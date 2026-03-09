"""PS4 GoldHEN sensors: FTP status, current game, CPU/SOC temp from klog."""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any
from aiohttp import ClientError

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    CONF_PS4_HOST,
    SENSOR_CPU_TEMP,
)

_LOGGER = logging.getLogger(__name__)

# Regex to catch the focus change line
FOCUS_RE = re.compile(r'AppFocusChanged \[(\w+)\] -> \[(\w+)\]')


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([
        PS4FTPStatusSensor(coordinator, entry),
        PS4CurrentGameSensor(entry),
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


class PS4CurrentGameSensor(SensorEntity):
    """Current game title sensor (parsed from live klog)."""
    _attr_has_entity_name = True
    _attr_icon = "mdi:gamepad-variant"
    _attr_should_poll = False  # HA will not poll this; it updates itself via socket

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._host = entry.data[CONF_PS4_HOST]
        self._attr_unique_id = f"{DOMAIN}_{self._host}_current_game"
        self._attr_name = "Current Game"
        self._attr_native_value = "Idle"
        
        self._title_cache = {
            "NPXS20001": "PlayStation Home Screen"
        }
        self._monitor_task = None

    async def async_added_to_hass(self) -> None:
        """Run when entity is about to be added to hass."""
        self._monitor_task = self.hass.loop.create_task(self._klog_monitor_loop())

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity will be removed from hass."""
        if self._monitor_task:
            self._monitor_task.cancel()

    async def _async_get_game_title(self, title_id: str) -> str:
        """Fetch the game title using Sony's official Metadata Database (TMDB)."""
        if title_id in self._title_cache:
            return self._title_cache[title_id]
            
        if title_id.startswith("NPXS"):
            name = f"System App ({title_id})"
            self._title_cache[title_id] = name
            return name

        session = async_get_clientsession(self.hass)
        
        # Sony's official TMDB endpoint for PS4 uses the CUSA ID + _00
        url = f"https://tmdb.np.dl.playstation.net/tmdb2/{title_id}_00.xml"
        
        try:
            async with session.get(url, timeout=5) as response:
                if response.status == 200:
                    xml_data = await response.text()
                    
                    # Extract the title name from the XML using regex
                    # Sony typically places it inside <name> tags
                    match = re.search(r'<name>(.*?)</name>', xml_data, re.IGNORECASE)
                    if match:
                        name = match.group(1).strip()
                        self._title_cache[title_id] = name
                        return name
                        
        except (ClientError, asyncio.TimeoutError) as err:
            _LOGGER.debug("Failed to fetch title from Sony TMDB for %s: %s", title_id, err)
            
        # Fallback to the raw CUSA ID if offline/fails
        return title_id 

    async def _klog_monitor_loop(self) -> None:
        """Background task to continuously read from the PS4 klog socket."""
        while True:
            try:
                reader, writer = await asyncio.open_connection(self._host, 3232)
                _LOGGER.debug("Connected to PS4 klog at %s:3232", self._host)
                
                if self._attr_native_value == "Disconnected":
                    self._attr_native_value = "Idle"
                    self.async_write_ha_state()

                while True:
                    line_bytes = await reader.readline()
                    if not line_bytes:
                        break
                        
                    line = line_bytes.decode('utf-8', errors='ignore')
                    match = FOCUS_RE.search(line)
                    
                    if match:
                        new_app = match.group(2)
                        game_title = await self._async_get_game_title(new_app)
                        
                        self._attr_native_value = game_title
                        self.async_write_ha_state()

            except asyncio.CancelledError:
                _LOGGER.debug("PS4 klog monitor task cancelled")
                if 'writer' in locals():
                    writer.close()
                    await writer.wait_closed()
                break
            except Exception as e:
                _LOGGER.debug("PS4 klog connection lost or failed: %s", e)
                self._attr_native_value = "Disconnected"
                self.async_write_ha_state()
                
            # Wait 10 seconds before attempting to reconnect if the PS4 is turned off
            await asyncio.sleep(10)


class PS4CPUTempSensor(CoordinatorEntity, SensorEntity):
    """CPU/SOC temperature sensor (parsed from coordinator)."""
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

