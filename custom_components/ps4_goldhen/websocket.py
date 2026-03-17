"""WebSocket handlers for PS4 GoldHEN."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import (
    DOMAIN,
    EVENT_KLOG_LINE,
)


def _ensure_domain_root(hass: HomeAssistant) -> dict[str, Any]:
    hass.data.setdefault(DOMAIN, {})
    root: dict[str, Any] = hass.data[DOMAIN]
    root.setdefault("_global", {})
    return root


@websocket_api.websocket_command(
    {vol.Required("type"): "ps4_goldhen/list_entries"}
)
@websocket_api.async_response
async def ws_list_entries(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    from homeassistant.config_entries import SOURCE_IMPORT
    entries = hass.config_entries.async_entries(DOMAIN)
    out = [
        {
            "entry_id": entry.entry_id,
            "title": entry.title,
            "source": entry.source or SOURCE_IMPORT,
        }
        for entry in entries
    ]
    connection.send_result(msg["id"], {"entries": out})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "ps4_goldhen/get_klog_history",
        vol.Required("entry_id"): str,
        vol.Optional("limit", default=100): int,
    }
)
@websocket_api.async_response
async def ws_get_klog_history(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    root = _ensure_domain_root(hass)
    entry_data = root.get(msg["entry_id"])
    if not entry_data:
        connection.send_error(msg["id"], "not_found", "Entry not found")
        return

    sm = entry_data.get("klog_state_machine")
    if not sm:
        connection.send_result(msg["id"], {"lines": [], "total": 0, "klog_connected": False})
        return

    limit = max(1, min(msg.get("limit", 100), 250))
    lines = list(sm.recent_lines)[-limit:]
    connection.send_result(
        msg["id"],
        {
            "lines": lines,
            "total": len(sm.recent_lines),
            "klog_connected": sm.klog_connected,
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "ps4_goldhen/subscribe_klog",
        vol.Required("entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_subscribe_klog(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    entry_id = msg["entry_id"]

    @callback
    def _forward_klog_event(event) -> None:
        if event.data.get("entry_id") != entry_id:
            return
        connection.send_event(
            msg["id"],
            {
                "message": event.data.get("message"),
                "title_id": event.data.get("title_id"),
            },
        )

    unsub = hass.bus.async_listen(EVENT_KLOG_LINE, _forward_klog_event)
    connection.subscriptions[msg["id"]] = unsub
    connection.send_result(msg["id"], {"subscribed": True})


def async_setup(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_list_entries)
    websocket_api.async_register_command(hass, ws_get_klog_history)
    websocket_api.async_register_command(hass, ws_subscribe_klog)
