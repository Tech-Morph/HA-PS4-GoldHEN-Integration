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
    SENSOR_RSX_TEMP,
)

_HOME_SCREEN_STATE = "PlayStation Home Screen"
_IDLE_STATE = "Idle"
_REST_MODE_STATE = "Rest Mode"
_OFF_STATE = "Off"

# Entity ID of your Pi-based PS4 state sensor
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
    """Current game / power state sensor.

    Logic:
    - If Pi sensor says 'Rest' or 'Offline' → show that, ignore klog entirely
    - If Pi sensor says 'On' → show the klog-derived game/home state
    - If Pi sensor is unavailable → fall back to klog state
    """

    _attr_has_entity_name = True
    _attr_name = "Current Game"
    _attr_icon = "mdi:gamepad-variant"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        host = entry.data[CONF_PS4_HOST]
        self._attr_unique_id = f"{DOMAIN}_{host}_current_game"
        self._pi_state: str | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        # Seed from current Pi sensor state immediately
        pi_entity = self.hass.states.get(_PI_STATE_SENSOR)
        if pi_entity:
            self._pi_state = pi_entity.state

        # Subscribe to Pi sensor changes
        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                [_PI_STATE_SENSOR],
                self._handle_pi_state_change,
            )
        )

    @callback
    def _handle_pi_state_change(self, event) -> None:
        new_state = event.data.get("new_state")
        if new_state:
            self._pi_state = new_state.state
            self.async_write_ha_state()

    def _get_klog_state(self) -> str:
        data = self.coordinator.data or {}
        value = data.get(SENSOR_CURRENT_GAME)
        if isinstance(value, str) and value.strip():
            return value.strip()
        return _HOME_SCREEN_STATE

    @property
    def native_value(self) -> str:
        pi = (self._pi_state or "").strip().lower()

        # Pi says console is not fully on — trust it completely
        if pi == "rest":
            return _REST_MODE_STATE
        if pi == "offline":
            return _OFF_STATE

        # Pi says on (or unknown) — use klog for game/home state
        return self._get_klog_state()

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        value = self.native_value

        return {
            "title_id": value if value not in (
                _HOME_SCREEN_STATE, _IDLE_STATE, _REST_MODE_STATE, _OFF_STATE
            ) else None,
            "state_classification": (
                "home_screen" if value == _HOME_SCREEN_STATE
                else "idle" if value == _IDLE_STATE
                else "rest" if value == _REST_MODE_STATE
                else "off" if value == _OFF_STATE
                else "game"
            ),
            "pi_state": self._pi_state,
            "klog_state": self._get_klog_state(),
            "klog_connected": data.get("klog_connected", False),
            "state_reason": data.get("state_reason"),
            "state_signal_line": data.get("state_signal_line"),
            "pending_title_id": data.get("pending_title_id"),
            "pending_reason": data.get("pending_reason"),
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
