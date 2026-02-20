from __future__ import annotations

import asyncio
import logging

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    DOMAIN,
    CONF_PS4_HOST,
    CONF_BINLOADER_PORT,
    CONF_FTP_PORT,
    DEFAULT_PS4_HOST,
    DEFAULT_BINLOADER_PORT,
    DEFAULT_FTP_PORT,
    TCP_PROBE_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)


def _schema(
    ps4_host: str = DEFAULT_PS4_HOST,
    binloader_port: int = DEFAULT_BINLOADER_PORT,
    ftp_port: int = DEFAULT_FTP_PORT,
) -> vol.Schema:
    """Return the config/options schema with current defaults pre-filled."""
    return vol.Schema(
        {
            vol.Required(CONF_PS4_HOST, default=ps4_host): str,
            vol.Required(
                CONF_BINLOADER_PORT, default=binloader_port
            ): vol.All(vol.Coerce(int), vol.Range(min=1024, max=65535)),
            vol.Required(
                CONF_FTP_PORT, default=ftp_port
            ): vol.All(vol.Coerce(int), vol.Range(min=1024, max=65535)),
        }
    )


async def _tcp_reachable(host: str, port: int, timeout: float = TCP_PROBE_TIMEOUT) -> bool:
    """Return True if a TCP connection to host:port succeeds within timeout."""
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass
        return True
    except Exception:  # noqa: BLE001
        return False


class PS4GoldHENConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial setup flow for PS4 GoldHEN."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "PS4GoldHENOptionsFlow":
        """Expose the options (re-configure) flow."""
        return PS4GoldHENOptionsFlow(config_entry)

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Handle the first (and only) step of the setup wizard."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_PS4_HOST].strip()
            ftp_port = int(user_input[CONF_FTP_PORT])
            binloader_port = int(user_input[CONF_BINLOADER_PORT])

            # Validate: probe FTP (safe to poke).  BinLoader is NOT probed on
            # setup because repeated connections can destabilise GoldHEN.
            if not await _tcp_reachable(host, ftp_port):
                errors["base"] = "ftp_not_reachable"

            if not errors:
                # Prevent duplicate entries for the same PS4
                await self.async_set_unique_id(host)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"PS4 GoldHEN ({host})",
                    data={
                        CONF_PS4_HOST: host,
                        CONF_BINLOADER_PORT: binloader_port,
                        CONF_FTP_PORT: ftp_port,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_schema(),
            errors=errors,
        )


class PS4GoldHENOptionsFlow(config_entries.OptionsFlow):
    """Let the user change settings after the integration is set up."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input=None) -> FlowResult:
        """Show the options form (mirrors the setup form)."""
        errors: dict[str, str] = {}
        current = self._config_entry.data

        if user_input is not None:
            host = user_input[CONF_PS4_HOST].strip()
            ftp_port = int(user_input[CONF_FTP_PORT])
            binloader_port = int(user_input[CONF_BINLOADER_PORT])

            if not await _tcp_reachable(host, ftp_port):
                errors["base"] = "ftp_not_reachable"

            if not errors:
                self.hass.config_entries.async_update_entry(
                    self._config_entry,
                    title=f"PS4 GoldHEN ({host})",
                    data={
                        CONF_PS4_HOST: host,
                        CONF_BINLOADER_PORT: binloader_port,
                        CONF_FTP_PORT: ftp_port,
                    },
                )
                return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init",
            data_schema=_schema(
                ps4_host=current.get(CONF_PS4_HOST, DEFAULT_PS4_HOST),
                binloader_port=current.get(CONF_BINLOADER_PORT, DEFAULT_BINLOADER_PORT),
                ftp_port=current.get(CONF_FTP_PORT, DEFAULT_FTP_PORT),
            ),
            errors=errors,
        )
