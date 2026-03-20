"""The PS4 GoldHEN Integration."""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import logging
import os
import re
import shutil
from collections import deque
from datetime import timedelta
from functools import partial
from pathlib import Path
from typing import Any

from aiohttp import web
import voluptuous as vol

from homeassistant.components import panel_custom, websocket_api
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
    SENSOR_SOC_TEMP,
    SENSOR_TITLE_ID,
    SENSOR_GAME_NAME,
    SENSOR_GAME_COVER,
    SENSOR_KLOG_LAST_LINE,
    SENSOR_SOC_POWER,
    SENSOR_CPU_POWER,
    SENSOR_GPU_POWER,
    SENSOR_TOTAL_POWER,
    SENSOR_FAN_DUTY,
    SENSOR_FW_VERSION,
    SENSOR_HW_MODEL,
    SENSOR_CONSOLE_ID,
    EVENT_KLOG_LINE,
    HOME_SCREEN,
    APP_DB_REMOTE,
    APP_DB_LOCAL,
    DB_REFRESH_INTERVAL,
)
from . import db as ps4_db

_LOGGER = logging.getLogger(__name__)

_FTP_POLL_INTERVAL  = timedelta(seconds=5)
_PS4STATE_JSON_PATH = "/data/GoldHEN/ps4_state.json"
_SVC_SEND_PAYLOAD   = "send_payload"

_PANEL_URL_PATH       = "ps4_goldhen"
_PANEL_SIDEBAR_TITLE  = "PS4 GoldHEN"
_PANEL_SIDEBAR_ICON   = "mdi:sony-playstation"
_PANEL_WEBCOMPONENT   = "ps4-goldhen-panel"

_JS_STATIC_URL            = "/api/ps4_goldhen/frontend/ps4-goldhen-panel.js"
_JS_MODULE_URL            = f"{_JS_STATIC_URL}?v=1.0.0"
_LOGO_STATIC_URL          = "/api/ps4_goldhen/frontend/goldhen_logo.png"
_PAYLOAD_ICONS_STATIC_URL = "/api/ps4_goldhen/frontend/payload_icons"

_BUNDLED_PAYLOADS_DIRNAME = "bundled_payloads"

_HOME_SCREEN_STATE  = HOME_SCREEN
_IDLE_STATE         = "Idle"
_HOME_SCREEN_APP_ID = "NPXS20001"

_TITLE_ID_RE = re.compile(r"[A-Z]{4}\d{5}")

_KLOG_SL_FOCUS_PATTERN = re.compile(
    r"\[SL\]\s+AppFocusChanged\s+\[([A-Z0-9]+)\]\s*->\s*\[([A-Z0-9]+)\]",
    re.IGNORECASE,
)
_KLOG_LNC_LAUNCH_PATTERN = re.compile(
    r"\[SceLncService\]\s+launchApp\(([A-Z]{4}\d{5})\)",
    re.IGNORECASE,
)
_KLOG_BGFT_GAME_START = re.compile(
    r"\[BGFT\].*GameWillStart\(([A-Z]{4}\d{5}),",
    re.IGNORECASE,
)
_KLOG_GAME_CLOSE_PATTERN  = re.compile(r"Game Close detected", re.IGNORECASE)
_KLOG_BGFT_GAME_STOPPED   = re.compile(
    r"\[BGFT\].*GameStopped\(([A-Z]{4}\d{5}),",
    re.IGNORECASE,
)
_KLOG_EXIT_TO_HOME_PATTERN = re.compile(
    r"OnFocusActiveSceneChanged\s+\[ApplicationExitScene\s*:\s*ApplicationExitScene\]\s*->\s*\[ContentAreaScene\s*:\s*ContentAreaScene\]",
    re.IGNORECASE,
)

