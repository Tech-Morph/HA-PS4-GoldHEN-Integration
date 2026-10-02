"""WebSocket API handlers for PS4 GoldHEN FTP file browser + Klog stream."""
from __future__ import annotations

import asyncio
import ftplib
import io
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN, DEFAULT_FTP_PORT, EVENT_KLOG_STREAM
from .ftp_listing import list_directory

# FTP timeout for all operations (seconds)
_FTP_TIMEOUT = 15

# GoldHEN Klog server default port (documented in GoldHEN changelog)
DEFAULT_KLOG_PORT = 3232


def _ftp_list_dir(host: str, port: int, path: str) -> list[dict[str, Any]]:
    """Blocking: return a structured directory listing via FTP."""
    with ftplib.FTP() as ftp:
        ftp.connect(host, port, timeout=_FTP_TIMEOUT)
        ftp.login()
        return list_directory(ftp, path)



def _ftp_delete(host: str, port: int, path: str, is_dir: bool) -> None:
    """Blocking: delete a file or empty directory via FTP."""
    with ftplib.FTP() as ftp:
        ftp.connect(host, port, timeout=_FTP_TIMEOUT)
        ftp.login()
        if is_dir:
            ftp.rmd(path)
        else:
            ftp.delete(path)


def _ftp_rename(host: str, port: int, from_path: str, to_path: str) -> None:
    """Blocking: rename/move a file or directory via FTP."""
    with ftplib.FTP() as ftp:
        ftp.connect(host, port, timeout=_FTP_TIMEOUT)
        ftp.login()
        ftp.rename(from_path, to_path)


def _ftp_mkdir(host: str, port: int, path: str) -> None:
    """Blocking: create a directory via FTP."""
    with ftplib.FTP() as ftp:
        ftp.connect(host, port, timeout=_FTP_TIMEOUT)
        ftp.login()
        ftp.mkd(path)


def _ftp_get_text(host: str, port: int, path: str) -> str:
    """Blocking: download a file and return as string."""
    buffer = io.BytesIO()
    with ftplib.FTP() as ftp:
        ftp.connect(host, port, timeout=_FTP_TIMEOUT)
        ftp.login()
        ftp.retrbinary(f"RETR {path}", buffer.write)
    buffer.seek(0)
    return buffer.read().decode("utf-8", errors="replace")


def _ftp_put_text(host: str, port: int, path: str, content: str) -> None:
    """Blocking: upload string content to a file."""
    buffer = io.BytesIO(content.encode("utf-8"))
    with ftplib.FTP() as ftp:
        ftp.connect(host, port, timeout=_FTP_TIMEOUT)
        ftp.login()
        ftp.storbinary(f"STOR {path}", buffer)


def _safe_int(s: str) -> int:
    try:
        return int(s)
    except (ValueError, TypeError):
        return 0


@callback
def async_setup(hass: HomeAssistant) -> None:
    """Register all WebSocket commands for the integration."""
    # FTP
    websocket_api.async_register_command(hass, ws_list_dir)
    websocket_api.async_register_command(hass, ws_delete)
    websocket_api.async_register_command(hass, ws_rename)
    websocket_api.async_register_command(hass, ws_mkdir)
    websocket_api.async_register_command(hass, ws_get_text)
    websocket_api.async_register_command(hass, ws_put_text)

    # Klog
    websocket_api.async_register_command(hass, ws_klog_subscribe)


