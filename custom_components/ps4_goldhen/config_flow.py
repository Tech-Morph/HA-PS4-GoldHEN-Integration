from __future__ import annotations

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .const import (
    DOMAIN,
    CONF_ADDON_URL,
    DEFAULT_ADDON_URL,
    ENDPOINT_HEALTH,
)


class PS4GoldHENConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the config flow for PS4 GoldHEN integration."""

    VERSION = 3

    async def async_step_user(self, user_input=None) -> FlowResult:
        errors = {}

        if user_input is not None:
            addon_url = user_input[CONF_ADDON_URL].rstrip("/")

            # Validate the add-on is reachable
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"{addon_url}{ENDPOINT_HEALTH}",
                        timeout=aiohttp.ClientTimeout(total=5),
                    ) as resp:
                        if resp.status != 200:
                            errors["base"] = "addon_not_reachable"
            except Exception:  # noqa: BLE001
                errors["base"] = "addon_not_reachable"

            if not errors:
                return self.async_create_entry(
                    title=f"PS4 GoldHEN ({addon_url})",
                    data={
                        CONF_ADDON_URL: addon_url,
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_ADDON_URL, default=DEFAULT_ADDON_URL): str,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "addon_url_hint": "e.g. http://192.168.1.50:8787"
            },
        )
