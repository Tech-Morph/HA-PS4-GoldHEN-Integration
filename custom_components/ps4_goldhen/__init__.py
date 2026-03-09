"""The PS4 GoldHEN Integration."""
from __future__ import annotations

import asyncio
import contextlib
import io
import logging
import os
import re
import shutil
import time
from collections import deque
from datetime import timedelta
from functools import partial
from pathlib import Path
from typing import Any

from aiohttp import web
import voluptuous as vol

from homeassistant.components import frontend, panel_custom, websocket_api
from homeassistant.components.frontend import StaticPathConfig
from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    DOMAIN,
    PLATFORMS,
    CONF_PS4_HOST,
    CONF_BINLOADER_PORT,
    CONF_FTP_PORT,
    CONF_RPI_PORT,
    CONF_KLOG_PORT,
    DEFAULT_BINLOADER_PORT,
    DEFAULT_FTP_PORT,
    DEFAULT_RPI_PORT,
    DEFAULT_KLOG_PORT,
    PAYLOAD_DIR,
    TCP_PROBE_TIMEOUT,
    SENSOR_CURRENT_GAME,
    SENSOR_CPU_TEMP,
)

_LOGGER = logging.getLogger(__name__)

_FTP_POLL_INTERVAL = timedelta(seconds=30)
_SVC_SEND_PAYLOAD = "send_payload"

_PANEL_URL_PATH = "ps4_goldhen"
_PANEL_SIDEBAR_TITLE = "PS4 GoldHEN"
_PANEL_SIDEBAR_ICON = "mdi:sony-playstation"
_PANEL_WEBCOMPONENT = "ps4-goldhen-panel"

_JS_STATIC_URL = "/api/ps4_goldhen/frontend/ps4-goldhen-panel.js"
_JS_MODULE_URL = f"{_JS_STATIC_URL}?v=1.0.0"
_LOGO_STATIC_URL = "/api/ps4_goldhen/frontend/goldhen_logo.png"
_PAYLOAD_ICONS_STATIC_URL = "/api/ps4_goldhen/frontend/payload_icons"

_BUNDLED_PAYLOADS_DIRNAME = "bundled_payloads"

_HOME_SCREEN_STATE = "PlayStation Home Screen"
_IDLE_STATE = "Idle"
_HOME_SCREEN_APP_ID = "NPXS20001"

_TITLE_ID_RE = re.compile(r"[A-Z]{4}\d{5}")

_KLOG_LAUNCH_PATTERNS = (
    re.compile(r"launchApp\(\)\s*titleId=\[?([A-Z]{4}\d{5})\]?", re.IGNORECASE),
    re.compile(r"launchApp\(([A-Z]{4}\d{5})\)", re.IGNORECASE),
    re.compile(r"GameStartBoot\(([A-Z]{4}\d{5}),", re.IGNORECASE),
    re.compile(r"GameWillStart\(([A-Z]{4}\d{5}),", re.IGNORECASE),
    re.compile(r"createApp\s+([A-Z]{4}\d{5})", re.IGNORECASE),
    re.compile(r"title_id='([A-Z]{4}\d{5})'", re.IGNORECASE),
    re.compile(r"titleId\s*=\s*([A-Z]{4}\d{5})", re.IGNORECASE),
)

_KLOG_FOCUS_PATTERN = re.compile(
    r"AppFocusChanged\s+\[?([A-Z0-9]+)\]?\s*(?:->|-)\s*\[?([A-Z0-9]+)\]?",
    re.IGNORECASE,
)

_KLOG_HOME_SCENE_PATTERNS = (
    re.compile(
        r"OnFocusActiveSceneChanged\s+\[AppScreen\s*:\s*ApplicationScreenScene\]\s*->\s*\[ContentAreaScene\s*:\s*ContentAreaScene\]",
        re.IGNORECASE,
    ),
    re.compile(
        r"OnFocusActiveSceneChanged\s+AppScreen\s+ApplicationScreenScene\s*-\s*ContentAreaScene\s+ContentAreaScene",
        re.IGNORECASE,
    ),
)

_KLOG_GAME_SCENE_PATTERNS = (
    re.compile(
        r"OnFocusActiveSceneChanged\s+\[ContentAreaScene\s*:\s*ContentAreaScene\]\s*->\s*\[AppScreen\s*:\s*ApplicationScreenScene\]",
        re.IGNORECASE,
    ),
    re.compile(
        r"OnFocusActiveSceneChanged\s+ContentAreaScene\s+ContentAreaScene\s*-\s*AppScreen\s+ApplicationScreenScene",
        re.IGNORECASE,
    ),
)

