from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .const import (
    DOMAIN,
    CONF_HOST,
    CONF_BINLOADER_PORT,
    CONF_FTP_PORT,
    DEFAULT_BINLOADER_PORT,
    DEFAULT_FTP_PORT,
)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_BINLOADER_PORT, default=DEFAULT_BINLOADER_PORT): vol.Coerce(int),
        vol.Optional(CONF_FTP_PORT, default=DEFAULT_FTP_PORT): vol.Coerce(int),
    }
)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None) -> FlowResult:
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=STEP_USER_DATA_SCHEMA)

        host = user_input[CONF_HOST]
        await self.async_set_unique_id(f"{DOMAIN}_{host}")
        self._abort_if_unique_id_configured()

        return self.async_create_entry(title=f"PS4 GoldHEN ({host})", data=user_input)
