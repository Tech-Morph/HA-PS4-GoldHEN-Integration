"""The PS4 GoldHEN Integration."""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import timedelta

from aiohttp import web
import voluptuous as vol

from homeassistant.components import frontend
from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
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
        vol.Required("payload"): str,
        vol.Optional("host"): str,
        vol.Optional("port"): vol.Coerce(int),
    }
)

_INSTALL_PKG_SCHEMA = vol.Schema(
    {
        vol.Required("url"): str,
        vol.Optional("method"): vol.In(["rpi", "goldhen"]),
        vol.Optional("host"): str,
        vol.Optional("port"): vol.Coerce(int),
    }
)

async def _send_payload(
    hass: HomeAssistant, host: str, port: int, payload_path: str
) -> None:
    """Send a binary payload to PS4 BinLoader via raw TCP."""
    def _check_file():
        return os.path.exists(payload_path)

    if not await hass.async_add_executor_job(_check_file):
        raise HomeAssistantError(f"Payload file not found: {payload_path}")

    _LOGGER.info("Sending payload %s to %s:%d", payload_path, host, port)
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=TCP_PROBE_TIMEOUT
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
    """Upload a PKG file from HA payload dir to PS4 /data/pkg/ via GoldHEN FTP.
    Returns the remote path on the PS4, e.g. '/data/pkg/game.pkg'.
    """
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
                pass  # directory already exists
            ftp.cwd("/data/pkg")
            with open(source_path, "rb") as fh:
                ftp.storbinary(f"STOR {filename}", fh)

    try:
        await hass.async_add_executor_job(_do_upload)
    except FileNotFoundError:
        raise HomeAssistantError(
            f"PKG '{filename}' not found in {PAYLOAD_DIR}. "
            "Upload it to HA first via the panel."
        )
    except Exception as err:
        raise HomeAssistantError(f"FTP upload failed: {err}") from err

    _LOGGER.info("FTP upload complete: /data/pkg/%s", filename)
    return f"/data/pkg/{filename}"

async def _goldhen_install_pkg(
    hass: HomeAssistant, host: str, rpi_port: int, pkg_path_on_ps4: str
) -> None:
    """Trigger GoldHEN's built-in package installer."""
    api_url = f"http://{host}:{rpi_port}/api/install"
    pkg_ftp_url = f"ftp://ps4:ps4@{host}:2121{pkg_path_on_ps4}"
    body = {"type": "direct", "packages": [pkg_ftp_url]}

    _LOGGER.info("GoldHEN install: POST %s pkg=%s", api_url, pkg_ftp_url)
    try:
        session = async_get_clientsession(hass)
        async with session.post(api_url, json=body, timeout=20) as resp:
            text = await resp.text()
            if resp.status not in (200, 204):
                raise HomeAssistantError(
                    f"GoldHEN install error (HTTP {resp.status}): {text}"
                )
            _LOGGER.info("GoldHEN install triggered: %s", text)
    except HomeAssistantError:
        raise
    except Exception as err:
        raise HomeAssistantError(
            f"Could not reach GoldHEN installer at {api_url}: {err}"
        ) from err

async def _remote_install_pkg(
    hass: HomeAssistant, host: str, port: int, url: str
) -> None:
    """Trigger install via Remote Package Installer (RPI) homebrew app."""
    api_url = f"http://{host}:{port}/api/install"
    body = {"type": "direct", "packages": [url]}
    try:
        session = async_get_clientsession(hass)
        async with session.post(api_url, json=body, timeout=20) as resp:
            text = await resp.text()
            if resp.status not in (200, 204):
                raise HomeAssistantError(
                    f"RPI installer error (HTTP {resp.status}): {text}"
                )
    except HomeAssistantError:
        raise
    except Exception as err:
        raise HomeAssistantError(
            f"Failed to reach RPI at {api_url}: {err}"
        ) from err

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
        return {"online": True}

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
        payload = call.data["payload"]
        p_host = call.data.get("host", host)
        p_port = call.data.get("port", binloader_port)
        await _send_payload(
            hass, p_host, p_port, hass.config.path(PAYLOAD_DIR, payload)
        )

    async def handle_install_pkg(call: ServiceCall):
        url = call.data["url"]
        method = call.data.get("method", "rpi")
        p_host = call.data.get("host", host)

        if method == "goldhen":
            filename = url.split("/")[-1]
            pkg_path = await _ftp_upload_to_ps4(hass, p_host, ftp_port, filename)
            await _goldhen_install_pkg(hass, p_host, rpi_port, pkg_path)
        else:
            p_port = call.data.get("port", rpi_port)
            await _remote_install_pkg(hass, p_host, p_port, url)

    hass.services.async_register(
        DOMAIN, _SVC_SEND_PAYLOAD, handle_send_payload, schema=_SEND_PAYLOAD_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, _SVC_INSTALL_PKG, handle_install_pkg, schema=_INSTALL_PKG_SCHEMA
    )

    hass.http.register_view(PS4PayloadView())
    hass.http.register_view(PS4UploadView())

    frontend_path = hass.config.path("custom_components/ps4_goldhen/frontend")
    hass.http.register_static_path(
        "/ps4_goldhen_static/ps4-goldhen-panel.js",
        os.path.join(frontend_path, "ps4-goldhen-panel.js"),
    )

    await hass.components.frontend.async_register_built_in_panel(
        component_name="panel_custom",
        sidebar_title="PS4 GoldHEN",
        sidebar_icon="mdi:playstation",
        url_path="ps4-goldhen",
        config={
            "webcomponent_name": "ps4-goldhen-panel",
            "module_url": "/ps4_goldhen_static/ps4-goldhen-panel.js",
            "entity_id": entry.entry_id,
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
