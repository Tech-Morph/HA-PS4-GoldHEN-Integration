"""The PS4 GoldHEN Integration."""
from __future__ import annotations
import asyncio
import io
import logging
import os
from datetime import timedelta
from typing import Any
from aiohttp import web
import voluptuous as vol
from homeassistant.components import frontend, panel_custom
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
    DEFAULT_BINLOADER_PORT,
    DEFAULT_FTP_PORT,
    DEFAULT_RPI_PORT,
    PAYLOAD_DIR,
    TCP_PROBE_TIMEOUT,
    _SVC_SEND_PAYLOAD,
    _SVC_INSTALL_PKG,
)

_LOGGER = logging.getLogger(__name__)

_FTP_POLL_INTERVAL = timedelta(seconds=30)
PKG_STORAGE_DIR = "ps4_pkgs"

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

_INSTALL_PKG_SCHEMA = vol.Schema(
    {
        vol.Required("url"): str,
        vol.Optional("ps4_host"): str,
        vol.Optional("rpi_port"): vol.All(
            vol.Coerce(int), vol.Range(min=1024, max=65535)
        ),
    }
)

async def _send_bin_tcp(
    host: str, port: int, filepath: str, timeout: float = 30.0
) -> None:
    if not os.path.isfile(filepath):
        raise HomeAssistantError(f"Payload file not found: {filepath}")
    file_size = os.path.getsize(filepath)
    _LOGGER.info("Sending payload %s to %s:%d", os.path.basename(filepath), host, port)
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
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
        except Exception:
            pass

async def _remote_install_pkg(host: str, port: int, pkg_url: str) -> None:
    import aiohttp
    url = f"http://{host}:{port}/api/install"
    payload = {"type": "direct", "packages": [pkg_url]}
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=payload, timeout=10) as response:
                if response.status != 200:
                    raise HomeAssistantError(f"RPI returned status {response.status}")
        except Exception as err:
            raise HomeAssistantError(f"Failed to connect to RPI at {host}:{port}: {err}") from err

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    host = entry.data[CONF_PS4_HOST]
    binloader_port = entry.data.get(CONF_BINLOADER_PORT, DEFAULT_BINLOADER_PORT)
    ftp_port = entry.data.get(CONF_FTP_PORT, DEFAULT_FTP_PORT)
    rpi_port = entry.data.get(CONF_RPI_PORT, DEFAULT_RPI_PORT)

    pkg_dir = hass.config.path(f"custom_components/{DOMAIN}/{PKG_STORAGE_DIR}")
    if not os.path.exists(pkg_dir):
        await hass.async_add_executor_job(os.makedirs, pkg_dir)

    if not os.path.exists(hass.config.path(PAYLOAD_DIR)):
        await hass.async_add_executor_job(os.makedirs, hass.config.path(PAYLOAD_DIR))

    async def _poll_ftp() -> dict[str, Any]:
        try:
            _r, writer = await asyncio.wait_for(
                asyncio.open_connection(host, ftp_port), timeout=TCP_PROBE_TIMEOUT
            )
            writer.close()
            await writer.wait_closed()
            return {"ftp_reachable": True}
        except Exception:
            return {"ftp_reachable": False}

    coordinator = DataUpdateCoordinator(
        hass, _LOGGER, name=f"{DOMAIN}_{host}", 
        update_method=_poll_ftp, update_interval=_FTP_POLL_INTERVAL,
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "host": host,
        "binloader_port": binloader_port,
        "rpi_port": rpi_port,
        "ftp_port": ftp_port,
    }

    async def handle_send_payload(call: ServiceCall) -> None:
        p_file = call.data["payload_file"]
        t_host = call.data.get("ps4_host") or host
        t_port = int(call.data.get("binloader_port") or binloader_port)
        timeout = float(call.data.get("timeout", 30))
        filepath = p_file if os.path.isabs(p_file) else hass.config.path(os.path.join(PAYLOAD_DIR, p_file))
        await _send_bin_tcp(t_host, t_port, filepath, timeout)

    async def handle_install_pkg(call: ServiceCall) -> None:
        p_url = call.data["url"]
        t_host = call.data.get("ps4_host") or host
        t_port = int(call.data.get("rpi_port") or rpi_port)
        await _remote_install_pkg(t_host, t_port, p_url)

    hass.services.async_register(DOMAIN, _SVC_SEND_PAYLOAD, handle_send_payload, schema=_SEND_PAYLOAD_SCHEMA)
    hass.services.async_register(DOMAIN, _SVC_INSTALL_PKG, handle_install_pkg, schema=_INSTALL_PKG_SCHEMA)

    from .websocket import async_setup as async_setup_websocket
    async_setup_websocket(hass)

    hass.http.register_view(PS4FTPUploadView())
    hass.http.register_view(PS4PKGUploadView())
    hass.http.register_view(PS4PKGServeView())
    hass.http.register_view(PS4PayloadListView())

    js_url_path = "/api/ps4_goldhen/frontend/ps4-goldhen-panel.js"
    await hass.http.async_register_static_paths([
        StaticPathConfig(js_url_path, hass.config.path(f"custom_components/{DOMAIN}/frontend/ps4-goldhen-panel.js"), False)
    ])

    # Dashboard Panel
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path="ps4_dashboard",
        webcomponent_name="ps4-goldhen-panel",
        module_url=js_url_path,
        sidebar_title="PS4 Dashboard",
        sidebar_icon="mdi:view-dashboard",
        config={"entry_id": entry.entry_id, "mode": "dashboard"},
        require_admin=False,
    )

    # FTP Browser Panel (Original)
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path="ps4_ftp",
        webcomponent_name="ps4-goldhen-panel",
        module_url=js_url_path,
        sidebar_title="PS4 FTP",
        sidebar_icon="mdi:folder-network",
        config={"entry_id": entry.entry_id, "mode": "ftp"},
        require_admin=False,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

