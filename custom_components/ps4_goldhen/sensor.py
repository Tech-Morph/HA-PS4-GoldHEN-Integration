from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_ADDON_URL


@dataclass(frozen=True, kw_only=True)
class Ps4GoldhenSensorDescription(SensorEntityDescription):
    key: str


SENSORS: tuple[Ps4GoldhenSensorDescription, ...] = (
    Ps4GoldhenSensorDescription(
        key="available",
        name="Add-on Reachable",
        icon="mdi:lan-connect",
    ),
    Ps4GoldhenSensorDescription(
        key="status",
        name="PS4 Status",
        icon="mdi:sony-playstation",
    ),
    Ps4GoldhenSensorDescription(
        key="goldhen",
        name="GoldHEN Status",
        icon="mdi:script-text",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([Ps4GoldhenSensor(coordinator, desc) for desc in SENSORS])


class Ps4GoldhenSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, description: Ps4GoldhenSensorDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{DOMAIN}_{description.key}"

    @property
    def native_value(self) -> Any:
        data = self.coordinator.data or {}
        val = data.get(self.entity_description.key)
        if self.entity_description.key == "available":
            return "online" if val else "offline"
        if val is None:
            return "unknown"
        return str(val)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        return {
            "addon_url": self.coordinator.config_entry.data.get(CONF_ADDON_URL),
            "ps4_ip": data.get("ip"),
            "ps4_mac": data.get("mac"),
            "firmware": data.get("firmware"),
            "goldhen_version": data.get("goldhen_version"),
        }

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success
