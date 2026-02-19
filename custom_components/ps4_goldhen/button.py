from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    ENDPOINT_WAKE,
    ENDPOINT_STANDBY,
    ENDPOINT_REBOOT,
)


@dataclass(frozen=True, kw_only=True)
class Ps4GoldhenButtonDescription(ButtonEntityDescription):
    endpoint: str
    method: str = "post"  # "get" or "post"


BUTTONS: tuple[Ps4GoldhenButtonDescription, ...] = (
    Ps4GoldhenButtonDescription(
        key="wake",
        name="Wake",
        icon="mdi:power",
        endpoint=ENDPOINT_WAKE,
        method="post",
    ),
    Ps4GoldhenButtonDescription(
        key="standby",
        name="Standby",
        icon="mdi:sleep",
        endpoint=ENDPOINT_STANDBY,
        method="get",
    ),
    Ps4GoldhenButtonDescription(
        key="reboot",
        name="Reboot",
        icon="mdi:restart",
        endpoint=ENDPOINT_REBOOT,
        method="get",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    addon_url = hass.data[DOMAIN][entry.entry_id]["addon_url"]
    async_add_entities(
        [Ps4GoldhenButton(coordinator, addon_url, desc) for desc in BUTTONS]
    )


class Ps4GoldhenButton(CoordinatorEntity, ButtonEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator,
        addon_url: str,
        description: Ps4GoldhenButtonDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._addon_url = addon_url
        self._attr_unique_id = f"{DOMAIN}_{description.key}_button"

    async def async_press(self) -> None:
        import aiohttp

        url = f"{self._addon_url}{self.entity_description.endpoint}"
        async with aiohttp.ClientSession() as session:
            if self.entity_description.method == "post":
                async with session.post(url, json={}, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    resp.raise_for_status()
            else:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    resp.raise_for_status()
