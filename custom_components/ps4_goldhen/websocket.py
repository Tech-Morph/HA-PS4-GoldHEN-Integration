"""WebSocket API handlers for PS4 GoldHEN FTP file browser."""
from __future__ import annotations

import asyncio
import ftplib
import io
import os
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN, CONF_PS4_HOST, CONF_FTP_PORT, DEFAULT_FTP_PORT

# FTP timeout for all operations (seconds)
_FTP_TIMEOUT = 15

def _ftp_list_dir(host: str, port: int, path: str) -> list[dict[str, Any]]:
    """Blocking: list a directory via FTP. Returns list of entry dicts."""
    entries: list[dict[str, Any]] = []
    with ftplib.FTP() as ftp:
        ftp.connect(host, port, timeout=_FTP_TIMEOUT)
        ftp.login()  # GoldHEN FTP is unauthenticated
        ftp.cwd(path)
        raw: list[str] = []
        ftp.retrlines("LIST", raw.append)
        for line in raw:
            parts = line.split(None, 8)
            if len(parts) < 9:
                continue
            name = parts[8]
            if name in (".", ".."):
                continue
            is_dir = line.startswith("d")
            size = 0 if is_dir else _safe_int(parts[4])
            entries.append(
                {
                    "name": name,
                    "path": path.rstrip("/") + "/" + name,
                    "is_dir": is_dir,
                    "size": size,
                    "modified": " ".join(parts[5:8]),
                    "permissions": parts[0],
                }
            )
    entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))
    return entries

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
    """Register all WebSocket commands for the FTP file browser."""
    websocket_api.async_register_command(hass, ws_list_dir)
    websocket_api.async_register_command(hass, ws_delete)
    websocket_api.async_register_command(hass, ws_rename)
    websocket_api.async_register_command(hass, ws_mkdir)
    websocket_api.async_register_command(hass, ws_get_text)
    websocket_api.async_register_command(hass, ws_put_text)

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
        entries = await loop.run_in_executor(
            None, _ftp_list_dir, host, port, path
        )
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
        await loop.run_in_executor(
            None, _ftp_delete, host, port, msg["path"], msg["is_dir"]
        )
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
        await loop.run_in_executor(
            None, _ftp_rename, host, port, msg["from_path"], msg["to_path"]
        )
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
        await loop.run_in_executor(
            None, _ftp_mkdir, host, port, msg["path"]
        )
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
        content = await loop.run_in_executor(
            None, _ftp_get_text, host, port, msg["path"]
        )
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
        await loop.run_in_executor(
            None, _ftp_put_text, host, port, msg["path"], msg["content"]
        )
        connection.send_result(msg["id"], {"success": True})
    except ftplib.all_errors as err:
        connection.send_error(msg["id"], "ftp_error", str(err))
    except Exception as err:  # noqa: BLE001
        connection.send_error(msg["id"], "unknown_error", str(err))

# ── helpers ───────────────────────────────────────────────────────────────────
def _get_ftp_params(hass: HomeAssistant, entry_id: str) -> tuple[str, int]:
    """Pull host + FTP port from stored entry data."""
    data = hass.data[DOMAIN][entry_id]
    return data["host"], int(data["ftp_port"])
