"""PS4 GoldHEN sensors: FTP status, current game, CPU/SOC temp from klog."""
from __future__ import annotations
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    CONF_PS4_HOST,
    SENSOR_CURRENT_GAME,
    SENSOR_CPU_TEMP,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([
        PS4FTPStatusSensor(coordinator, entry),
        PS4CurrentGameSensor(coordinator, entry),
        PS4CPUTempSensor(coordinator, entry),
    ])


class PS4FTPStatusSensor(CoordinatorEntity, SensorEntity):
    """FTP reachability sensor."""
    _attr_has_entity_name = True
    _attr_icon = "mdi:sony-playstation"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        host = entry.data[CONF_PS4_HOST]
        self._attr_unique_id = f"{DOMAIN}_{host}_ftp_status"
        self._attr_name = "FTP Status"

    @property
    def native_value(self) -> str:
        data = self.coordinator.data or {}
        return "online" if data.get("ftp_reachable") else "offline"


class PS4CurrentGameSensor(CoordinatorEntity, SensorEntity):
    """Current game title sensor (parsed from klog)."""
    _attr_has_entity_name = True
    _attr_icon = "mdi:gamepad-variant"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        host = entry.data[CONF_PS4_HOST]
        self._attr_unique_id = f"{DOMAIN}_{host}_current_game"
        self._attr_name = "Current Game"

    @property
    def native_value(self) -> str | None:
        data = self.coordinator.data or {}
        return data.get(SENSOR_CURRENT_GAME, "Unknown")


class PS4CPUTempSensor(CoordinatorEntity, SensorEntity):
    """CPU/SOC temperature sensor (parsed from klog)."""
    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_icon = "mdi:thermometer"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        host = entry.data[CONF_PS4_HOST]
        self._attr_unique_id = f"{DOMAIN}_{host}_cpu_temp"
        self._attr_name = "CPU Temperature"

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data or {}
        temp = data.get(SENSOR_CPU_TEMP)
        return float(temp) if temp is not None else None
