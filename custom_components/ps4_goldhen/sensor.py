from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


@dataclass(frozen=True, kw_only=True)
class Ps4GoldhenSensorDescription(SensorEntityDescription):
    key: str


SENSORS: tuple[Ps4GoldhenSensorDescription, ...] = (
    Ps4GoldhenSensorDescription(
        key="binloader_ok",
        name="BinLoader Reachable",
        icon="mdi:lan-connect",
    ),
    Ps4GoldhenSensorDescription(
        key="ftp_ok",
        name="FTP Reachable",
        icon="mdi:folder-network",
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
        host = coordinator.data.get("host", "ps4")
        self._attr_unique_id = f"{DOMAIN}_{host}_{description.key}"

    @property
    def native_value(self) -> Any:
        # show as "on/off" text-like sensor; you can later switch to binary_sensor if desired
        v = self.coordinator.data.get(self.entity_description.key)
        return "on" if v else "off"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "host": self.coordinator.data.get("host"),
            "binloader_port": self.coordinator.data.get("binloader_port"),
            "ftp_port": self.coordinator.data.get("ftp_port"),
        }
