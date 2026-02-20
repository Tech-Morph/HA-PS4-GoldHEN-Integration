from __future__ import annotations

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    DOMAIN,
    CONF_ADDON_URL,
    CONF_PS4_HOST,
    CONF_BINLOADER_PORT,
    DEFAULT_ADDON_URL,
    DEFAULT_PS4_HOST,
    DEFAULT_BINLOADER_PORT,
    ENDPOINT_HEALTH,
)


def _build_schema(
    addon_url: str = DEFAULT_ADDON_URL,
    ps4_host: str = DEFAULT_PS4_HOST,
    binloader_port: int = DEFAULT_BINLOADER_PORT,
) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_ADDON_URL, default=addon_url): str,
            vol.Required(CONF_PS4_HOST, default=ps4_host): str,
            vol.Required(CONF_BINLOADER_PORT, default=binloader_port): vol.All(
                vol.Coerce(int), vol.Range(min=1024, max=65535)
            ),
        }
    )


class PS4GoldHENConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the config flow for PS4 GoldHEN integration."""

    VERSION = 4

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "PS4GoldHENOptionsFlow":
        """Return the options flow handler."""
        return PS4GoldHENOptionsFlow(config_entry)

    async def async_step_user(self, user_input=None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            addon_url = user_input[CONF_ADDON_URL].rstrip("/")
            ps4_host = user_input[CONF_PS4_HOST].strip()
            binloader_port = int(user_input[CONF_BINLOADER_PORT])

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
                    title=f"PS4 GoldHEN ({ps4_host})",
                    data={
                        CONF_ADDON_URL: addon_url,
                        CONF_PS4_HOST: ps4_host,
                        CONF_BINLOADER_PORT: binloader_port,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_build_schema(),
            errors=errors,
        )


class PS4GoldHENOptionsFlow(config_entries.OptionsFlow):
    """Handle options (re-configure) flow for PS4 GoldHEN."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input=None) -> FlowResult:
        errors: dict[str, str] = {}

        current = self._config_entry.data

        if user_input is not None:
            addon_url = user_input[CONF_ADDON_URL].rstrip("/")
            ps4_host = user_input[CONF_PS4_HOST].strip()
            binloader_port = int(user_input[CONF_BINLOADER_PORT])

            # Validate the add-on is still reachable
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
                self.hass.config_entries.async_update_entry(
                    self._config_entry,
                    title=f"PS4 GoldHEN ({ps4_host})",
                    data={
                        CONF_ADDON_URL: addon_url,
                        CONF_PS4_HOST: ps4_host,
                        CONF_BINLOADER_PORT: binloader_port,
                    },
                )
                return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init",
            data_schema=_build_schema(
                addon_url=current.get(CONF_ADDON_URL, DEFAULT_ADDON_URL),
                ps4_host=current.get(CONF_PS4_HOST, DEFAULT_PS4_HOST),
                binloader_port=current.get(CONF_BINLOADER_PORT, DEFAULT_BINLOADER_PORT),
            ),
            errors=errors,
        )