_KLOG_IDLE_PATTERNS = (
    re.compile(r"Power Mode Change:\s*STANDBY", re.IGNORECASE),
    re.compile(r"Power Mode Change:\s*REST", re.IGNORECASE),
    re.compile(r"Power Mode Change:\s*OFF", re.IGNORECASE),
    re.compile(r"Power Mode Change:\s*SUSPEND", re.IGNORECASE),
)

_KLOG_SHELL_FG_PATTERN = re.compile(r"ShellUI is Fg", re.IGNORECASE)
_KLOG_SHELL_BG_PATTERN = re.compile(r"ShellUI is Bg", re.IGNORECASE)
_KLOG_VCS_SHELL_FOCUS_PATTERN = re.compile(
    r"Focus Change\..*appType\s*=?\s*1\s*\(?SHELL[_ ]?UI\)?",
    re.IGNORECASE,
)
_KLOG_VCS_BIGAPP_FOCUS_PATTERN = re.compile(
    r"Focus Change\..*appType\s*=?\s*5\s*\(?BIG[_ ]?APP\)?",
    re.IGNORECASE,
)
_KLOG_RESUME_APP_PATTERN = re.compile(r"resumeApp\(\)\s*appId", re.IGNORECASE)
_KLOG_SUSPEND_APP_PATTERN = re.compile(r"suspendApp\(\)\s*appId", re.IGNORECASE)

_KLOG_NOISE_PATTERNS = (
    re.compile(r"\bD88391\b", re.IGNORECASE),
    re.compile(r"\bfrom tbl_appbrowse_", re.IGNORECASE),
    re.compile(r"\bfrom tblappbrowse", re.IGNORECASE),
    re.compile(r"^\s*<\d+>\s*=+ bindValue", re.IGNORECASE),
    re.compile(r"^\s*<\d+>\s*=+ sql\s*=", re.IGNORECASE),
)

_KLOG_CPU_TEMP_PATTERN = re.compile(r"CPU.*?(\d+\.?\d*)\s*[°C]", re.IGNORECASE)


def _ensure_domain_root(hass: HomeAssistant) -> dict[str, Any]:
    hass.data.setdefault(DOMAIN, {})
    root: dict[str, Any] = hass.data[DOMAIN]
    root.setdefault("_global", {})
    g: dict[str, Any] = root["_global"]
    g.setdefault("panel_registered", False)
    g.setdefault("frontend_registered", False)
    g.setdefault("ws_registered", False)
    g.setdefault("bundled_payloads_installed", False)
    return root


def _global(hass: HomeAssistant) -> dict[str, Any]:
    root = _ensure_domain_root(hass)
    return root["_global"]


def _copy_bundled_payloads_to_config() -> int:
    """Copy bundled payloads shipped with the integration into /config/ps4_payloads."""
    src_dir = Path(__file__).parent / _BUNDLED_PAYLOADS_DIRNAME
    dst_dir = Path(PAYLOAD_DIR)

    if not src_dir.exists() or not src_dir.is_dir():
        return 0

    dst_dir.mkdir(parents=True, exist_ok=True)
    copied = 0

    for p in sorted(src_dir.iterdir()):
        if not p.is_file() or p.suffix.lower() not in (".bin", ".elf"):
            continue
        dst = dst_dir / p.name
        if dst.exists():
            continue
        shutil.copy2(str(p), str(dst))
        copied += 1

    return copied


def _list_payloads_blocking(payload_dir: str) -> list[str]:
    """Blocking payload directory scan."""
    p = Path(payload_dir)
    p.mkdir(parents=True, exist_ok=True)
    items: list[str] = []
    hidden = {"linux.bin"}

    for entry in sorted(p.iterdir(), key=lambda e: e.name):
        name = entry.name
        if name.lower() in hidden:
            continue
        if entry.is_file() and (name.lower().endswith(".bin") or name.lower().endswith(".elf")):
            items.append(name)

    return items


