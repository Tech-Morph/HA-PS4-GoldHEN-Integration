"""PS4 GoldHEN sensors."""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    CONF_PS4_HOST,
    SENSOR_CURRENT_GAME,
    SENSOR_CPU_TEMP,
)

_HOME_SCREEN_STATE = "PlayStation Home Screen"
_IDLE_STATE = "Idle"
_REST_MODE_STATE = "Rest Mode"
_OFF_STATE = "Off"

# Pi power-state sensor
_PI_STATE_SENSOR = "sensor.ps4_state_pi"


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
        ],
        update_before_add=False,
    )


class PS4FTPStatusSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "FTP Status"
    _attr_icon = "mdi:sony-playstation"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{entry.data[CONF_PS4_HOST]}_ftp_status"

    @property
    def native_value(self) -> str:
        data = self.coordinator.data or {}
        return "online" if data.get("ftp_reachable") else "offline"


class PS4CurrentGameSensor(CoordinatorEntity, SensorEntity):
    """
    Reports the current PS4 state.

    Power state comes from sensor.ps4_state_pi.
    Game state comes from klog state machine.
    """

    _attr_has_entity_name = True
    _attr_name = "Current Game"
    _attr_icon = "mdi:gamepad-variant"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{entry.data[CONF_PS4_HOST]}_current_game"
        self._pi_state: str | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        pi = self.hass.states.get(_PI_STATE_SENSOR)
        if pi:
            self._pi_state = pi.state

        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                [_PI_STATE_SENSOR],
                self._on_pi_state_change,
            )
        )

    @callback
    def _on_pi_state_change(self, event) -> None:
        new = event.data.get("new_state")
        if new:
            self._pi_state = new.state
            self.async_write_ha_state()

    def _klog_state(self) -> str:
        data = self.coordinator.data or {}
        val = data.get(SENSOR_CURRENT_GAME)

        if isinstance(val, str) and val.strip():
            return val.strip()

        return _HOME_SCREEN_STATE

    @property
    def native_value(self) -> str:
        pi = (self._pi_state or "").strip().lower()

        if pi == "rest":
            return _REST_MODE_STATE

        if pi == "offline":
            return _OFF_STATE

        return self._klog_state()

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        val = self.native_value

        return {
            "title_id": data.get("title_id"),
            "state_classification": (
                "rest"
                if val == _REST_MODE_STATE
                else "off"
                if val == _OFF_STATE
                else "home_screen"
                if val == _HOME_SCREEN_STATE
                else "idle"
                if val == _IDLE_STATE
                else "game"
            ),
            "pi_state": self._pi_state,
            "klog_state": self._klog_state(),
            "klog_connected": data.get("klog_connected", False),
            "state_reason": data.get("state_reason"),
            "pending_title_id": data.get("pending_title_id"),
            "state_signal_line": data.get("state_signal_line"),
        }


class PS4CPUTempSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "CPU Temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_icon = "mdi:thermometer"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{entry.data[CONF_PS4_HOST]}_cpu_temp"

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data or {}
        temp = data.get(SENSOR_CPU_TEMP)

        if temp is None:
            return None

        return float(temp)