_KLOG_NOISE_PATTERNS = (
    re.compile(r"\bD88391\b",                    re.IGNORECASE),
    re.compile(r"\bfrom tbl_appbrowse_",         re.IGNORECASE),
    re.compile(r"\bfrom tblappbrowse",           re.IGNORECASE),
    re.compile(r"^\s*<\d+>\s*=+ bindValue",      re.IGNORECASE),
    re.compile(r"^\s*<\d+>\s*=+ sql\s*=",        re.IGNORECASE),
    re.compile(r"^\s*======== sql\s*=",          re.IGNORECASE),
    re.compile(r"^\s*======== bindValue",        re.IGNORECASE),
    re.compile(r"^\s*======== limit\s*=",        re.IGNORECASE),
    re.compile(r"uhub\d+: giving up port",       re.IGNORECASE),
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _ensure_domain_root(hass: HomeAssistant) -> dict[str, Any]:
    hass.data.setdefault(DOMAIN, {})
    root: dict[str, Any] = hass.data[DOMAIN]
    root.setdefault("_global", {})
    g: dict[str, Any] = root["_global"]
    g.setdefault("panel_registered",           False)
    g.setdefault("frontend_registered",        False)
    g.setdefault("ws_registered",              False)
    g.setdefault("bundled_payloads_installed", False)
    g.setdefault("cover_view_registered",      False)
    return root


def _global(hass: HomeAssistant) -> dict[str, Any]:
    return _ensure_domain_root(hass)["_global"]


def _copy_bundled_payloads_to_config() -> int:
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
    p = Path(payload_dir)
    p.mkdir(parents=True, exist_ok=True)
    hidden = {"linux.bin"}
    return [
        e.name for e in sorted(p.iterdir(), key=lambda e: e.name)
        if e.is_file()
        and e.name.lower() not in hidden
        and e.suffix.lower() in (".bin", ".elf")
    ]


async def _register_frontend_and_panel_once(hass: HomeAssistant) -> None:
    g = _global(hass)
    if not g["frontend_registered"]:
        payload_icons_dir = hass.config.path(
            f"custom_components/{DOMAIN}/frontend/payload_icons"
        )
        await hass.async_add_executor_job(
            partial(os.makedirs, payload_icons_dir, exist_ok=True)
        )
        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(
                    _JS_STATIC_URL,
                    hass.config.path(
                        f"custom_components/{DOMAIN}/frontend/ps4-goldhen-panel.js"
                    ),
                    False,
                ),
                StaticPathConfig(
                    _LOGO_STATIC_URL,
                    hass.config.path(
                        f"custom_components/{DOMAIN}/frontend/goldhen_logo.png"
                    ),
                    False,
                ),
                StaticPathConfig(
                    _PAYLOAD_ICONS_STATIC_URL,
                    payload_icons_dir,
                    False,
                ),
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


async def _send_bin_tcp(
    host: str, port: int, filepath: str, timeout: float = 30.0
) -> None:
    loop = asyncio.get_running_loop()
    try:
        data = await loop.run_in_executor(None, lambda: open(filepath, "rb").read())
    except Exception as err:
        raise HomeAssistantError(f"Cannot read payload file {filepath}: {err}") from err

    _LOGGER.info("Sending payload %s to %s:%d", os.path.basename(filepath), host, port)
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        writer.write(data)
        await asyncio.wait_for(writer.drain(), timeout=timeout)
        writer.close()
        await writer.wait_closed()
        _LOGGER.info("Payload sent successfully.")
    except Exception as err:
        raise HomeAssistantError(
            f"Connection to PS4 BinLoader failed: {err}"
        ) from err


def _is_real_game_title_id(value: str | None) -> bool:
    if not value:
        return False
    value = value.strip().upper()
    return bool(_TITLE_ID_RE.fullmatch(value)) and not value.startswith("NPXS")


# ── Klog state machine ─────────────────────────────────────────────────────────

class KlogStateMachine:
    def __init__(self) -> None:
        self.current_title_id: str | None = None
        self.last_reason       = "init"
        self.last_signal_line  = ""
        self.recent_lines: deque[str] = deque(maxlen=250)
        self.klog_connected: bool = True
        self._pending_launch: str | None = None

    def snapshot(self) -> dict[str, Any]:
        state = self.current_title_id if self.current_title_id else _HOME_SCREEN_STATE
        return {
            SENSOR_CURRENT_GAME:  state,
            SENSOR_TITLE_ID:      self.current_title_id,
            "state_reason":       self.last_reason,
            "state_signal_line":  self.last_signal_line,
            "pending_title_id":   self._pending_launch,
            "klog_connected":     self.klog_connected,
        }

    def ingest(self, line: str) -> bool:
        self.recent_lines.append(line[-300:])
        self.klog_connected = True

        for pattern in _KLOG_NOISE_PATTERNS:
            if pattern.search(line):
                return False

        m = _KLOG_SL_FOCUS_PATTERN.search(line)
        if m:
            new_app = m.group(2).strip().upper()
            if _is_real_game_title_id(new_app):
                return self._set(new_app, "sl_focus_game", line)
            elif new_app == _HOME_SCREEN_APP_ID:
                if self._pending_launch:
                    _LOGGER.debug(
                        "Ignoring sl_focus_home — launch pending for %s",
                        self._pending_launch,
                    )
                    return False
                if self.current_title_id is not None:
                    return self._set(None, "sl_focus_home", line)
            return False

        m = _KLOG_BGFT_GAME_START.search(line)
        if m:
            tid = m.group(1).strip().upper()
            if _is_real_game_title_id(tid):
                self._pending_launch = tid
                return self._set(tid, "bgft_game_will_start", line)

        m = _KLOG_LNC_LAUNCH_PATTERN.search(line)
        if m:
            tid = m.group(1).strip().upper()
            if _is_real_game_title_id(tid):
                self._pending_launch = tid
                self.last_reason      = "lnc_launch_pending"
                self.last_signal_line = line[-300:]
                return False

        if _KLOG_GAME_CLOSE_PATTERN.search(line):
            if self.current_title_id is not None:
                return self._set(None, "game_close_detected", line)

        m = _KLOG_BGFT_GAME_STOPPED.search(line)
        if m:
            tid = m.group(1).strip().upper()
            if self.current_title_id == tid:
                return self._set(None, "bgft_game_stopped", line)

        if _KLOG_EXIT_TO_HOME_PATTERN.search(line):
            if self._pending_launch:
                _LOGGER.debug(
                    "Ignoring exit_scene_to_home — launch pending for %s",
                    self._pending_launch,
                )
                return False
            if self.current_title_id is not None:
                return self._set(None, "exit_scene_to_home", line)

        return False

    def _set(self, title_id: str | None, reason: str, line: str) -> bool:
        changed                = self.current_title_id != title_id
        self.current_title_id  = title_id
        self._pending_launch   = None
        self.last_reason       = reason
        self.last_signal_line  = line[-300:]
        return changed


# ── Klog line parser ───────────────────────────────────────────────────────────

async def _force_db_refresh(
    hass: HomeAssistant,
    entry_id: str,
    coordinator: DataUpdateCoordinator,
) -> None:
    entry_data = hass.data[DOMAIN].get(entry_id)
    if not entry_data:
        return
    try:
        game_map = await hass.async_add_executor_job(
            ps4_db.download_and_parse,
            entry_data["host"],
            entry_data["ftp_port"],
        )
        entry_data["game_map"] = game_map
        klog_data = entry_data["klog_data"]
        tid = klog_data.get(SENSOR_TITLE_ID)
        if tid and tid in game_map:
            klog_data[SENSOR_GAME_NAME]  = game_map[tid].get("name")
            klog_data[SENSOR_GAME_COVER] = game_map[tid].get("cover")
            coordinator.async_set_updated_data(
                {**(coordinator.data or {}), **klog_data}
            )
        _LOGGER.info(
            "[ps4_goldhen] force db refresh done — %d titles", len(game_map)
        )
    except Exception as err:
        _LOGGER.warning("[ps4_goldhen] force db refresh failed: %s", err)


def _parse_klog_line(
    hass: HomeAssistant,
    line: str,
    entry_data: dict[str, Any],
    entry_id: str,
) -> bool:
    state_machine: KlogStateMachine = entry_data["klog_state_machine"]

    for pattern in _KLOG_NOISE_PATTERNS:
        if pattern.search(line):
            return False

    state_changed = state_machine.ingest(line)

    klog_data = entry_data["klog_data"]
    klog_data.update(state_machine.snapshot())
    klog_data[SENSOR_KLOG_LAST_LINE] = line[:300]

    tid = klog_data.get(SENSOR_TITLE_ID)
    if tid:
        game_info = entry_data.get("game_map", {}).get(tid, {})
        klog_data[SENSOR_GAME_NAME]  = game_info.get("name")
        klog_data[SENSOR_GAME_COVER] = game_info.get("cover")
        # game_map empty or title missing — refresh app.db immediately
        if not game_info.get("name"):
            coordinator = entry_data.get("coordinator")
            if coordinator:
                asyncio.ensure_future(
                    _force_db_refresh(hass, entry_id, coordinator)
                )
    else:
        klog_data[SENSOR_GAME_NAME]  = None
        klog_data[SENSOR_GAME_COVER] = None

    hass.bus.async_fire(
        EVENT_KLOG_LINE,
        {
            "entry_id": entry_id,
            "message":  line[:300],
            "title_id": klog_data.get(SENSOR_TITLE_ID),
        },
    )
    return state_changed


# ── Background tasks ───────────────────────────────────────────────────────────

async def _klog_listener_task(
    hass: HomeAssistant,
    entry_id: str,
    host: str,
    port: int,
    coordinator: DataUpdateCoordinator,
) -> None:
    _LOGGER.info("Starting klog listener for %s:%d", host, port)

    while True:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=10
            )
            _LOGGER.info("Connected to klog at %s:%d", host, port)

            entry_data = hass.data[DOMAIN].get(entry_id)
            if entry_data:
                entry_data["klog_state_machine"].klog_connected = True

            text_buffer = ""

            while True:
                try:
                    chunk = await asyncio.wait_for(reader.read(4096), timeout=30.0)
                except asyncio.TimeoutError:
                    continue

                if not chunk:
                    _LOGGER.warning("Klog connection closed by PS4")
                    break

                text_buffer += chunk.decode("utf-8", errors="replace")
                lines        = text_buffer.split("\n")
                text_buffer  = lines[-1]

                entry_data = hass.data[DOMAIN].get(entry_id)
                if not entry_data:
                    break

                changed = False
                for line in lines[:-1]:
                    line = line.rstrip("\r")
                    if line and _parse_klog_line(hass, line, entry_data, entry_id):
                        changed = True

                if changed:
                    coordinator.async_set_updated_data(
                        {**(coordinator.data or {}), **entry_data["klog_data"]}
                    )

            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

        except asyncio.CancelledError:
            _LOGGER.info("Klog listener task cancelled")
            raise
        except Exception as err:
            err_str = str(err)
            if "111" in err_str or "Connect call failed" in err_str:
                _LOGGER.debug(
                    "Klog unavailable (PS4 off/rest) %s:%d: %s", host, port, err
                )
            else:
                _LOGGER.warning(
                    "Klog connection error for %s:%d: %s", host, port, err
                )

        entry_data = hass.data[DOMAIN].get(entry_id)
        if entry_data:
            entry_data["klog_state_machine"].klog_connected = False
            entry_data["klog_data"]["klog_connected"] = False
            coordinator.async_set_updated_data(
                {**(coordinator.data or {}), **entry_data["klog_data"]}
            )

        _LOGGER.info("Reconnecting to klog in 10s...")
        await asyncio.sleep(10)


