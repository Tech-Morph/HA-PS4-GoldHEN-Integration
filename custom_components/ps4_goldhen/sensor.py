"""PS4 GoldHEN sensors."""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
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
    SENSOR_RSX_TEMP,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    async_add_entities(
        [
            PS4FTPStatusSensor(coordinator, entry),
            PS4CurrentGameSensor(coordinator, entry),
            PS4CPUTempSensor(coordinator, entry),
            PS4RSXTempSensor(coordinator, entry),
        ],
        update_before_add=False,
    )


class PS4FTPStatusSensor(CoordinatorEntity, SensorEntity):
    """FTP reachability sensor."""

    _attr_has_entity_name = True
    _attr_name = "FTP Status"
    _attr_icon = "mdi:sony-playstation"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        host = entry.data[CONF_PS4_HOST]
        self._attr_unique_id = f"{DOMAIN}_{host}_ftp_status"

    @property
    def native_value(self) -> str:
        data = self.coordinator.data or {}
        return "online" if data.get("ftp_reachable") else "offline"


class PS4CurrentGameSensor(CoordinatorEntity, SensorEntity):
    """Current game sensor."""

    _attr_has_entity_name = True
    _attr_name = "Current Game"
    _attr_icon = "mdi:gamepad-variant"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        host = entry.data[CONF_PS4_HOST]
        self._attr_unique_id = f"{DOMAIN}_{host}_current_game"

    @property
    def native_value(self) -> str:
        data = self.coordinator.data or {}
        value = data.get(SENSOR_CURRENT_GAME)

        if isinstance(value, str) and value.strip():
            return value.strip()

        return "Idle"

    @property
    def extra_state_attributes(self) -> dict:
        value = self.native_value
        return {
            "title_id": value if value != "Idle" else None,
        }


class PS4CPUTempSensor(CoordinatorEntity, SensorEntity):
    """CPU temperature sensor."""

    _attr_has_entity_name = True
    _attr_name = "CPU Temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_icon = "mdi:thermometer"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        host = entry.data[CONF_PS4_HOST]
        self._attr_unique_id = f"{DOMAIN}_{host}_cpu_temp"

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data or {}
        temp = data.get(SENSOR_CPU_TEMP)
        return float(temp) if temp is not None else None


class PS4RSXTempSensor(CoordinatorEntity, SensorEntity):
    """RSX/GPU temperature sensor."""

    _attr_has_entity_name = True
    _attr_name = "RSX Temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_icon = "mdi:thermometer"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        host = entry.data[CONF_PS4_HOST]
        self._attr_unique_id = f"{DOMAIN}_{host}_rsx_temp"

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data or {}
        temp = data.get(SENSOR_RSX_TEMP)
        return float(temp) if temp is not None else None
