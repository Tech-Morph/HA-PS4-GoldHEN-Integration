from __future__ import annotations

import asyncio
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
        timeout = float(call.data.get("timeout") or DEFAULT_TIMEOUT)
        _LOGGER.info("Sending payload '%s' via add-on", payload_file)
        result = await _addon_post(
            addon_url,
            ENDPOINT_PAYLOAD,
            {"payload_file": payload_file},
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
    return True


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
