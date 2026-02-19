from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    PLATFORMS,
    CONF_HOST,
    CONF_BINLOADER_PORT,
    CONF_FTP_PORT,
)

_LOGGER = logging.getLogger(__name__)

PAYLOAD_DIR = Path("/config/ps4_payloads")

SERVICE_SEND_PAYLOAD = "send_payload"
SERVICE_SCHEMA_SEND_PAYLOAD = vol.Schema(
    {
        vol.Required("payload_file"): str,  # relative to /config/ps4_payloads
        vol.Optional("host"): str,
        vol.Optional("port"): int,
        vol.Optional("timeout"): vol.Coerce(float),
    }
)

DEFAULT_TIMEOUT = 10.0


async def _tcp_probe(host: str, port: int, timeout: float) -> bool:
    try:
        conn = asyncio.open_connection(host, port)
        reader, writer = await asyncio.wait_for(conn, timeout=timeout)
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        return False


async def _send_payload(host: str, port: int, payload: bytes, timeout: float) -> None:
    reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
    try:
        writer.write(payload)
        await asyncio.wait_for(writer.drain(), timeout=timeout)
    finally:
        writer.close()
        await writer.wait_closed()


def _safe_payload_path(payload_file: str) -> Path:
    # Prevent path traversal; force files to remain under /config/ps4_payloads
    p = (PAYLOAD_DIR / payload_file).resolve()
    base = PAYLOAD_DIR.resolve()
    if base not in p.parents and p != base:
        raise ValueError("payload_file must be within /config/ps4_payloads/")
    return p


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    host = entry.data[CONF_HOST]
    binloader_port = entry.data[CONF_BINLOADER_PORT]
    ftp_port = entry.data[CONF_FTP_PORT]

    async def _async_update() -> dict[str, Any]:
        timeout = DEFAULT_TIMEOUT
        ok_bin = await _tcp_probe(host, binloader_port, timeout)
        ok_ftp = await _tcp_probe(host, ftp_port, timeout)
        return {
            "host": host,
            "binloader_port": binloader_port,
            "ftp_port": ftp_port,
            "binloader_ok": ok_bin,
            "ftp_ok": ok_ftp,
        }

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"{DOMAIN}_{host}",
        update_method=_async_update,
        update_interval=timedelta(seconds=15),
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
    }

    async def handle_send_payload(call: ServiceCall) -> None:
        data = call.data
        payload_file = data["payload_file"]
        override_host = data.get("host") or host
        override_port = data.get("port") or binloader_port
        timeout = float(data.get("timeout") or DEFAULT_TIMEOUT)

        payload_path = _safe_payload_path(payload_file)

        if not payload_path.exists():
            raise FileNotFoundError(f"Payload file not found: {payload_path}")

        payload_bytes = await hass.async_add_executor_job(payload_path.read_bytes)

        _LOGGER.info("Sending payload '%s' to %s:%s (%d bytes)", payload_file, override_host, override_port, len(payload_bytes))
        await _send_payload(override_host, int(override_port), payload_bytes, timeout)

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_PAYLOAD,
        handle_send_payload,
        schema=SERVICE_SCHEMA_SEND_PAYLOAD,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, SERVICE_SEND_PAYLOAD)
            hass.data.pop(DOMAIN, None)
    return unload_ok
