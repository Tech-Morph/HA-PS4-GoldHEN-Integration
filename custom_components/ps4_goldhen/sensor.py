"""PS4 GoldHEN sensors."""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature, UnitOfPower
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    CONF_PS4_HOST,
    SENSOR_CURRENT_GAME,
    SENSOR_CPU_TEMP,
    SENSOR_SOC_TEMP,
    SENSOR_TITLE_ID,
    SENSOR_GAME_NAME,
    SENSOR_GAME_COVER,
    SENSOR_KLOG_LAST_LINE,
    SENSOR_SOC_POWER,
    SENSOR_CPU_POWER,
    SENSOR_GPU_POWER,
    SENSOR_TOTAL_POWER,
    HOME_SCREEN,
)

_HOME_SCREEN_STATE = HOME_SCREEN
_IDLE_STATE        = "Idle"
_REST_MODE_STATE   = "Rest Mode"
_OFF_STATE         = "Off"

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
            PS4SoCTempSensor(coordinator, entry),
            PS4SoCPowerSensor(coordinator, entry),
            PS4CPUPowerSensor(coordinator, entry),
            PS4GPUPowerSensor(coordinator, entry),
            PS4TotalPowerSensor(coordinator, entry),
            PS4KlogLastLineSensor(coordinator, entry),
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
    _attr_has_entity_name = True
    _attr_name = "Current Game"
    _attr_icon = "mdi:gamepad-variant"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{entry.data[CONF_PS4_HOST]}_current_game"
        self._entry_id = entry.entry_id
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

    def _ps4_state(self) -> str:
        data = self.coordinator.data or {}
        tid  = data.get(SENSOR_TITLE_ID)
        if not tid:
            return _HOME_SCREEN_STATE
        name = data.get(SENSOR_GAME_NAME)
        if name and name.strip():
            return name.strip()
        return tid

    @property
    def native_value(self) -> str:
        pi = (self._pi_state or "").strip().lower()
        if pi == "rest":
            return _REST_MODE_STATE
        if pi == "offline":
            return _OFF_STATE
        return self._ps4_state()

    @property
    def entity_picture(self) -> str | None:
        data = self.coordinator.data or {}
        tid  = data.get(SENSOR_TITLE_ID)
        if not tid:
            return None
        return f"/api/ps4_goldhen/cover/{self._entry_id}/{tid}"

    @property
    def extra_state_attributes(self) -> dict:
        data     = self.coordinator.data or {}
        val      = self.native_value
        tid      = data.get(SENSOR_TITLE_ID)
        game_map  = (
            self.hass.data.get(DOMAIN, {})
            .get(self._entry_id, {})
            .get("game_map", {})
        )
        game_info = game_map.get(tid, {}) if tid else {}
        return {
            SENSOR_TITLE_ID:    tid,
            SENSOR_GAME_NAME:   data.get(SENSOR_GAME_NAME),
            "cdn_cover":        game_info.get("cdn_cover"),
            "cover_url": (
                f"/api/ps4_goldhen/cover/{self._entry_id}/{tid}" if tid else None
            ),
            "state_classification": (
                "rest"        if val == _REST_MODE_STATE  else
                "off"         if val == _OFF_STATE        else
                "home_screen" if val == _HOME_SCREEN_STATE else
                "game"
            ),
            "pi_state":          self._pi_state,
            "klog_connected":    data.get("klog_connected", False),
            "state_reason":      data.get("state_reason"),
            "pending_title_id":  data.get("pending_title_id"),
            "state_signal_line": data.get("state_signal_line"),
        }


class PS4CPUTempSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "CPU Temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:thermometer"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{entry.data[CONF_PS4_HOST]}_cpu_temp"

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data or {}
        temp = data.get(SENSOR_CPU_TEMP)
        return float(temp) if temp is not None else None


class PS4SoCTempSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "SoC Temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:thermometer"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{entry.data[CONF_PS4_HOST]}_soc_temp"

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data or {}
        temp = data.get(SENSOR_SOC_TEMP)
        return float(temp) if temp is not None else None


class PS4SoCPowerSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "SoC Power"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.MILLIWATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:chip"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{entry.data[CONF_PS4_HOST]}_soc_power"

    @property
    def native_value(self) -> int | None:
        return (self.coordinator.data or {}).get(SENSOR_SOC_POWER)


class PS4CPUPowerSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "CPU Power"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.MILLIWATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:cpu-64-bit"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{entry.data[CONF_PS4_HOST]}_cpu_power"

    @property
    def native_value(self) -> int | None:
        return (self.coordinator.data or {}).get(SENSOR_CPU_POWER)


class PS4GPUPowerSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "GPU Power"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.MILLIWATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:gpu"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{entry.data[CONF_PS4_HOST]}_gpu_power"

    @property
    def native_value(self) -> int | None:
        return (self.coordinator.data or {}).get(SENSOR_GPU_POWER)


class PS4TotalPowerSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Total Power"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.MILLIWATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:flash"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{entry.data[CONF_PS4_HOST]}_total_power"

    @property
    def native_value(self) -> int | None:
        return (self.coordinator.data or {}).get(SENSOR_TOTAL_POWER)


class PS4KlogLastLineSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Klog Last Line"
    _attr_icon = "mdi:console-line"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{entry.data[CONF_PS4_HOST]}_klog_last_line"

    @property
    def native_value(self) -> str | None:
        data = self.coordinator.data or {}
        line = data.get(SENSOR_KLOG_LAST_LINE)
        return line[:255] if line else None