# ── list directory ────────────────────────────────────────────────────────────
@websocket_api.websocket_command(
    {
        vol.Required("type"): "ps4_goldhen/ftp_list_dir",
        vol.Required("entry_id"): str,
        vol.Optional("path", default="/"): str,
    }
)
@websocket_api.async_response
async def ws_list_dir(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """List a directory on the PS4 via FTP."""
    entry_id = msg["entry_id"]
    path = msg["path"] or "/"
    host, port = _get_ftp_params(hass, entry_id)
    try:
        loop = asyncio.get_running_loop()
        entries = await loop.run_in_executor(None, _ftp_list_dir, host, port, path)
        connection.send_result(msg["id"], {"path": path, "entries": entries})
    except ftplib.all_errors as err:
        connection.send_error(msg["id"], "ftp_error", str(err))
    except Exception as err:  # noqa: BLE001
        connection.send_error(msg["id"], "unknown_error", str(err))


# ── delete ────────────────────────────────────────────────────────────────────
@websocket_api.websocket_command(
    {
        vol.Required("type"): "ps4_goldhen/ftp_delete",
        vol.Required("entry_id"): str,
        vol.Required("path"): str,
        vol.Required("is_dir"): bool,
    }
)
@websocket_api.async_response
async def ws_delete(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete a file or empty directory on the PS4 via FTP."""
    host, port = _get_ftp_params(hass, msg["entry_id"])
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _ftp_delete, host, port, msg["path"], msg["is_dir"])
        connection.send_result(msg["id"], {"success": True})
    except ftplib.all_errors as err:
        connection.send_error(msg["id"], "ftp_error", str(err))
    except Exception as err:  # noqa: BLE001
        connection.send_error(msg["id"], "unknown_error", str(err))


# ── rename ────────────────────────────────────────────────────────────────────
@websocket_api.websocket_command(
    {
        vol.Required("type"): "ps4_goldhen/ftp_rename",
        vol.Required("entry_id"): str,
        vol.Required("from_path"): str,
        vol.Required("to_path"): str,
    }
)
@websocket_api.async_response
async def ws_rename(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Rename a file or directory on the PS4 via FTP."""
    host, port = _get_ftp_params(hass, msg["entry_id"])
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _ftp_rename, host, port, msg["from_path"], msg["to_path"])
        connection.send_result(msg["id"], {"success": True})
    except ftplib.all_errors as err:
        connection.send_error(msg["id"], "ftp_error", str(err))
    except Exception as err:  # noqa: BLE001
        connection.send_error(msg["id"], "unknown_error", str(err))


# ── mkdir ─────────────────────────────────────────────────────────────────────
@websocket_api.websocket_command(
    {
        vol.Required("type"): "ps4_goldhen/ftp_mkdir",
        vol.Required("entry_id"): str,
        vol.Required("path"): str,
    }
)
@websocket_api.async_response
async def ws_mkdir(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Create a directory on the PS4 via FTP."""
    host, port = _get_ftp_params(hass, msg["entry_id"])
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _ftp_mkdir, host, port, msg["path"])
        connection.send_result(msg["id"], {"success": True})
    except ftplib.all_errors as err:
        connection.send_error(msg["id"], "ftp_error", str(err))
    except Exception as err:  # noqa: BLE001
        connection.send_error(msg["id"], "unknown_error", str(err))


# ── get text content (Edit) ───────────────────────────────────────────────────
@websocket_api.websocket_command(
    {
        vol.Required("type"): "ps4_goldhen/ftp_get_text",
        vol.Required("entry_id"): str,
        vol.Required("path"): str,
    }
)
@websocket_api.async_response
async def ws_get_text(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Read content of a text file via FTP."""
    host, port = _get_ftp_params(hass, msg["entry_id"])
    try:
        loop = asyncio.get_running_loop()
        content = await loop.run_in_executor(None, _ftp_get_text, host, port, msg["path"])
        connection.send_result(msg["id"], {"content": content})
    except ftplib.all_errors as err:
        connection.send_error(msg["id"], "ftp_error", str(err))
    except Exception as err:  # noqa: BLE001
        connection.send_error(msg["id"], "unknown_error", str(err))


# ── put text content (Save) ───────────────────────────────────────────────────
@websocket_api.websocket_command(
    {
        vol.Required("type"): "ps4_goldhen/ftp_put_text",
        vol.Required("entry_id"): str,
        vol.Required("path"): str,
        vol.Required("content"): str,
    }
)
@websocket_api.async_response
async def ws_put_text(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Save content to a text file via FTP."""
    host, port = _get_ftp_params(hass, msg["entry_id"])
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _ftp_put_text, host, port, msg["path"], msg["content"])
        connection.send_result(msg["id"], {"success": True})
    except ftplib.all_errors as err:
        connection.send_error(msg["id"], "ftp_error", str(err))
    except Exception as err:  # noqa: BLE001
        connection.send_error(msg["id"], "unknown_error", str(err))


# ── Klog stream subscription ──────────────────────────────────────────────────
@websocket_api.websocket_command(
    {
        vol.Required("type"): "ps4_goldhen/klog_subscribe",
        vol.Required("entry_id"): str,
        # Accepted for older cached frontends; TCP port is entry-owned.
        vol.Optional("port"): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
    }
)
@websocket_api.async_response
async def ws_klog_subscribe(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Forward lines from the entry-owned klog listener to one UI subscriber."""
    entry_id = msg["entry_id"]
    entry_data = hass.data.get(DOMAIN, {}).get(entry_id)
    if not entry_data:
        connection.send_error(msg["id"], "not_found", "Entry not found")
        return

    @callback
    def _forward(event) -> None:
        data = event.data
        if data.get("entry_id") != entry_id:
            return
        line = data.get("message")
        if not isinstance(line, str):
            return
        connection.send_message(
            {
                "id": msg["id"],
                "type": "event",
                "event": {
                    "line": line,
                    "time": event.time_fired.isoformat(),
                },
            }
        )

    connection.subscriptions[msg["id"]] = hass.bus.async_listen(
        EVENT_KLOG_STREAM, _forward
    )
    connection.send_result(
        msg["id"],
        {
            "subscribed": True,
            "klog_connected": bool(
                entry_data.get("klog_data", {}).get("klog_connected", False)
            ),
        },
    )


# ── helpers ───────────────────────────────────────────────────────────────────
def _get_ftp_params(hass: HomeAssistant, entry_id: str) -> tuple[str, int]:
    """Pull host + FTP port from stored entry data."""
    data = hass.data[DOMAIN][entry_id]
    return data["host"], int(data.get("ftp_port", DEFAULT_FTP_PORT))