async def _register_frontend_and_panel_once(hass: HomeAssistant) -> None:
    g = _global(hass)

    if not g["frontend_registered"]:
        payload_icons_dir = hass.config.path(f"custom_components/{DOMAIN}/frontend/payload_icons")
        await hass.async_add_executor_job(partial(os.makedirs, payload_icons_dir, exist_ok=True))

        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(
                    _JS_STATIC_URL,
                    hass.config.path(f"custom_components/{DOMAIN}/frontend/ps4-goldhen-panel.js"),
                    False,
                ),
                StaticPathConfig(
                    _LOGO_STATIC_URL,
                    hass.config.path(f"custom_components/{DOMAIN}/frontend/goldhen_logo.png"),
                    False,
                ),
                StaticPathConfig(_PAYLOAD_ICONS_STATIC_URL, payload_icons_dir, False),
            ]
        )
        g["frontend_registered"] = True

    if not g["panel_registered"]:
        await panel_custom.async_register_panel(
            hass,
            frontend_url_path=_PANEL_URL_PATH,
            webcomponent_name=_PANEL_WEBCOMPONENT,
            module_url=_JS_MODULE_URL,
            sidebar_title=_PANEL_SIDEBAR_TITLE,
            sidebar_icon=_PANEL_SIDEBAR_ICON,
            config={},
            require_admin=False,
        )
        g["panel_registered"] = True


async def _send_bin_tcp(host: str, port: int, filepath: str, timeout: float = 30.0) -> None:
    """Stream a local payload file to host:port."""
    loop = asyncio.get_running_loop()

    try:
        data = await loop.run_in_executor(None, lambda: open(filepath, "rb").read())
    except Exception as err:
        raise HomeAssistantError(f"Cannot read payload file {filepath}: {err}") from err

    _LOGGER.info("Sending payload %s to %s:%d", os.path.basename(filepath), host, port)

    try:
        _reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
        writer.write(data)
        await asyncio.wait_for(writer.drain(), timeout=timeout)
        writer.close()
        await writer.wait_closed()
        _LOGGER.info("Payload sent successfully.")
    except Exception as err:
        raise HomeAssistantError(f"Connection to PS4 BinLoader failed: {err}") from err


def _is_real_game_title_id(value: str | None) -> bool:
    """Return True for real game/app title IDs, excluding shell/system IDs."""
    if not value:
        return False
    value = value.strip().upper()
    return bool(_TITLE_ID_RE.fullmatch(value)) and not value.startswith("NPXS")


