"""The PS4 GoldHEN Integration."""
from __future__ import annotations
import asyncio
import logging
import os
from datetime import timedelta
from aiohttp import web
import voluptuous as vol
from homeassistant.components import frontend, websocket_api
from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
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

_SEND_PAYLOAD_SCHEMA = vol.Schema(
    {
        vol.Required("payload_file"): str,
        vol.Optional("ps4_host"): str,
        vol.Optional("binloader_port"): vol.Coerce(int),
        vol.Optional("timeout"): vol.Coerce(int),
    }
)

_INSTALL_PKG_SCHEMA = vol.Schema(
    {
        vol.Required("url"): str,
        vol.Optional("method"): vol.In(["rpi", "goldhen"]),
        vol.Optional("ps4_host"): str,
        vol.Optional("rpi_port"): vol.Coerce(int),
    }
)

class PS4PayloadView(HomeAssistantView):
    """List .bin and .pkg files in HA's payload directory."""
    url = "/api/ps4_goldhen/payloads"
    name = "api:ps4_goldhen:payloads"
    requires_auth = True
    async def get(self, request):
        hass = request.app["hass"]
        path = hass.config.path(PAYLOAD_DIR)
        
        def _get_files():
            if not os.path.exists(path):
                return []
            return [f for f in os.listdir(path) if f.endswith(".bin") or f.endswith(".pkg")]
        
        files = await hass.async_add_executor_job(_get_files)
        return web.json_response(files)

class PS4UploadView(HomeAssistantView):
    """Accept multipart upload, save to HA payload directory."""
    url = "/api/ps4_goldhen/upload"
    name = "api:ps4_goldhen:upload"
    requires_auth = True
    async def post(self, request):
        hass = request.app["hass"]
        data = await request.post()
        file = data.get("file")
        
        if not file:
            return web.json_response({"error": "no file provided"}, status=400)
        
        filename = file.filename
        dest = hass.config.path(PAYLOAD_DIR, filename)
        
        def _save_file():
            with open(dest, "wb") as fh:
                fh.write(file.file.read())
        
        await hass.async_add_executor_job(_save_file)
        return web.json_response({"status": "ok", "filename": filename})

@websocket_api.require_admin
@websocket_api.async_response
@websocket_api.websocket_command(
    {
        vol.Required("type"): "ps4_goldhen/ftp_list_dir",
        vol.Required("entry_id"): str,
        vol.Optional("path", default="/"): str,
    }
)
async def websocket_ftp_list_dir(hass, connection, msg):
    """Handle FTP directory listing via websocket."""
    entry_id = msg["entry_id"]
    path = msg["path"]
    
    if entry_id not in hass.data[DOMAIN]:
        connection.send_error(msg["id"], "entry_not_found", "Config entry not found")
        return

    data = hass.data[DOMAIN][entry_id]
    host = data["host"]
    port = data["ftp_port"]

    def _list_dir():
        from ftplib import FTP
        entries = []
        try:
            with FTP() as ftp:
                ftp.connect(host, port, timeout=10)
                ftp.login("ps4", "ps4")
                ftp.cwd(path)
                lines = []
                ftp.retrlines('LIST', lines.append)
                
                for line in lines:
                    parts = line.split(None, 8)
                    if len(parts) < 9: continue
                    is_dir = parts[0].startswith('d')
                    size = parts[4] if not is_dir else ""
                    name = parts[8]
                    if name in ('.', '..'): continue
                    entries.append({
                        "name": name,
                        "is_dir": is_dir,
                        "size": size
                    })
        except Exception as e:
            _LOGGER.error("FTP list error: %s", e)
            raise e
        return entries

    try:
        entries = await hass.async_add_executor_job(_list_dir)
        connection.send_result(msg["id"], {"entries": entries})
    except Exception as err:
        connection.send_error(msg["id"], "ftp_error", str(err))

async def _send_payload(
    hass: HomeAssistant, host: str, port: int, payload_path: str, timeout: int = 10
) -> None:
    """Send a binary payload to PS4 BinLoader via raw TCP."""
    def _check_file():
        return os.path.exists(payload_path)
    if not await hass.async_add_executor_job(_check_file):
        raise HomeAssistantError(f"Payload file not found: {payload_path}")
    
    _LOGGER.info("Sending payload %s to %s:%d (timeout=%d)", payload_path, host, port, timeout)
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        try:
            def _read_payload():
                with open(payload_path, "rb") as fh:
                    return fh.read()
            
            data = await hass.async_add_executor_job(_read_payload)
            writer.write(data)
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
    except Exception as err:
        raise HomeAssistantError(f"Error sending payload: {err}") from err

async def _ftp_upload_to_ps4(
    hass: HomeAssistant, host: str, port: int, filename: str
) -> str:
    """Upload a PKG file from HA payload dir to PS4 /data/pkg/ via GoldHEN FTP."""
    source_path = hass.config.path(PAYLOAD_DIR, filename)
    def _do_upload() -> None:
        if not os.path.exists(source_path):
            raise FileNotFoundError(source_path)
        
        from ftplib import FTP, error_perm
        with FTP() as ftp:
            ftp.connect(host, port, timeout=30)
            ftp.login("ps4", "ps4")
            try:
                ftp.mkd("/data/pkg")
            except error_perm:
                pass
            ftp.cwd("/data/pkg")
            with open(source_path, "rb") as fh:
                ftp.storbinary(f"STOR {filename}", fh)
    
    try:
        await hass.async_add_executor_job(_do_upload)
    except FileNotFoundError:
        raise HomeAssistantError(f"PKG '{filename}' not found.")
    except Exception as err:
        raise HomeAssistantError(f"FTP upload failed: {err}") from err
    return f"/data/pkg/{filename}"

