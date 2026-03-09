"""PS4 GoldHEN sensors: FTP status, current game, CPU/SOC temp from klog."""
from __future__ import annotations

import logging
import asyncio

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    CONF_PS4_HOST,
    SENSOR_CURRENT_GAME,
    SENSOR_CPU_TEMP,
)
from .title_resolver import PS4TitleResolver

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities(
        [
            PS4FTPStatusSensor(coordinator, entry),
            PS4CurrentGameSensor(coordinator, entry),
            PS4CPUTempSensor(coordinator, entry),
        ],
        update_before_add=False,
    )


class PS4FTPStatusSensor(CoordinatorEntity, SensorEntity):
    """FTP reachability sensor."""
    _attr_has_entity_name = True
    _attr_icon = "mdi:sony-playstation"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        host = entry.data[CONF_PS4_HOST]
        self._attr_unique_id = f"{DOMAIN}_{host}_ftp_status"
        self._attr_name = "FTP Status"

    @property
    def native_value(self) -> str:
        data = self.coordinator.data or {}
        return "online" if data.get("ftp_reachable") else "offline"


class PS4CurrentGameSensor(CoordinatorEntity, SensorEntity):
    """Current game title sensor (translates CUSA IDs from the coordinator)."""
    _attr_has_entity_name = True
    _attr_icon = "mdi:gamepad-variant"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._host = entry.data[CONF_PS4_HOST]
        self._attr_unique_id = f"{DOMAIN}_{self._host}_current_game"
        self._attr_name = "Current Game"

        self._resolver: PS4TitleResolver | None = None
        self._current_title_id: str | None = None
        self._resolved_name: str | None = "Idle"
        
        # Attributes for debugging
        self._current_source: str | None = None
        self._current_error: str | None = None

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "title_id": self._current_title_id,
            "title_source": self._current_source,
            "title_lookup_error": self._current_error,
        }

    @property
    def native_value(self) -> str | None:
        return self._resolved_name

    async def async_added_to_hass(self) -> None:
        """Run when entity is about to be added."""
        await super().async_added_to_hass()
        self._resolver = PS4TitleResolver(self.hass)
        self._update_internal_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Intercept updated data from the coordinator in __init__.py."""
        self._update_internal_state()
        super()._handle_coordinator_update()

    def _update_internal_state(self) -> None:
        """Check if the title ID changed, and resolve it without blocking."""
        data = self.coordinator.data or {}
        new_title_id = data.get(SENSOR_CURRENT_GAME, "Idle")

        # If the ID hasn't changed, do nothing
        if new_title_id == self._current_title_id:
            return

        self._current_title_id = new_title_id

        # If __init__.py passes us a standard status word, pass it straight through
        if not new_title_id or new_title_id in ("Disconnected", "Idle", "Unknown"):
            self._resolved_name = new_title_id or "Idle"
            self._current_source = None
            self._current_error = None
            return

        # It's a new Title ID, launch a background task to resolve the actual name
        self.hass.loop.create_task(self._async_resolve_and_write(new_title_id))

    async def _async_resolve_and_write(self, title_id: str) -> None:
        """Fetch the title using PS4TitleResolver and update HA state."""
        if not self._resolver:
            return

        res = await self._resolver.async_resolve(title_id)
        
        # Ensure the ID didn't change while we were waiting for the network
        if self._current_title_id == title_id:
            self._resolved_name = res.name or title_id
            self._current_source = res.source
            self._current_error = res.error
            self.async_write_ha_state()


class PS4CPUTempSensor(CoordinatorEntity, SensorEntity):
    """CPU/SOC temperature sensor (parsed from coordinator)."""
    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_icon = "mdi:thermometer"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        host = entry.data[CONF_PS4_HOST]
        self._attr_unique_id = f"{DOMAIN}_{host}_cpu_temp"
        self._attr_name = "CPU Temperature"

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data or {}
        temp = data.get(SENSOR_CPU_TEMP)
        return float(temp) if temp is not None else None
