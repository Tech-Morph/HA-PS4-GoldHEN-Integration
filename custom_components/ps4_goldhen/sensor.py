from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    CONF_PS4_HOST,
    CONF_BINLOADER_PORT,
    CONF_FTP_PORT,
    DEFAULT_BINLOADER_PORT,
    DEFAULT_FTP_PORT,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the sensors for this config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities(
        [
            PS4FTPSensor(coordinator, entry),
        ]
    )


class PS4FTPSensor(CoordinatorEntity, SensorEntity):
    """
    Sensor: GoldHEN FTP reachability.

    Reports "online" when a TCP connection to the FTP port (default 2121)
    succeeds, and "offline" otherwise.

    NOTE: BinLoader (9090) is intentionally NOT probed on a schedule because
    repeated connections can destabilise the GoldHEN BinLoader service.
    Payloads are only sent on demand via the ps4_goldhen.send_payload service.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:sony-playstation"

    def __init__(
        self,
        coordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        host = entry.data[CONF_PS4_HOST]
        # Unique ID ensures this sensor survives restarts and re-imports
        self._attr_unique_id = f"{DOMAIN}_{host}_ftp"
        self._attr_name = "GoldHEN FTP"

    @property
    def native_value(self) -> str:
        """Return 'online' or 'offline' based on the FTP TCP probe."""
        data = self.coordinator.data or {}
        return "online" if data.get("ftp_reachable") else "offline"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose connection details as attributes."""
        entry_data = self._entry.data
        return {
            "ps4_host": entry_data.get(CONF_PS4_HOST),
            "ftp_port": entry_data.get(CONF_FTP_PORT, DEFAULT_FTP_PORT),
            "binloader_port": entry_data.get(CONF_BINLOADER_PORT, DEFAULT_BINLOADER_PORT),
            "note": (
                "BinLoader port is not polled on a schedule; "
                "use ps4_goldhen.send_payload to send payloads on demand."
            ),
        }

    @property
    def available(self) -> bool:
        """Sensor is always available as long as HA can run the coordinator."""
        return self.coordinator.last_update_success