class KlogStateMachine:
    """Resolve the current PS4 foreground state from the full live klog stream."""

    def __init__(self) -> None:
        self.current_state = _HOME_SCREEN_STATE
        self.last_reason = "init"
        self.last_signal_line = ""
        self.pending_title_id: str | None = None
        self.pending_reason: str | None = None
        self.pending_expires_at = 0.0
        self.recent_lines: deque[str] = deque(maxlen=250)

    def snapshot(self) -> dict[str, Any]:
        return {
            SENSOR_CURRENT_GAME: self.current_state,
            "state_reason": self.last_reason,
            "state_signal_line": self.last_signal_line,
            "pending_title_id": self.pending_title_id,
            "pending_reason": self.pending_reason,
        }

    def _set_state(self, state: str, reason: str, line: str) -> bool:
        changed = (
            self.current_state != state
            or self.last_reason != reason
            or self.last_signal_line != line[-300:]
        )
        self.current_state = state
        self.last_reason = reason
        self.last_signal_line = line[-300:]

        if state in (_HOME_SCREEN_STATE, _IDLE_STATE):
            self.pending_title_id = None
            self.pending_reason = None
            self.pending_expires_at = 0.0
        elif _is_real_game_title_id(state):
            self.pending_title_id = None
            self.pending_reason = None
            self.pending_expires_at = 0.0

        return changed

    def _queue_game(self, title_id: str, reason: str, line: str) -> bool:
        title_id = title_id.upper()
        if not _is_real_game_title_id(title_id):
            return False
        self.pending_title_id = title_id
        self.pending_reason = reason
        self.pending_expires_at = time.monotonic() + 15.0
        self.last_reason = reason
        self.last_signal_line = line[-300:]
        return False

    def _pending_game_is_alive(self) -> bool:
        return bool(self.pending_title_id) and time.monotonic() <= self.pending_expires_at

    def _clear_expired_pending(self) -> None:
        if self.pending_title_id and time.monotonic() > self.pending_expires_at:
            self.pending_title_id = None
            self.pending_reason = None
            self.pending_expires_at = 0.0

    def ingest(self, line: str) -> bool:
        self.recent_lines.append(line[-300:])
        self._clear_expired_pending()

        for pattern in _KLOG_IDLE_PATTERNS:
            if pattern.search(line):
                return self._set_state(_IDLE_STATE, "power_idle", line)

        for pattern in _KLOG_NOISE_PATTERNS:
            if pattern.search(line):
                return False

        match = _KLOG_FOCUS_PATTERN.search(line)
        if match:
            old_app = match.group(1).strip().upper()
            new_app = match.group(2).strip().upper()

            if new_app == _HOME_SCREEN_APP_ID:
                return self._set_state(_HOME_SCREEN_STATE, "focus_to_home", line)

            if _is_real_game_title_id(new_app):
                return self._set_state(new_app, "focus_to_game", line)

            if old_app == _HOME_SCREEN_APP_ID and _is_real_game_title_id(new_app):
                return self._set_state(new_app, "focus_home_to_game", line)

        for pattern in _KLOG_LAUNCH_PATTERNS:
            match = pattern.search(line)
            if match:
                title_id = match.group(1).strip().upper()
                if _is_real_game_title_id(title_id):
                    return self._queue_game(title_id, "launch_hint", line)

        if self._pending_game_is_alive():
            if _KLOG_VCS_BIGAPP_FOCUS_PATTERN.search(line):
                return self._set_state(self.pending_title_id, "bigapp_focus_confirmed", line)

            for pattern in _KLOG_GAME_SCENE_PATTERNS:
                if pattern.search(line):
                    return self._set_state(self.pending_title_id, "scene_game_confirmed", line)

            if _KLOG_RESUME_APP_PATTERN.search(line):
                return self._set_state(self.pending_title_id, "resume_confirmed", line)

            if _KLOG_SHELL_BG_PATTERN.search(line):
                return self._set_state(self.pending_title_id, "shell_bg_game_confirmed", line)

        for pattern in _KLOG_HOME_SCENE_PATTERNS:
            if pattern.search(line):
                return self._set_state(_HOME_SCREEN_STATE, "scene_home_confirmed", line)

        if _KLOG_VCS_SHELL_FOCUS_PATTERN.search(line):
            return self._set_state(_HOME_SCREEN_STATE, "shell_focus_confirmed", line)

        if _KLOG_SHELL_FG_PATTERN.search(line):
            return self._set_state(_HOME_SCREEN_STATE, "shell_fg_confirmed", line)

        if _KLOG_SUSPEND_APP_PATTERN.search(line) and self.current_state not in (_HOME_SCREEN_STATE, _IDLE_STATE):
            return self._set_state(_HOME_SCREEN_STATE, "suspend_to_home_hint", line)

        return False


def _parse_klog_line(line: str, entry_data: dict[str, Any]) -> bool:
    """Parse a single klog line and update entry_data in place."""
    state_machine: KlogStateMachine = entry_data["klog_state_machine"]
    state_changed = state_machine.ingest(line)

    klog_data = entry_data["klog_data"]
    klog_data.update(state_machine.snapshot())

    match = _KLOG_CPU_TEMP_PATTERN.search(line)
    if match:
        try:
            klog_data[SENSOR_CPU_TEMP] = float(match.group(1))
        except ValueError:
            pass

    return state_changed


async def _klog_listener_task(
    hass: HomeAssistant,
    entry_id: str,
    host: str,
    port: int,
    coordinator: DataUpdateCoordinator,
) -> None:
    """Background task to listen to klog stream and update coordinator."""
    _LOGGER.info("Starting klog listener for %s:%d", host, port)

    while True:
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=10)
            _LOGGER.info("Connected to klog at %s:%d", host, port)

            text_buffer = ""

            while True:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=30)
                if not chunk:
                    _LOGGER.warning("Klog connection closed by PS4")
                    break

                text_buffer += chunk.decode("utf-8", errors="replace")
                parts = re.split(r"\r\n|\n|\r", text_buffer)
                text_buffer = parts.pop() if parts else ""

                for line in parts:
                    if not line:
                        continue

                    entry_data = hass.data[DOMAIN].get(entry_id)
                    if not entry_data or "klog_data" not in entry_data:
                        continue

                    _parse_klog_line(line, entry_data)
                    coordinator.async_set_updated_data(
                        {**(coordinator.data or {}), **entry_data["klog_data"]}
                    )

            if text_buffer:
                entry_data = hass.data[DOMAIN].get(entry_id)
                if entry_data and "klog_data" in entry_data:
                    _parse_klog_line(text_buffer, entry_data)
                    coordinator.async_set_updated_data(
                        {**(coordinator.data or {}), **entry_data["klog_data"]}
                    )

            writer.close()
            await writer.wait_closed()

        except asyncio.TimeoutError:
            _LOGGER.debug("Klog connection timeout, retrying...")
        except asyncio.CancelledError:
            _LOGGER.info("Klog listener cancelled")
            raise
        except Exception as err:
            _LOGGER.warning("Klog listener error: %s, retrying in 30s", err)

        await asyncio.sleep(30)