async def _db_refresh_task(
    hass: HomeAssistant,
    entry_id: str,
    coordinator: DataUpdateCoordinator,
) -> None:
    while True:
        entry_data = hass.data[DOMAIN].get(entry_id)
        if not entry_data:
            return

        host     = entry_data["host"]
        ftp_port = entry_data["ftp_port"]

        try:
            game_map = await hass.async_add_executor_job(
                ps4_db.download_and_parse, host, ftp_port
            )
            entry_data["game_map"] = game_map
            _LOGGER.info(
                "app.db refreshed for %s — %d titles loaded", host, len(game_map)
            )

            klog_data = entry_data["klog_data"]
            tid = klog_data.get(SENSOR_TITLE_ID)
            if tid and tid in game_map:
                klog_data[SENSOR_GAME_NAME]  = game_map[tid].get("name")
                klog_data[SENSOR_GAME_COVER] = game_map[tid].get("cover")
                coordinator.async_set_updated_data(
                    {**(coordinator.data or {}), **klog_data}
                )

        except asyncio.CancelledError:
            _LOGGER.info("DB refresh task cancelled")
            raise
        except Exception as err:
            _LOGGER.warning("app.db refresh failed for %s: %s", host, err)

        await asyncio.sleep(DB_REFRESH_INTERVAL)


