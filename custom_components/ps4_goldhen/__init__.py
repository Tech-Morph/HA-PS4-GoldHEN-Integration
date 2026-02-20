from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    DOMAIN,
    PLATFORMS,
    CONF_ADDON_URL,
    CONF_PS4_HOST,
    CONF_BINLOADER_PORT,
    DEFAULT_BINLOADER_PORT,
    ENDPOINT_STATUS,
    ENDPOINT_WAKE,
    ENDPOINT_STANDBY,
    ENDPOINT_REBOOT,
    ENDPOINT_PAYLOAD,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 10.0
UPDATE_INTERVAL = timedelta(seconds=30)

SERVICE_WAKE = "wake"
SERVICE_STANDBY = "standby"
SERVICE_REBOOT = "reboot"
SERVICE_SEND_PAYLOAD = "send_payload"

SERVICE_SCHEMA_SEND_PAYLOAD = vol.Schema(
    {
        vol.Required("payload_file"): str,
        vol.Optional("ps4_host"): str,
        vol.Optional("binloader_port"): vol.All(vol.Coerce(int), vol.Range(min=1024, max=65535)),
        vol.Optional("timeout"): vol.Coerce(float),
    }
)


async def _addon_get(addon_url: str, endpoint: str, timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """GET request to add-on API."""
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{addon_url}{endpoint}",
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            resp.raise_for_status()
            return await resp.json()


async def _addon_post(
    addon_url: str,
    endpoint: str,
    payload: dict[str, Any] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """POST request to add-on API."""
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{addon_url}{endpoint}",
            json=payload or {},
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            resp.raise_for_status()
            return await resp.json()


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up PS4 GoldHEN from a config entry."""
    addon_url = entry.data[CONF_ADDON_URL].rstrip("/")
    ps4_host = entry.data[CONF_PS4_HOST]
    binloader_port = entry.data.get(CONF_BINLOADER_PORT, DEFAULT_BINLOADER_PORT)

    async def _async_update() -> dict[str, Any]:
        try:
            data = await _addon_get(addon_url, ENDPOINT_STATUS)
            data["available"] = True
            return data
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("PS4 add-on unreachable: %s", err)
            return {"available": False}

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"{DOMAIN}",
        update_method=_async_update,
        update_interval=UPDATE_INTERVAL,
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "addon_url": addon_url,
        "ps4_host": ps4_host,
        "binloader_port": binloader_port,
    }

    # ---- Service handlers ----
    async def handle_wake(call: ServiceCall) -> None:
        _LOGGER.info("PS4 wake requested")
        result = await _addon_post(addon_url, ENDPOINT_WAKE)
        _LOGGER.info("PS4 wake result: %s", result)

    async def handle_standby(call: ServiceCall) -> None:
        _LOGGER.info("PS4 standby requested")
        result = await _addon_get(addon_url, ENDPOINT_STANDBY)
        _LOGGER.info("PS4 standby result: %s", result)

    async def handle_reboot(call: ServiceCall) -> None:
        _LOGGER.info("PS4 reboot requested")
        result = await _addon_get(addon_url, ENDPOINT_REBOOT)
        _LOGGER.info("PS4 reboot result: %s", result)

    async def handle_send_payload(call: ServiceCall) -> None:
        payload_file = call.data["payload_file"]
        # Allow per-call override of ps4_host and binloader_port
        target_host = call.data.get("ps4_host") or ps4_host
        target_port = int(call.data.get("binloader_port") or binloader_port)
        timeout = float(call.data.get("timeout") or DEFAULT_TIMEOUT)
        _LOGGER.info(
            "Sending payload '%s' to %s:%s via add-on",
            payload_file,
            target_host,
            target_port,
        )
        result = await _addon_post(
            addon_url,
            ENDPOINT_PAYLOAD,
            {
                "payload_file": payload_file,
                "ps4_host": target_host,
                "binloader_port": target_port,
            },
            timeout,
        )
        _LOGGER.info("Payload result: %s", result)

    hass.services.async_register(DOMAIN, SERVICE_WAKE, handle_wake)
    hass.services.async_register(DOMAIN, SERVICE_STANDBY, handle_standby)
    hass.services.async_register(DOMAIN, SERVICE_REBOOT, handle_reboot)
    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_PAYLOAD,
        handle_send_payload,
        schema=SERVICE_SCHEMA_SEND_PAYLOAD,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update — reload the entry so new settings take effect."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            for svc in [SERVICE_WAKE, SERVICE_STANDBY, SERVICE_REBOOT, SERVICE_SEND_PAYLOAD]:
                hass.services.async_remove(DOMAIN, svc)
            hass.data.pop(DOMAIN, None)
    return unload_ok
