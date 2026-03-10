"""PS4 GoldHEN image entity — current game cover art."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    CONF_PS4_HOST,
    SENSOR_TITLE_ID,
    SENSOR_GAME_NAME,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities(
        [PS4GameCoverImageEntity(coordinator, entry)],
        update_before_add=False,
    )


class PS4GameCoverImageEntity(CoordinatorEntity, ImageEntity):
    """
    Image entity that always shows the cover art for the currently
    running PS4 game. Updates automatically when the game changes.

    Entity ID: image.ps4_goldhen_game_cover
    """

    _attr_has_entity_name = True
    _attr_name            = "Game Cover"
    _attr_icon            = "mdi:image-frame"
    _attr_content_type    = "image/png"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        CoordinatorEntity.__init__(self, coordinator)
        ImageEntity.__init__(self, coordinator.hass)
        self._attr_unique_id     = f"{DOMAIN}_{entry.data[CONF_PS4_HOST]}_game_cover"
        self._entry_id           = entry.entry_id
        self._last_tid: str | None = None
        self._image_last_updated = datetime.now(timezone.utc)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Bump image_last_updated whenever the title changes so HA re-fetches."""
        data = self.coordinator.data or {}
        tid  = data.get(SENSOR_TITLE_ID)
        if tid != self._last_tid:
            self._last_tid = tid
            self._image_last_updated = datetime.now(timezone.utc)
        self.async_write_ha_state()

    @property
    def image_last_updated(self) -> datetime:
        return self._image_last_updated

    @property
    def image_url(self) -> str | None:
        """
        Return the proxy URL for the cover image.
        HA fetches this URL server-side so auth is handled correctly.
        Returns None when no game is active — HA will show a placeholder.
        """
        data = self.coordinator.data or {}
        tid  = data.get(SENSOR_TITLE_ID)
        if not tid:
            return None
        return f"/api/ps4_goldhen/cover/{self._entry_id}/{tid}"

    @property
    def extra_state_attributes(self) -> dict:
        data     = self.coordinator.data or {}
        tid      = data.get(SENSOR_TITLE_ID)
        game_map = (
            self.hass.data.get(DOMAIN, {})
            .get(self._entry_id, {})
            .get("game_map", {})
        )
        game_info = game_map.get(tid, {}) if tid else {}
        return {
            "title_id":  tid,
            "game_name": data.get(SENSOR_GAME_NAME),
            "cdn_cover": game_info.get("cdn_cover"),
            "cover_url": (
                f"/api/ps4_goldhen/cover/{self._entry_id}/{tid}" if tid else None
            ),
        }