# ── WebSocket commands ─────────────────────────────────────────────────────────

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
            "entry_id":       entry.entry_id,
            "title":          entry.title,
            "ps4_host":       entry.data.get(CONF_PS4_HOST),
            "ftp_port":       entry.data.get(CONF_FTP_PORT,       DEFAULT_FTP_PORT),
            "binloader_port": entry.data.get(CONF_BINLOADER_PORT, DEFAULT_BINLOADER_PORT),
            "klog_port":      entry.data.get(CONF_KLOG_PORT,      DEFAULT_KLOG_PORT),
            "rpi_port":       entry.data.get(CONF_RPI_PORT,       DEFAULT_RPI_PORT),
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
        items = await hass.async_add_executor_job(
            _list_payloads_blocking, PAYLOAD_DIR
        )
        connection.send_result(
            msg["id"], {"payloads": items, "payload_dir": PAYLOAD_DIR}
        )
    except Exception as err:
        connection.send_error(msg["id"], "list_error", str(err))


# ── FTP JSON poll ──────────────────────────────────────────────────────────────

async def _poll_ftp_json(
    host: str,
    ftp_port: int,
    entry_id: str,
    hass: HomeAssistant,
    coordinator: DataUpdateCoordinator,
) -> dict[str, Any]:
    entry_data = _ensure_domain_root(hass).get(entry_id, {})
    existing   = dict(entry_data.get("klog_data", {}))

    reader = writer = None
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, ftp_port), timeout=TCP_PROBE_TIMEOUT
        )

        async def _readline() -> str:
            return (await reader.readline()).decode(errors="ignore")

        def _send(cmd: str) -> None:
            writer.write((cmd + "\r\n").encode())

        await _readline()  # banner

        _send("USER anonymous")
        await _readline()  # 230

        _send("TYPE I")
        await _readline()  # 200

        _send("PASV")
        pasv_line = await _readline()
        start = pasv_line.find("(")
        end   = pasv_line.find(")", start + 1)
        if start == -1 or end == -1:
            raise ValueError(f"PASV parse error: {pasv_line!r}")
        nums      = pasv_line[start + 1 : end].split(",")
        data_host = ".".join(nums[:4])
        data_port = (int(nums[4]) << 8) + int(nums[5])

        dreader, dwriter = await asyncio.wait_for(
            asyncio.open_connection(data_host, data_port), timeout=TCP_PROBE_TIMEOUT
        )

        _send(f"RETR {_PS4STATE_JSON_PATH}")
        await _readline()  # 150

        chunks: list[bytes] = []
        while True:
            chunk = await dreader.read(4096)
            if not chunk:
                break
            chunks.append(chunk)
        dwriter.close()
        with contextlib.suppress(Exception):
            await dwriter.wait_closed()

        await _readline()  # 226

        body = b"".join(chunks).decode(errors="ignore").strip()
        if body:
            parsed = json.loads(body)
            existing[SENSOR_CPU_TEMP]    = parsed.get("cpu_temp")
            existing[SENSOR_SOC_TEMP]    = parsed.get("soc_temp")
            existing[SENSOR_SOC_POWER]   = parsed.get("soc_power_w")
            existing[SENSOR_CPU_POWER]   = parsed.get("cpu_power_w")
            existing[SENSOR_GPU_POWER]   = parsed.get("gpu_power_w")
            existing[SENSOR_TOTAL_POWER] = parsed.get("total_power_w")
            existing[SENSOR_FAN_DUTY]    = parsed.get("fan_duty")
            existing[SENSOR_FW_VERSION]  = parsed.get("fw_version")
            existing[SENSOR_HW_MODEL]    = parsed.get("hw_model")
            existing[SENSOR_CONSOLE_ID]  = parsed.get("console_id")

        existing["ftp_reachable"] = True

    except asyncio.CancelledError:
        raise
    except Exception as err:
        _LOGGER.debug("PS4StateJSON FTP poll failed (%s): %s", host, err)
        existing["ftp_reachable"] = False
    finally:
        if writer is not None:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    if entry_id in _ensure_domain_root(hass):
        _ensure_domain_root(hass)[entry_id]["klog_data"].update(
            {k: existing[k] for k in (
                SENSOR_CPU_TEMP,    SENSOR_SOC_TEMP,
                SENSOR_SOC_POWER,   SENSOR_CPU_POWER,
                SENSOR_GPU_POWER,   SENSOR_TOTAL_POWER,
                SENSOR_FAN_DUTY,    SENSOR_FW_VERSION,
                SENSOR_HW_MODEL,    SENSOR_CONSOLE_ID,
                "ftp_reachable",
            ) if k in existing}
        )

    return existing