class PS4FTPUploadView(HomeAssistantView):
    url = "/api/ps4_goldhen/ftp/upload"
    name = "api:ps4_goldhen:ftp:upload"
    requires_auth = True
    async def post(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        reader = await request.multipart()
        entry_id = path = file_field = None
        while True:
            part = await reader.next()
            if part is None: break
            if part.name == "entry_id": entry_id = (await part.read(decode=True)).decode()
            elif part.name == "path": path = (await part.read(decode=True)).decode()
            elif part.name == "file": file_field = part; break
        if not all([entry_id, path, file_field]): return web.Response(status=400)
        data = hass.data[DOMAIN].get(entry_id)
        if not data: return web.Response(status=404)
        def _upload(content):
            import ftplib
            with ftplib.FTP() as ftp:
                ftp.connect(data["host"], data["ftp_port"], timeout=15)
                ftp.login()
                ftp.storbinary(f"STOR {path.rstrip('/')}/{file_field.filename}", io.BytesIO(content))
        await hass.async_add_executor_job(_upload, await file_field.read(decode=True))
        return web.json_response({"success": True})

class PS4PKGUploadView(HomeAssistantView):
    url = "/api/ps4_goldhen/pkg/upload"
    name = "api:ps4_goldhen:pkg:upload"
    requires_auth = True
    async def post(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        reader = await request.multipart()
        entry_id = file_field = None
        while True:
            part = await reader.next()
            if part is None: break
            if part.name == "entry_id": entry_id = (await part.read(decode=True)).decode()
            elif part.name == "file": file_field = part; break
        if not all([entry_id, file_field]): return web.Response(status=400)
        pkg_path = hass.config.path(f"custom_components/{DOMAIN}/{PKG_STORAGE_DIR}/{file_field.filename}")
        with open(pkg_path, "wb") as f:
            while True:
                chunk = await file_field.read_chunk()
                if not chunk: break
                f.write(chunk)
        ext_url = hass.config.external_url or hass.config.internal_url
        install_url = f"{ext_url.rstrip('/')}/api/ps4_goldhen/pkg/serve/{file_field.filename}"
        data = hass.data[DOMAIN][entry_id]
        await _remote_install_pkg(data["host"], data["rpi_port"], install_url)
        return web.json_response({"success": True})

class PS4PKGServeView(HomeAssistantView):
    url = "/api/ps4_goldhen/pkg/serve/{filename}"
    name = "api:ps4_goldhen:pkg:serve"
    requires_auth = False
    async def get(self, request: web.Request, filename: str) -> web.FileResponse:
        path = request.app["hass"].config.path(f"custom_components/{DOMAIN}/{PKG_STORAGE_DIR}/{filename}")
        return web.FileResponse(path)

class PS4PayloadListView(HomeAssistantView):
    url = "/api/ps4_goldhen/payloads"
    name = "api:ps4_goldhen:payloads"
    requires_auth = True
    async def get(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        payload_path = hass.config.path(PAYLOAD_DIR)
        if not os.path.exists(payload_path): return web.json_response([])
        files = [f for f in os.listdir(payload_path) if f.endswith((".bin", ".elf"))]
        return web.json_response(files)

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        frontend.async_remove_panel(hass, "ps4_dashboard")
        frontend.async_remove_panel(hass, "ps4_ftp")
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
