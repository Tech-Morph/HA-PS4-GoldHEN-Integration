from __future__ import annotations

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .const import (
    DOMAIN,
    CONF_ADDON_URL,
    CONF_HOST,
    CONF_BINLOADER_PORT,
    CONF_FTP_PORT,
    DEFAULT_ADDON_URL,
    DEFAULT_BINLOADER_PORT,
    DEFAULT_FTP_PORT,
    ENDPOINT_HEALTH,
)


class PS4GoldHENConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the config flow for PS4 GoldHEN integration."""

    VERSION = 2

    async def async_step_user(self, user_input=None) -> FlowResult:
        errors = {}

        if user_input is not None:
            addon_url = user_input[CONF_ADDON_URL].rstrip("/")
            # Validate the add-on is reachable
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"{addon_url}{ENDPOINT_HEALTH}", timeout=aiohttp.ClientTimeout(total=5)
                    ) as resp:
                        if resp.status != 200:
                            errors["base"] = "addon_not_reachable"
            except Exception:
                errors["base"] = "addon_not_reachable"

            if not errors:
                return self.async_create_entry(
                    title=f"PS4 GoldHEN ({addon_url})",
                    data={
                        CONF_ADDON_URL: addon_url,
                        CONF_HOST: user_input[CONF_HOST],
                        CONF_BINLOADER_PORT: user_input[CONF_BINLOADER_PORT],
                        CONF_FTP_PORT: user_input[CONF_FTP_PORT],
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_ADDON_URL, default=DEFAULT_ADDON_URL): str,
                vol.Required(CONF_HOST, default="192.168.1.14"): str,
                vol.Optional(CONF_BINLOADER_PORT, default=DEFAULT_BINLOADER_PORT): int,
                vol.Optional(CONF_FTP_PORT, default=DEFAULT_FTP_PORT): int,
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