# ── Config entry setup ─────────────────────────────────────────────────────────

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    host           = entry.data[CONF_PS4_HOST]
    binloader_port = entry.data.get(CONF_BINLOADER_PORT, DEFAULT_BINLOADER_PORT)
    ftp_port       = entry.data.get(CONF_FTP_PORT,       DEFAULT_FTP_PORT)
    rpi_port       = entry.data.get(CONF_RPI_PORT,       DEFAULT_RPI_PORT)
    klog_port      = entry.data.get(CONF_KLOG_PORT,      DEFAULT_KLOG_PORT)

    root          = _ensure_domain_root(hass)
    state_machine = KlogStateMachine()

    root[entry.entry_id] = {
        "host":               host,
        "binloader_port":     binloader_port,
        "ftp_port":           ftp_port,
        "rpi_port":           rpi_port,
        "klog_port":          klog_port,
        "klog_state_machine": state_machine,
        "klog_data": {
            **state_machine.snapshot(),
            SENSOR_CPU_TEMP:       None,
            SENSOR_SOC_TEMP:       None,
            SENSOR_GAME_NAME:      None,
            SENSOR_GAME_COVER:     None,
            SENSOR_KLOG_LAST_LINE: None,
            SENSOR_SOC_POWER:      None,
            SENSOR_CPU_POWER:      None,
            SENSOR_GPU_POWER:      None,
            SENSOR_TOTAL_POWER:    None,
            SENSOR_FAN_DUTY:       None,
            SENSOR_FW_VERSION:     None,
            SENSOR_HW_MODEL:       None,
            SENSOR_CONSOLE_ID:     None,
            "ftp_reachable":       False,
        },
        "game_map": {},
    }

    async def _poll_update() -> dict[str, Any]:
        return await _poll_ftp_json(host, ftp_port, entry.entry_id, hass, coordinator)

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"{DOMAIN}_{host}",
        update_method=_poll_update,
        update_interval=_FTP_POLL_INTERVAL,
    )

    await coordinator.async_config_entry_first_refresh()
    root[entry.entry_id]["coordinator"] = coordinator

    klog_task = entry.async_create_background_task(
        hass,
        _klog_listener_task(hass, entry.entry_id, host, klog_port, coordinator),
        name=f"{DOMAIN}_klog_{entry.entry_id}",
    )
    root[entry.entry_id]["klog_task"] = klog_task

    db_task = entry.async_create_background_task(
        hass,
        _db_refresh_task(hass, entry.entry_id, coordinator),
        name=f"{DOMAIN}_db_{entry.entry_id}",
    )
    root[entry.entry_id]["db_task"] = db_task

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

    if not g.get("cover_view_registered"):
        hass.http.register_view(PS4FTPDownloadView())
        hass.http.register_view(PS4FTPUploadView())
        hass.http.register_view(PS4GameCoverView())
        g["cover_view_registered"] = True

    _SEND_PAYLOAD_SCHEMA = vol.Schema(
        {
            vol.Required("payload_file"): str,
            vol.Optional("ps4_host"): str,
            vol.Optional("binloader_port"): vol.All(
                vol.Coerce(int), vol.Range(min=1024, max=65535)
            ),
            vol.Optional("timeout", default=30): vol.All(
                vol.Coerce(float), vol.Range(min=1)
            ),
        }
    )

    async def handle_send_payload(call: ServiceCall) -> None:
        p_file   = call.data["payload_file"]
        t_host   = call.data.get("ps4_host") or host
        t_port   = int(call.data.get("binloader_port") or binloader_port)
        filepath = (
            p_file if os.path.isabs(p_file) else os.path.join(PAYLOAD_DIR, p_file)
        )
        await _send_bin_tcp(t_host, t_port, filepath, call.data.get("timeout", 30))

    if not hass.services.has_service(DOMAIN, _SVC_SEND_PAYLOAD):
        hass.services.async_register(
            DOMAIN, _SVC_SEND_PAYLOAD, handle_send_payload,
            schema=_SEND_PAYLOAD_SCHEMA,
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


# ── HTTP views ─────────────────────────────────────────────────────────────────

class PS4FTPDownloadView(HomeAssistantView):
    url          = "/api/ps4_goldhen/ftp/download"
    name         = "api:ps4_goldhen:ftp_download"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        import ftplib
        entry_id = request.query.get("entry_id")
        path     = request.query.get("path")
        if not entry_id or not path:
            return web.Response(text="Missing entry_id or path", status=400)
        data = _ensure_domain_root(request.app["hass"]).get(entry_id)
        if not data:
            return web.Response(text="Entry not found", status=404)
        def _get_file():
            buf = io.BytesIO()
            with ftplib.FTP() as ftp:
                ftp.connect(data["host"], int(data["ftp_port"]), timeout=15)
                ftp.login()
                ftp.retrbinary(f"RETR {path}", buf.write)
            return buf.getvalue()
        try:
            content = await request.app["hass"].async_add_executor_job(_get_file)
            return web.Response(
                body=content,
                content_type="application/octet-stream",
                headers={
                    "Content-Disposition":
                        f'attachment; filename="{os.path.basename(path)}"'
                },
            )
        except Exception as err:
            return web.Response(text=f"FTP Error: {err}", status=500)


class PS4FTPUploadView(HomeAssistantView):
    url          = "/api/ps4_goldhen/ftp/upload"
    name         = "api:ps4_goldhen:ftp_upload"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        import ftplib
        reader   = await request.multipart()
        entry_id = path = file_field = None
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
        def _upload(content):
            with ftplib.FTP() as ftp:
                ftp.connect(data["host"], int(data["ftp_port"]), timeout=15)
                ftp.login()
                ftp.storbinary(f"STOR {full_dest}", io.BytesIO(content))
        try:
            await request.app["hass"].async_add_executor_job(
                _upload, await file_field.read(decode=True)
            )
            return web.json_response({"success": True, "path": full_dest})
        except Exception as err:
            return web.Response(text=f"FTP Upload Error: {err}", status=500)


class PS4GameCoverView(HomeAssistantView):
    url          = "/api/ps4_goldhen/cover/{entry_id}/{title_id}"
    name         = "api:ps4_goldhen:cover"
    requires_auth = False

    async def get(
        self, request: web.Request, entry_id: str, title_id: str
    ) -> web.Response:
        import ftplib
        data = _ensure_domain_root(request.app["hass"]).get(entry_id)
        if not data:
            return web.Response(text="Entry not found", status=404)
        tid       = title_id.strip().upper()
        game_info = data.get("game_map", {}).get(tid, {})
        cdn_url   = game_info.get("cdn_cover")
        if cdn_url and cdn_url.startswith("http"):
            raise web.HTTPFound(cdn_url)
        cover_path = game_info.get("cover") or f"/user/appmeta/{tid}/icon0.png"
        def _fetch_cover():
            buf = io.BytesIO()
            with ftplib.FTP() as ftp:
                ftp.connect(data["host"], int(data["ftp_port"]), timeout=15)
                ftp.login()
                ftp.retrbinary(f"RETR {cover_path}", buf.write)
            return buf.getvalue()
        try:
            img_bytes = await request.app["hass"].async_add_executor_job(_fetch_cover)
            return web.Response(
                body=img_bytes,
                content_type="image/png",
                headers={"Cache-Control": "max-age=86400"},
            )
        except Exception as err:
            _LOGGER.debug("Cover FTP fetch failed for %s: %s", tid, err)
            return web.Response(text=f"Cover not found: {err}", status=404)


# ── Teardown ───────────────────────────────────────────────────────────────────

async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    entry_data = _ensure_domain_root(hass).get(entry.entry_id)
    if entry_data:
        for task_key in ("klog_task", "db_task"):
            t = entry_data.get(task_key)
            if t and not t.done():
                t.cancel()
                with contextlib.suppress(Exception):
                    await asyncio.gather(t, return_exceptions=True)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        _ensure_domain_root(hass).pop(entry.entry_id, None)
    return unload_ok