@websocket_api.websocket_command({vol.Required("type"): "ps4_goldhen/list_entries"})
@websocket_api.async_response
async def ws_list_entries(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    entries = hass.config_entries.async_entries(DOMAIN)
    out = [
        {
            "entry_id": entry.entry_id,
            "title": entry.title,
            "ps4_host": entry.data.get(CONF_PS4_HOST),
            "ftp_port": entry.data.get(CONF_FTP_PORT, DEFAULT_FTP_PORT),
            "binloader_port": entry.data.get(CONF_BINLOADER_PORT, DEFAULT_BINLOADER_PORT),
            "klog_port": entry.data.get(CONF_KLOG_PORT, DEFAULT_KLOG_PORT),
            "rpi_port": entry.data.get(CONF_RPI_PORT, DEFAULT_RPI_PORT),
        }
        for entry in entries
    ]
    connection.send_result(msg["id"], {"entries": out})


@websocket_api.websocket_command({vol.Required("type"): "ps4_goldhen/list_payloads"})
@websocket_api.async_response
async def ws_list_payloads(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    try:
        items = await hass.async_add_executor_job(_list_payloads_blocking, PAYLOAD_DIR)
        connection.send_result(msg["id"], {"payloads": items, "payload_dir": PAYLOAD_DIR})
    except Exception as err:
        connection.send_error(msg["id"], "list_error", str(err))


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    host = entry.data[CONF_PS4_HOST]
    binloader_port = entry.data.get(CONF_BINLOADER_PORT, DEFAULT_BINLOADER_PORT)
    ftp_port = entry.data.get(CONF_FTP_PORT, DEFAULT_FTP_PORT)
    rpi_port = entry.data.get(CONF_RPI_PORT, DEFAULT_RPI_PORT)
    klog_port = entry.data.get(CONF_KLOG_PORT, DEFAULT_KLOG_PORT)

    async def _poll_ftp() -> dict[str, Any]:
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, ftp_port),
                timeout=TCP_PROBE_TIMEOUT,
            )
            writer.close()
            await writer.wait_closed()
            return {"ftp_reachable": True}
        except Exception:
            return {"ftp_reachable": False}

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"{DOMAIN}_{host}",
        update_method=_poll_ftp,
        update_interval=_FTP_POLL_INTERVAL,
    )

    await coordinator.async_config_entry_first_refresh()

    root = _ensure_domain_root(hass)

    prev = root.get(entry.entry_id)
    if isinstance(prev, dict) and prev.get("klog_task") is not None:
        task = prev["klog_task"]
        with contextlib.suppress(Exception):
            task.cancel()

    state_machine = KlogStateMachine()

    root[entry.entry_id] = {
        "coordinator": coordinator,
        "host": host,
        "binloader_port": binloader_port,
        "ftp_port": ftp_port,
        "rpi_port": rpi_port,
        "klog_port": klog_port,
        "klog_state_machine": state_machine,
        "klog_data": {
            **state_machine.snapshot(),
            SENSOR_CPU_TEMP: None,
        },
    }

    klog_task = entry.async_create_background_task(
        hass,
        _klog_listener_task(hass, entry.entry_id, host, klog_port, coordinator),
        name=f"{DOMAIN}_klog_{entry.entry_id}",
    )
    root[entry.entry_id]["klog_task"] = klog_task

    g = _global(hass)

    if not g["ws_registered"]:
        websocket_api.async_register_command(hass, ws_list_entries)
        websocket_api.async_register_command(hass, ws_list_payloads)

        from .websocket import async_setup as async_setup_websocket

        async_setup_websocket(hass)
        g["ws_registered"] = True

    await _register_frontend_and_panel_once(hass)

    if not g.get("bundled_payloads_installed"):
        await hass.async_add_executor_job(_copy_bundled_payloads_to_config)
        g["bundled_payloads_installed"] = True

    _SEND_PAYLOAD_SCHEMA = vol.Schema(
        {
            vol.Required("payload_file"): str,
            vol.Optional("ps4_host"): str,
            vol.Optional("binloader_port"): vol.All(vol.Coerce(int), vol.Range(min=1024, max=65535)),
            vol.Optional("timeout", default=30): vol.All(vol.Coerce(float), vol.Range(min=1)),
        }
    )

    async def handle_send_payload(call: ServiceCall) -> None:
        p_file = call.data["payload_file"]
        t_host = call.data.get("ps4_host") or host
        t_port = int(call.data.get("binloader_port") or binloader_port)
        filepath = p_file if os.path.isabs(p_file) else os.path.join(PAYLOAD_DIR, p_file)
        await _send_bin_tcp(t_host, t_port, filepath, call.data.get("timeout", 30))

    if not hass.services.has_service(DOMAIN, _SVC_SEND_PAYLOAD):
        hass.services.async_register(DOMAIN, _SVC_SEND_PAYLOAD, handle_send_payload, schema=_SEND_PAYLOAD_SCHEMA)

    hass.http.register_view(PS4FTPDownloadView())
    hass.http.register_view(PS4FTPUploadView())

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


