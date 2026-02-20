from __future__ import annotations

import asyncio
import logging
import os
from datetime import timedelta
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    DOMAIN,
    PLATFORMS,
    CONF_PS4_HOST,
    CONF_BINLOADER_PORT,
    CONF_FTP_PORT,
    DEFAULT_BINLOADER_PORT,
    PAYLOAD_DIR,
    TCP_PROBE_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)

# How often we poll FTP reachability for the sensor
_FTP_POLL_INTERVAL = timedelta(seconds=30)

# Service name
_SVC_SEND_PAYLOAD = "send_payload"

# Service schema
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


async def _send_bin_tcp(
    host: str,
    port: int,
    filepath: str,
    timeout: float = 30.0,
) -> None:
    """Stream a local .bin file to host:port over a raw TCP connection."""
    if not os.path.isfile(filepath):
        raise HomeAssistantError(f"Payload file not found: {filepath}")

    file_size = os.path.getsize(filepath)
    _LOGGER.info("Sending payload %s (%d bytes) to %s:%d", os.path.basename(filepath), file_size, host, port)

    try:
        _reader, writer = await asyncio.wait_for(
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
        except Exception:  # noqa: BLE001
            pass
    _LOGGER.info("Payload sent successfully.")


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up PS4 GoldHEN integration from a config entry."""
    host = entry.data[CONF_PS4_HOST]
    binloader_port = entry.data.get(CONF_BINLOADER_PORT, DEFAULT_BINLOADER_PORT)
    ftp_port = entry.data.get(CONF_FTP_PORT, 2121)

    async def _poll_ftp() -> dict[str, Any]:
        try:
            _reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, ftp_port), timeout=TCP_PROBE_TIMEOUT,
            )
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

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "host": host,
        "binloader_port": binloader_port,
        "ftp_port": ftp_port,
    }

    # ── Service ───────────────────────────────────────────────────────────────────

    async def handle_send_payload(call: ServiceCall) -> None:
        p_file = call.data["payload_file"]
        t_host = call.data.get("ps4_host") or host
        t_port = int(call.data.get("binloader_port") or binloader_port)
        timeout = float(call.data.get("timeout", 30))

        filepath = p_file if os.path.isabs(p_file) else os.path.join(PAYLOAD_DIR, p_file)
        await _send_bin_tcp(t_host, t_port, filepath, timeout)

    if not hass.services.has_service(DOMAIN, _SVC_SEND_PAYLOAD):
        hass.services.async_register(DOMAIN, _SVC_SEND_PAYLOAD, handle_send_payload, schema=_SEND_PAYLOAD_SCHEMA)

    # ── WebSocket & Panel ──────────────────────────────────────────────────────────

    from .websocket import async_setup as async_setup_websocket
    async_setup_websocket(hass)

    hass.components.frontend.async_register_built_in_panel(
        component_name="custom",
        sidebar_title="PS4 FTP",
        sidebar_icon="mdi:folder-network",
        url_path="ps4_ftp",
        config={
            "entry_id": entry.entry_id,
            "module_url": f"/api/ps4_goldhen/frontend/ps4-goldhen-panel.js",
            "name": "ps4-goldhen-panel"
        },
        require_admin=False,
    )
    
    # We also need to serve the JS file
    hass.http.register_static_path(
        "/api/ps4_goldhen/frontend/ps4-goldhen-panel.js",
        hass.config.path(f"custom_components/{DOMAIN}/frontend/ps4-goldhen-panel.js"),
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when the user saves new options."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry and clean up."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, _SVC_SEND_PAYLOAD)
            hass.data.pop(DOMAIN, None)
    return unload_ok
