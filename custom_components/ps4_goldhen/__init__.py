"""The PS4 GoldHEN Integration."""
from __future__ import annotations

import asyncio
import io
import logging
import os
import shutil
from datetime import timedelta
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
    DEFAULT_BINLOADER_PORT,
    DEFAULT_FTP_PORT,
    PAYLOAD_DIR,
    TCP_PROBE_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)

# How often we poll FTP reachability for the sensor
_FTP_POLL_INTERVAL = timedelta(seconds=30)

# Service names
_SVC_SEND_PAYLOAD = "send_payload"

# GLOBAL panel (single sidebar item)
_PANEL_URL_PATH = "ps4_goldhen"
_PANEL_SIDEBAR_TITLE = "PS4 GoldHEN"
_PANEL_SIDEBAR_ICON = "mdi:sony-playstation"
_PANEL_WEBCOMPONENT = "ps4-goldhen-panel"

# Frontend static paths (served by HA)
_JS_STATIC_URL = "/api/ps4_goldhen/frontend/ps4-goldhen-panel.js"
# Bump this when you change the panel JS so browsers pick it up.
_JS_MODULE_URL = "/api/ps4_goldhen/frontend/ps4-goldhen-panel.js?v=0.9.2"
_LOGO_STATIC_URL = "/api/ps4_goldhen/frontend/goldhen_logo.png"
_PAYLOAD_ICONS_STATIC_URL = "/api/ps4_goldhen/frontend/payload_icons"

# Bundled payloads shipped with the integration (optional)
_BUNDLED_PAYLOADS_DIRNAME = "bundled_payloads"


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
    """Copy bundled payloads shipped with the integration into /config/ps4_payloads (no overwrite)."""
    src_dir = Path(__file__).parent / _BUNDLED_PAYLOADS_DIRNAME
    dst_dir = Path(PAYLOAD_DIR)

    if not src_dir.exists() or not src_dir.is_dir():
        return 0

    dst_dir.mkdir(parents=True, exist_ok=True)

    copied = 0
    for p in sorted(src_dir.iterdir()):
        if not p.is_file():
            continue
        if p.suffix.lower() not in (".bin", ".elf"):
            continue

        dst = dst_dir / p.name
        if dst.exists():
            continue

        shutil.copy2(str(p), str(dst))
        copied += 1

    return copied


async def _register_frontend_and_panel_once(hass: HomeAssistant) -> None:
    g = _global(hass)

    if not g["frontend_registered"]:
        # Ensure directories exist (helps avoid static-path issues if folder missing)
        payload_icons_dir = hass.config.path(f"custom_components/{DOMAIN}/frontend/payload_icons")
        os.makedirs(payload_icons_dir, exist_ok=True)

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
                StaticPathConfig(
                    _PAYLOAD_ICONS_STATIC_URL,
                    payload_icons_dir,
                    False,
                ),
            ]
        )
        g["frontend_registered"] = True
        _LOGGER.debug("Registered static frontend paths")

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
        _LOGGER.info("Registered global panel: %s", _PANEL_URL_PATH)


async def _send_bin_tcp(host: str, port: int, filepath: str, timeout: float = 30.0) -> None:
    """Stream a local .bin/.elf file to host:port over a raw TCP connection."""
    if not os.path.isfile(filepath):
        raise HomeAssistantError(f"Payload file not found: {filepath}")

    file_size = os.path.getsize(filepath)
    _LOGGER.info("Sending payload %s (%d bytes) to %s:%d", os.path.basename(filepath), file_size, host, port)

    try:
        _reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
    except (asyncio.TimeoutError, OSError) as err:
        raise HomeAssistantError(f"Cannot reach BinLoader at {host}:{port}: {err}") from err

    try:
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(None, lambda: open(filepath, "rb").read())
        writer.write(data)
        await asyncio.wait_for(writer.drain(), timeout=timeout)
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass

    _LOGGER.info("Payload sent successfully.")