class PS4FTPDownloadView(HomeAssistantView):
    url = "/api/ps4_goldhen/ftp/download"
    name = "api:ps4_goldhen:ftp_download"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        import ftplib

        entry_id = request.query.get("entry_id")
        path = request.query.get("path")

        if not entry_id or not path:
            return web.Response(text="Missing entry_id or path", status=400)

        data = _ensure_domain_root(request.app["hass"]).get(entry_id)
        if not data:
            return web.Response(text="Entry not found", status=404)

        def _get_file():
            buffer = io.BytesIO()
            with ftplib.FTP() as ftp:
                ftp.connect(data["host"], int(data["ftp_port"]), timeout=15)
                ftp.login()
                ftp.retrbinary(f"RETR {path}", buffer.write)
            return buffer.getvalue()

        try:
            content = await request.app["hass"].async_add_executor_job(_get_file)
            return web.Response(
                body=content,
                content_type="application/octet-stream",
                headers={"Content-Disposition": f'attachment; filename="{os.path.basename(path)}"'},
            )
        except Exception as err:
            return web.Response(text=f"FTP Error: {err}", status=500)


class PS4FTPUploadView(HomeAssistantView):
    url = "/api/ps4_goldhen/ftp/upload"
    name = "api:ps4_goldhen:ftp_upload"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        import ftplib

        reader = await request.multipart()
        entry_id, path, file_field = None, None, None

        while True:
            part = await reader.next()
            if part is None:
                break
            if part.name == "entry_id":
                entry_id = (await part.read(decode=True)).decode()
            elif part.name == "path":
                path = (await part.read(decode=True)).decode()
            elif part.name == "file":
                file_field = part
                break

        if not all([entry_id, path, file_field]):
            return web.Response(text="Missing data", status=400)

        data = _ensure_domain_root(request.app["hass"]).get(entry_id)
        if not data:
            return web.Response(text="Entry not found", status=404)

        full_dest = (path.rstrip("/") + "/" + file_field.filename).replace("//", "/")

        def _upload_file(content):
            with ftplib.FTP() as ftp:
                ftp.connect(data["host"], int(data["ftp_port"]), timeout=15)
                ftp.login()
                ftp.storbinary(f"STOR {full_dest}", io.BytesIO(content))

        try:
            await request.app["hass"].async_add_executor_job(_upload_file, await file_field.read(decode=True))
            return web.json_response({"success": True, "path": full_dest})
        except Exception as err:
            return web.Response(text=f"FTP Upload Error: {err}", status=500)


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    entry_data = _ensure_domain_root(hass).get(entry.entry_id)
    if entry_data and entry_data.get("klog_task") is not None:
        task = entry_data["klog_task"]
        task.cancel()
        with contextlib.suppress(Exception):
            await asyncio.gather(task, return_exceptions=True)

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        _ensure_domain_root(hass).pop(entry.entry_id, None)

    return unload_ok