async def _goldhen_install_pkg(
    hass: HomeAssistant, host: str, rpi_port: int, pkg_path_on_ps4: str
) -> None:
    """Trigger GoldHEN's built-in package installer."""
    api_url = f"http://{host}:{rpi_port}/api/install"
    pkg_ftp_url = f"ftp://ps4:ps4@{host}:2121{pkg_path_on_ps4}"
    body = {"type": "direct", "packages": [pkg_ftp_url]}
    try:
        session = async_get_clientsession(hass)
        async with session.post(api_url, json=body, timeout=20) as resp:
            if resp.status not in (200, 204):
                text = await resp.text()
                raise HomeAssistantError(f"GoldHEN install error ({resp.status}): {text}")
    except Exception as err:
        raise HomeAssistantError(f"Could not reach GoldHEN installer: {err}") from err

async def _remote_install_pkg(
    hass: HomeAssistant, host: str, port: int, url: str
) -> None:
    """Trigger install via Remote Package Installer (RPI) homebrew app."""
    api_url = f"http://{host}:{port}/api/install"
    body = {"type": "direct", "packages": [url]}
    try:
        session = async_get_clientsession(hass)
        async with session.post(api_url, json=body, timeout=20) as resp:
            if resp.status not in (200, 204):
                text = await resp.text()
                raise HomeAssistantError(f"RPI installer error ({resp.status}): {text}")
    except Exception as err:
        raise HomeAssistantError(f"Failed to reach RPI: {err}") from err

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up PS4 GoldHEN from a config entry."""
    host = entry.data[CONF_PS4_HOST]
    binloader_port = entry.data.get(CONF_BINLOADER_PORT, DEFAULT_BINLOADER_PORT)
    ftp_port = entry.data.get(CONF_FTP_PORT, DEFAULT_FTP_PORT)
    rpi_port = entry.data.get(CONF_RPI_PORT, DEFAULT_RPI_PORT)
    payload_dir = hass.config.path(PAYLOAD_DIR)
    
    def _create_dir():
        if not os.path.exists(payload_dir):
            os.makedirs(payload_dir, exist_ok=True)
    await hass.async_add_executor_job(_create_dir)

    async def _async_update_data():
        """Check if PS4 FTP is online."""
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, ftp_port), timeout=TCP_PROBE_TIMEOUT
            )
            writer.close()
            await writer.wait_closed()
            return {"ftp_reachable": True}
        except Exception:
            return {"ftp_reachable": False}

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=DOMAIN,
        update_method=_async_update_data,
        update_interval=_FTP_POLL_INTERVAL,
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "host": host,
        "binloader_port": binloader_port,
        "ftp_port": ftp_port,
        "rpi_port": rpi_port,
    }

    async def handle_send_payload(call: ServiceCall):
        payload_file = call.data["payload_file"]
        p_host = call.data.get("ps4_host", host)
        p_port = call.data.get("binloader_port", binloader_port)
        timeout = call.data.get("timeout", 10)
        await _send_payload(
            hass, p_host, p_port, hass.config.path(PAYLOAD_DIR, payload_file), timeout
        )

    async def handle_install_pkg(call: ServiceCall):
        url = call.data["url"]
        method = call.data.get("method", "rpi")
        p_host = call.data.get("ps4_host", host)
        if method == "goldhen":
            filename = url.split("/")[-1]
            pkg_path = await _ftp_upload_to_ps4(hass, p_host, ftp_port, filename)
            await _goldhen_install_pkg(hass, p_host, rpi_port, pkg_path)
        else:
            p_port = call.data.get("rpi_port", rpi_port)
            await _remote_install_pkg(hass, p_host, p_port, url)

    hass.services.async_register(
        DOMAIN, _SVC_SEND_PAYLOAD, handle_send_payload, schema=_SEND_PAYLOAD_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, _SVC_INSTALL_PKG, handle_install_pkg, schema=_INSTALL_PKG_SCHEMA
    )

    hass.http.register_view(PS4PayloadView())
    hass.http.register_view(PS4UploadView())
    websocket_api.async_register_command(hass, websocket_ftp_list_dir)

    frontend_path = hass.config.path("custom_components/ps4_goldhen/frontend")
    hass.http.register_static_path("/ps4_goldhen_static", frontend_path, cache_headers=False)

    frontend.async_register_panel(
        hass,
        "ps4-goldhen",
        "ps4-goldhen-panel",
        sidebar_title="PS4 GoldHEN",
        sidebar_icon="mdi:playstation",
        config={
            "module_url": "/ps4_goldhen_static/ps4-goldhen-panel.js",
            "entry_id": entry.entry_id,
        },
        require_admin=True,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        frontend.async_remove_panel(hass, "ps4-goldhen")
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
