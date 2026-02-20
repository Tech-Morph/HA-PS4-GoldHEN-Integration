from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import aiohttp

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    CONF_PS4_HOST,
    CONF_GOLDHEN_PORT,
    DEFAULT_GOLDHEN_PORT,
    ENDPOINT_WAKE,
    ENDPOINT_STANDBY,
    ENDPOINT_REBOOT,
)

_LOGGER = logging.getLogger(__name__)

# Timeout for REST calls (seconds)
_REST_TIMEOUT = aiohttp.ClientTimeout(total=10)


@dataclass(frozen=True, kw_only=True)
class Ps4GoldhenButtonDescription(ButtonEntityDescription):
    """Extend ButtonEntityDescription with our REST endpoint."""

    endpoint: str


BUTTON_DESCRIPTIONS: tuple[Ps4GoldhenButtonDescription, ...] = (
    Ps4GoldhenButtonDescription(
        key="wake",
        name="Wake PS4",
        icon="mdi:power",
        endpoint=ENDPOINT_WAKE,
    ),
    Ps4GoldhenButtonDescription(
        key="standby",
        name="Standby PS4",
        icon="mdi:power-sleep",
        endpoint=ENDPOINT_STANDBY,
    ),
    Ps4GoldhenButtonDescription(
        key="reboot",
        name="Reboot PS4",
        icon="mdi:restart",
        endpoint=ENDPOINT_REBOOT,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create button entities for this config entry."""
    entry_data = hass.data[DOMAIN][entry.entry_id]
    coordinator = entry_data["coordinator"]
    host = entry_data["host"]
    goldhen_port = entry_data.get("goldhen_port", DEFAULT_GOLDHEN_PORT)

    async_add_entities(
        [
            Ps4GoldhenButton(coordinator, entry, host, goldhen_port, description)
            for description in BUTTON_DESCRIPTIONS
        ]
    )


class Ps4GoldhenButton(CoordinatorEntity, ButtonEntity):
    """
    A button entity that fires a single REST call to GoldHEN's HTTP API.

    GoldHEN exposes a lightweight HTTP server (default port 12800) with
    simple POST endpoints for power management:
        POST /api/wake      -> wake the PS4 from standby (DDP)
        POST /api/standby   -> put the PS4 in standby/rest mode
        POST /api/reboot    -> reboot the PS4

    The coordinator is attached so availability tracks FTP reachability;
    the button itself does not poll.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator,
        entry: ConfigEntry,
        host: str,
        goldhen_port: int,
        description: Ps4GoldhenButtonDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._host = host
        self._goldhen_port = goldhen_port
        self._attr_unique_id = (
            f"{DOMAIN}_{host}_{description.key}"
        )
        self._attr_name = description.name

    @property
    def available(self) -> bool:
        """Available as long as the coordinator has had at least one success."""
        return self.coordinator.last_update_success

    async def async_press(self) -> None:
        """Handle button press: POST to the GoldHEN REST endpoint."""
        url = (
            f"http://{self._host}:{self._goldhen_port}"
            f"{self.entity_description.endpoint}"
        )
        _LOGGER.debug(
            "PS4 GoldHEN button '%s' pressed -> POST %s",
            self.entity_description.key,
            url,
        )
        try:
            async with aiohttp.ClientSession(timeout=_REST_TIMEOUT) as session:
                async with session.post(url) as resp:
                    if resp.status not in (200, 204):
                        body = await resp.text()
                        raise HomeAssistantError(
                            f"GoldHEN '{self.entity_description.key}' failed "
                            f"(HTTP {resp.status}): {body[:200]}"
                        )
        except asyncio.TimeoutError as err:
            raise HomeAssistantError(
                f"Timed out calling GoldHEN at {self._host}:{self._goldhen_port}. "
                "Is GoldHEN running and the HTTP server enabled?"
            ) from err
        except aiohttp.ClientConnectionError as err:
            raise HomeAssistantError(
                f"Cannot connect to GoldHEN at {self._host}:{self._goldhen_port}: {err}"
            ) from err

        _LOGGER.info(
            "PS4 GoldHEN '%s' command sent successfully to %s:%d",
            self.entity_description.key,
            self._host,
            self._goldhen_port,
        )
