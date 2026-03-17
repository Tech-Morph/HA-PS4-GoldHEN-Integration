"""WebSocket handlers for PS4 GoldHEN."""
from __future__ import annotations

import ftplib
import io
import os
import stat
from datetime import datetime
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import (
    DOMAIN,
    CONF_PS4_HOST,
    CONF_BINLOADER_PORT,
    CONF_FTP_PORT,
    CONF_RPI_PORT,
    CONF_KLOG_PORT,
    DEFAULT_BINLOADER_PORT,
    DEFAULT_FTP_PORT,
    DEFAULT_RPI_PORT,
    DEFAULT_KLOG_PORT,
    PAYLOAD_DIR,
    EVENT_KLOG_LINE,
)


def _ensure_domain_root(hass: HomeAssistant) -> dict[str, Any]:
    hass.data.setdefault(DOMAIN, {})
    return hass.data[DOMAIN]


def _get_entry_data(hass: HomeAssistant, entry_id: str) -> dict[str, Any] | None:
    return _ensure_domain_root(hass).get(entry_id)


# ── list_entries ───────────────────────────────────────────────────────────────

@websocket_api.websocket_command(
    {vol.Required("type"): "ps4_goldhen/list_entries"}
)
@websocket_api.async_response
async def ws_list_entries(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    entries = hass.config_entries.async_entries(DOMAIN)
    out = [
        {
            "entry_id":       entry.entry_id,
            "title":          entry.title,
            "ps4_host":       entry.data.get(CONF_PS4_HOST),
            "ftp_port":       entry.data.get(CONF_FTP_PORT,       DEFAULT_FTP_PORT),
            "binloader_port": entry.data.get(CONF_BINLOADER_PORT, DEFAULT_BINLOADER_PORT),
            "klog_port":      entry.data.get(CONF_KLOG_PORT,      DEFAULT_KLOG_PORT),
            "rpi_port":       entry.data.get(CONF_RPI_PORT,       DEFAULT_RPI_PORT),
        }
        for entry in entries
    ]
    connection.send_result(msg["id"], {"entries": out})


# ── list_payloads ──────────────────────────────────────────────────────────────

@websocket_api.websocket_command(
    {vol.Required("type"): "ps4_goldhen/list_payloads"}
)
@websocket_api.async_response
async def ws_list_payloads(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    from pathlib import Path

    def _list() -> list[str]:
        p = Path(PAYLOAD_DIR)
        p.mkdir(parents=True, exist_ok=True)
        hidden = {"linux.bin"}
        return [
            e.name for e in sorted(p.iterdir(), key=lambda e: e.name)
            if e.is_file()
            and e.name.lower() not in hidden
            and e.suffix.lower() in (".bin", ".elf")
        ]

    try:
        items = await hass.async_add_executor_job(_list)
        connection.send_result(msg["id"], {"payloads": items, "payload_dir": PAYLOAD_DIR})
    except Exception as err:
        connection.send_error(msg["id"], "list_error", str(err))


# ── FTP helpers ────────────────────────────────────────────────────────────────

def _ftp_connect(host: str, port: int) -> ftplib.FTP:
    ftp = ftplib.FTP()
    ftp.connect(host, port, timeout=15)
    ftp.login()
    return ftp


def _ftp_list_dir(host: str, port: int, path: str) -> dict[str, Any]:
    entries = []
    with _ftp_connect(host, port) as ftp:
        ftp.cwd(path)
        cwd = ftp.pwd()
        lines = []
        ftp.retrlines("LIST", lines.append)
        for line in lines:
            parts = line.split(None, 8)
            if len(parts) < 9:
                continue
            perms    = parts[0]
            size_str = parts[4]
            name     = parts[8]
            mod_str  = " ".join(parts[5:8])
            if name in (".", ".."):
                continue
            is_dir = perms.startswith("d")
            full   = (cwd.rstrip("/") + "/" + name)
            try:
                size = int(size_str)
            except ValueError:
                size = 0
            entries.append({
                "name":     name,
                "path":     full,
                "is_dir":   is_dir,
                "size":     size,
                "modified": mod_str,
            })
    return {"path": cwd, "entries": entries}


# ── ftp_list_dir ───────────────────────────────────────────────────────────────

@websocket_api.websocket_command(
    {
        vol.Required("type"):     "ps4_goldhen/ftp_list_dir",
        vol.Required("entry_id"): str,
        vol.Optional("path", default="/"): str,
    }
)
@websocket_api.async_response
async def ws_ftp_list_dir(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    data = _get_entry_data(hass, msg["entry_id"])
    if not data:
        connection.send_error(msg["id"], "not_found", "Entry not found")
        return
    try:
        result = await hass.async_add_executor_job(
            _ftp_list_dir, data["host"], data["ftp_port"], msg["path"]
        )
        connection.send_result(msg["id"], result)
    except Exception as err:
        connection.send_error(msg["id"], "ftp_error", str(err))


# ── ftp_delete ─────────────────────────────────────────────────────────────────

@websocket_api.websocket_command(
    {
        vol.Required("type"):     "ps4_goldhen/ftp_delete",
        vol.Required("entry_id"): str,
        vol.Required("path"):     str,
        vol.Optional("is_dir", default=False): bool,
    }
)
@websocket_api.async_response
async def ws_ftp_delete(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    data = _get_entry_data(hass, msg["entry_id"])
    if not data:
        connection.send_error(msg["id"], "not_found", "Entry not found")
        return

    def _delete():
        with _ftp_connect(data["host"], data["ftp_port"]) as ftp:
            if msg["is_dir"]:
                ftp.rmd(msg["path"])
            else:
                ftp.delete(msg["path"])

    try:
        await hass.async_add_executor_job(_delete)
        connection.send_result(msg["id"], {"success": True})
    except Exception as err:
        connection.send_error(msg["id"], "ftp_error", str(err))


# ── ftp_rename ─────────────────────────────────────────────────────────────────

@websocket_api.websocket_command(
    {
        vol.Required("type"):      "ps4_goldhen/ftp_rename",
        vol.Required("entry_id"):  str,
        vol.Required("from_path"): str,
        vol.Required("to_path"):   str,
    }
)
@websocket_api.async_response
async def ws_ftp_rename(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    data = _get_entry_data(hass, msg["entry_id"])
    if not data:
        connection.send_error(msg["id"], "not_found", "Entry not found")
        return

    def _rename():
        with _ftp_connect(data["host"], data["ftp_port"]) as ftp:
            ftp.rename(msg["from_path"], msg["to_path"])

    try:
        await hass.async_add_executor_job(_rename)
        connection.send_result(msg["id"], {"success": True})
    except Exception as err:
        connection.send_error(msg["id"], "ftp_error", str(err))


# ── ftp_get_text ───────────────────────────────────────────────────────────────

@websocket_api.websocket_command(
    {
        vol.Required("type"):     "ps4_goldhen/ftp_get_text",
        vol.Required("entry_id"): str,
        vol.Required("path"):     str,
    }
)
@websocket_api.async_response
async def ws_ftp_get_text(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    data = _get_entry_data(hass, msg["entry_id"])
    if not data:
        connection.send_error(msg["id"], "not_found", "Entry not found")
        return

    def _get():
        buf = io.BytesIO()
        with _ftp_connect(data["host"], data["ftp_port"]) as ftp:
            ftp.retrbinary(f"RETR {msg['path']}", buf.write)
        return buf.getvalue().decode("utf-8", errors="replace")

    try:
        content = await hass.async_add_executor_job(_get)
        connection.send_result(msg["id"], {"content": content})
    except Exception as err:
        connection.send_error(msg["id"], "ftp_error", str(err))


# ── ftp_put_text ───────────────────────────────────────────────────────────────

@websocket_api.websocket_command(
    {
        vol.Required("type"):     "ps4_goldhen/ftp_put_text",
        vol.Required("entry_id"): str,
        vol.Required("path"):     str,
        vol.Required("content"):  str,
    }
)
@websocket_api.async_response
async def ws_ftp_put_text(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    data = _get_entry_data(hass, msg["entry_id"])
    if not data:
        connection.send_error(msg["id"], "not_found", "Entry not found")
        return

    def _put():
        buf = io.BytesIO(msg["content"].encode("utf-8"))
        with _ftp_connect(data["host"], data["ftp_port"]) as ftp:
            ftp.storbinary(f"STOR {msg['path']}", buf)

    try:
        await hass.async_add_executor_job(_put)
        connection.send_result(msg["id"], {"success": True})
    except Exception as err:
        connection.send_error(msg["id"], "ftp_error", str(err))


# ── get_klog_history ───────────────────────────────────────────────────────────

@websocket_api.websocket_command(
    {
        vol.Required("type"):     "ps4_goldhen/get_klog_history",
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
    data = _get_entry_data(hass, msg["entry_id"])
    if not data:
        connection.send_error(msg["id"], "not_found", "Entry not found")
        return
    sm = data.get("klog_state_machine")
    if not sm:
        connection.send_result(msg["id"], {"lines": [], "total": 0, "klog_connected": False})
        return
    limit = max(1, min(msg.get("limit", 100), 250))
    lines = list(sm.recent_lines)[-limit:]
    connection.send_result(msg["id"], {
        "lines":         lines,
        "total":         len(sm.recent_lines),
        "klog_connected": sm.klog_connected,
    })


# ── subscribe_klog ─────────────────────────────────────────────────────────────

@websocket_api.websocket_command(
    {
        vol.Required("type"):     "ps4_goldhen/subscribe_klog",
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
    def _forward(event) -> None:
        if event.data.get("entry_id") != entry_id:
            return
        connection.send_event(msg["id"], {
            "message":  event.data.get("message"),
            "title_id": event.data.get("title_id"),
        })

    connection.subscriptions[msg["id"]] = hass.bus.async_listen(EVENT_KLOG_LINE, _forward)
    connection.send_result(msg["id"], {"subscribed": True})


# ── async_setup ────────────────────────────────────────────────────────────────

def async_setup(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_list_entries)
    websocket_api.async_register_command(hass, ws_list_payloads)
    websocket_api.async_register_command(hass, ws_ftp_list_dir)
    websocket_api.async_register_command(hass, ws_ftp_delete)
    websocket_api.async_register_command(hass, ws_ftp_rename)
    websocket_api.async_register_command(hass, ws_ftp_get_text)
    websocket_api.async_register_command(hass, ws_ftp_put_text)
    websocket_api.async_register_command(hass, ws_get_klog_history)
    websocket_api.async_register_command(hass, ws_subscribe_klog)
