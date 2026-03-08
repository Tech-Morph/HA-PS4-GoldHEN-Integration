"""PS4 GoldHEN buttons: Restart, Standby."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, CONF_PS4_HOST


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up PS4 GoldHEN buttons."""
    async_add_entities([
        PS4RestartButton(entry),
        PS4StandbyButton(entry),
    ])


class PS4RestartButton(ButtonEntity):
    """Button to restart PS4."""
    _attr_has_entity_name = True
    _attr_icon = "mdi:restart"

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        host = entry.data[CONF_PS4_HOST]
        self._attr_unique_id = f"{DOMAIN}_{host}_restart"
        self._attr_name = "Restart"

    async def async_press(self) -> None:
        """Send restart payload/command."""
        # TODO: Send "ps4_goldhen.send_payload" with restart.bin
        # or use a dedicated RPI/HTTP endpoint if GoldHEN supports it
        await self.hass.services.async_call(
            DOMAIN,
            "send_payload",
            {"payload_file": "restart.bin"},  # You need to provide this payload
            blocking=True,
        )


class PS4StandbyButton(ButtonEntity):
    """Button to put PS4 in standby."""
    _attr_has_entity_name = True
    _attr_icon = "mdi:power"

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        host = entry.data[CONF_PS4_HOST]
        self._attr_unique_id = f"{DOMAIN}_{host}_standby"
        self._attr_name = "Standby"

    async def async_press(self) -> None:
        """Send standby payload/command."""
        await self.hass.services.async_call(
            DOMAIN,
            "send_payload",
            {"payload_file": "standby.bin"},  # You need to provide this payload
            blocking=True,
        )
