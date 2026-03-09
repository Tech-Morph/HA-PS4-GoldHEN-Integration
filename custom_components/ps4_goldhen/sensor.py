"""PS4 GoldHEN sensors: FTP status, current game, CPU/SOC temp from klog."""
from __future__ import annotations

import asyncio
import logging
import re

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    CONF_PS4_HOST,
    SENSOR_CPU_TEMP,
)
from .title_resolver import PS4TitleResolver

_LOGGER = logging.getLogger(__name__)

# Example line from your klog:
# <118>[SL] AppFocusChanged [NPXS20001] -> [CUSA11993]
FOCUS_RE = re.compile(r"AppFocusChanged \[(\w+)\] -> \[(\w+)\]")


async def async_setup_entry(hass, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities(
        [
            PS4FTPStatusSensor(coordinator, entry),
            PS4CurrentGameSensor(entry),
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


class PS4CurrentGameSensor(SensorEntity):
    """Current game title sensor (parsed from live klog)."""
    _attr_has_entity_name = True
    _attr_icon = "mdi:gamepad-variant"
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry) -> None:
        self._host = entry.data[CONF_PS4_HOST]
        self._attr_unique_id = f"{DOMAIN}_{self._host}_current_game"
        self._attr_name = "Current Game"

        self._attr_native_value = "Idle"
        self._monitor_task: asyncio.Task | None = None

        self._resolver: PS4TitleResolver | None = None
        self._current_title_id: str | None = None
        self._current_source: str | None = None
        self._current_error: str | None = None

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "title_id": self._current_title_id,
            "title_source": self._current_source,
            "title_lookup_error": self._current_error,
            "ps4_host": self._host,
        }

    async def async_added_to_hass(self) -> None:
        self._resolver = PS4TitleResolver(self.hass)
        self._monitor_task = self.hass.loop.create_task(self._klog_monitor_loop())

    async def async_will_remove_from_hass(self) -> None:
        if self._monitor_task:
            self._monitor_task.cancel()

    async def _klog_monitor_loop(self) -> None:
        while True:
            writer = None
            try:
                reader, writer = await asyncio.open_connection(self._host, 3232)
                _LOGGER.debug("Connected to PS4 klog at %s:3232", self._host)

                while True:
                    line_bytes = await reader.readline()
                    if not line_bytes:
                        break

                    line = line_bytes.decode("utf-8", errors="ignore")
                    m = FOCUS_RE.search(line)
                    if not m:
                        continue

                    new_app = m.group(2)
                    self._current_title_id = new_app

                    # Resolve to friendly name
                    if self._resolver is None:
                        resolved_name = new_app
                        self._current_source = "resolver_missing"
                        self._current_error = "resolver not initialized"
                    else:
                        res = await self._resolver.async_resolve(new_app)
                        resolved_name = res.name or new_app
                        self._current_source = res.source
                        self._current_error = res.error

                    self._attr_native_value = resolved_name
                    self.async_write_ha_state()

            except asyncio.CancelledError:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                break
            except Exception as err:
                _LOGGER.debug("PS4 klog connection error: %s", err)
                self._attr_native_value = "Disconnected"
                self._current_source = "klog"
                self._current_error = str(err)
                self.async_write_ha_state()

            await asyncio.sleep(10)


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