@websocket_api.websocket_command({vol.Required("type"): "ps4_goldhen/list_entries"})
@websocket_api.async_response
async def ws_list_entries(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    entries = hass.config_entries.async_entries(DOMAIN)
    out: list[dict[str, Any]] = []
    for entry in entries:
        host = entry.data.get(CONF_PS4_HOST, "")
        out.append(
            {
                "entry_id": entry.entry_id,
                "title": entry.title,
                "ps4_host": host,
                "ftp_port": entry.data.get(CONF_FTP_PORT, DEFAULT_FTP_PORT),
                "binloader_port": entry.data.get(CONF_BINLOADER_PORT, DEFAULT_BINLOADER_PORT),
            }
        )
    connection.send_result(msg["id"], {"entries": out})


@websocket_api.websocket_command({vol.Required("type"): "ps4_goldhen/list_payloads"})
@websocket_api.async_response
async def ws_list_payloads(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    try:
        os.makedirs(PAYLOAD_DIR, exist_ok=True)
        items: list[str] = []
        for name in sorted(os.listdir(PAYLOAD_DIR)):
            lower = name.lower()
            if lower.endswith(".bin") or lower.endswith(".elf"):
                full = os.path.join(PAYLOAD_DIR, name)
                if os.path.isfile(full):
                    items.append(name)
        connection.send_result(msg["id"], {"payloads": items, "payload_dir": PAYLOAD_DIR})
    except Exception as err:  # noqa: BLE001
        connection.send_error(msg["id"], "list_error", str(err))


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up PS4 GoldHEN integration from a config entry."""
    host = entry.data[CONF_PS4_HOST]
    binloader_port = entry.data.get(CONF_BINLOADER_PORT, DEFAULT_BINLOADER_PORT)
    ftp_port = entry.data.get(CONF_FTP_PORT, DEFAULT_FTP_PORT)

    async def _poll_ftp() -> dict[str, Any]:
        try:
            _reader, writer = await asyncio.wait_for(asyncio.open_connection(host, ftp_port), timeout=TCP_PROBE_TIMEOUT)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass
            return {"ftp_reachable": True}
        except Exception:  # noqa: BLE001
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
    root[entry.entry_id] = {
        "coordinator": coordinator,
        "host": host,
        "binloader_port": binloader_port,
        "ftp_port": ftp_port,
    }

    # Register integration WS commands once globally (FTP + Klog are registered in websocket.py async_setup)
    g = _global(hass)
    if not g["ws_registered"]:
        websocket_api.async_register_command(hass, ws_list_entries)
        websocket_api.async_register_command(hass, ws_list_payloads)

        from .websocket import async_setup as async_setup_websocket

        async_setup_websocket(hass)

        g["ws_registered"] = True

    await _register_frontend_and_panel_once(hass)

    # Install bundled payloads once (optional)
    if not g.get("bundled_payloads_installed", False):
        copied = await hass.async_add_executor_job(_copy_bundled_payloads_to_config)
        if copied:
            _LOGGER.info("Installed %d bundled payload(s) into %s", copied, PAYLOAD_DIR)
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
        timeout = float(call.data.get("timeout", 30))

        os.makedirs(PAYLOAD_DIR, exist_ok=True)
        filepath = p_file if os.path.isabs(p_file) else os.path.join(PAYLOAD_DIR, p_file)
        await _send_bin_tcp(t_host, t_port, filepath, timeout)

    if not hass.services.has_service(DOMAIN, _SVC_SEND_PAYLOAD):
        hass.services.async_register(DOMAIN, _SVC_SEND_PAYLOAD, handle_send_payload, schema=_SEND_PAYLOAD_SCHEMA)

    hass.http.register_view(PS4FTPDownloadView())
    hass.http.register_view(PS4FTPUploadView())

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


class PS4FTPDownloadView(HomeAssistantView):
    """View to download/view files from PS4 via FTP."""

    url = "/api/ps4_goldhen/ftp/download"
    name = "api:ps4_goldhen:ftp_download"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        import ftplib

        hass = request.app["hass"]
        entry_id = request.query.get("entry_id")
        path = request.query.get("path")

        if not entry_id or not path:
            return web.Response(text="Missing entry_id or path", status=400)

        root = _ensure_domain_root(hass)
        data = root.get(entry_id)
        if not data:
            return web.Response(text="Entry not found", status=404)

        host = data["host"]
        port = int(data.get("ftp_port", DEFAULT_FTP_PORT))

        def _get_file() -> bytes:
            buffer = io.BytesIO()
            with ftplib.FTP() as ftp:
                ftp.connect(host, port, timeout=15)
                ftp.login()
                ftp.retrbinary(f"RETR {path}", buffer.write)
                buffer.seek(0)
                return buffer.read()

        try:
            content = await hass.async_add_executor_job(_get_file)
            filename = os.path.basename(path)
            return web.Response(
                body=content,
                content_type="application/octet-stream",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
        except Exception as err:
            return web.Response(text=f"FTP Error: {err}", status=500)


class PS4FTPUploadView(HomeAssistantView):
    """View to upload files to PS4 via FTP."""

    url = "/api/ps4_goldhen/ftp/upload"
    name = "api:ps4_goldhen:ftp_upload"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        import ftplib

        hass = request.app["hass"]

        reader = await request.multipart()
        entry_id = None
        path = None
        file_field = None

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
            return web.Response(text="Missing entry_id, path, or file", status=400)

        root = _ensure_domain_root(hass)
        data = root.get(entry_id)
        if not data:
            return web.Response(text="Entry not found", status=404)

        host = data["host"]
        port = int(data.get("ftp_port", DEFAULT_FTP_PORT))
        filename = file_field.filename
        full_dest_path = (path.rstrip("/") + "/" + filename).replace("//", "/")

        def _upload_file(file_data: bytes) -> None:
            with ftplib.FTP() as ftp:
                ftp.connect(host, port, timeout=15)
                ftp.login()
                ftp.storbinary(f"STOR {full_dest_path}", io.BytesIO(file_data))

        try:
            content = await file_field.read(decode=True)
            await hass.async_add_executor_job(_upload_file, content)
            return web.json_response({"success": True, "path": full_dest_path})
        except Exception as err:
            return web.Response(text=f"FTP Upload Error: {err}", status=500)


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    root = _ensure_domain_root(hass)
    root.pop(entry.entry_id, None)

    remaining = [k for k in root.keys() if k != "_global"]
    if not remaining:
        hass.services.async_remove(DOMAIN, _SVC_SEND_PAYLOAD)

        try:
            frontend.async_remove_panel(hass, _PANEL_URL_PATH)
        except Exception:  # noqa: BLE001
            pass

        hass.data.pop(DOMAIN, None)

    return True
