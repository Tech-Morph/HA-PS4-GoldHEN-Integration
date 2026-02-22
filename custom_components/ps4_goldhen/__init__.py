"""The PS4 GoldHEN Integration."""
from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import secrets
import time
from datetime import timedelta
from typing import Any

from aiohttp import ClientError, ClientTimeout, web
import voluptuous as vol

from homeassistant.components import frontend, panel_custom, websocket_api
from homeassistant.components.frontend import StaticPathConfig
from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    DOMAIN,
    PLATFORMS,
    CONF_PS4_HOST,
    CONF_BINLOADER_PORT,
    CONF_FTP_PORT,
    CONF_RPI_PORT,
    DEFAULT_BINLOADER_PORT,
    DEFAULT_FTP_PORT,
    DEFAULT_RPI_PORT,
    PAYLOAD_DIR,
    TCP_PROBE_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)

# How often we poll FTP reachability for the sensor
_FTP_POLL_INTERVAL = timedelta(seconds=30)

# Service names
_SVC_SEND_PAYLOAD = "send_payload"
_SVC_INSTALL_PKG = "install_pkg"

# GLOBAL panel (single sidebar item)
_PANEL_URL_PATH = "ps4_goldhen"
_PANEL_SIDEBAR_TITLE = "PS4 GoldHEN"
_PANEL_SIDEBAR_ICON = "mdi:playstation"
_PANEL_WEBCOMPONENT = "ps4-goldhen-panel"

# Frontend JS static path (served by HA)
_JS_STATIC_URL = "/api/ps4_goldhen/frontend/ps4-goldhen-panel.js"
# Module URL can include a cache-busting query string
_JS_MODULE_URL = "/api/ps4_goldhen/frontend/ps4-goldhen-panel.js?v=0.7.3"

# RPI installer constants
_RPI_TMP_DIR = "ps4_goldhen_rpi_tmp"
_RPI_TOKEN_TTL_SECONDS = 3 * 60 * 60  # 3 hours
_RPI_MAX_UPLOAD_BYTES = int(110 * 1024 * 1024 * 1024)  # ~110 GiB

# Authenticated upload endpoint (kept for API/automation use if needed)
_RPI_UPLOAD_INSTALL_URL = "/api/ps4_goldhen/rpi/upload_install"

# Tokenized upload (fixes 401 from panel POST uploads)
_RPI_UPLOAD_TOKEN_TTL_SECONDS = 5 * 60  # 5 minutes
_RPI_UPLOAD_TOKENS_KEY = "rpi_upload_tokens"  # token -> {"entry_id": str, "expires": float}
_RPI_UPLOAD_INSTALL_TOKEN_URL = "/api/ps4_goldhen/rpi/upload_install/{token}"


def _now() -> float:
    return time.time()


def _ensure_domain_root(hass: HomeAssistant) -> dict[str, Any]:
    hass.data.setdefault(DOMAIN, {})
    root: dict[str, Any] = hass.data[DOMAIN]
    root.setdefault("_global", {})
    g: dict[str, Any] = root["_global"]
    g.setdefault("panel_registered", False)
    g.setdefault("frontend_registered", False)
    g.setdefault("ws_registered", False)
    g.setdefault("rpi_tokens", {})  # token -> {"path": str, "filename": str, "expires": float}
    g.setdefault(_RPI_UPLOAD_TOKENS_KEY, {})  # token -> {"entry_id": str, "expires": float}
    g.setdefault("rpi_cleanup_task", None)
    return root


def _global(hass: HomeAssistant) -> dict[str, Any]:
    root = _ensure_domain_root(hass)
    return root["_global"]


def _safe_filename(name: str) -> str:
    name = os.path.basename(name or "")
    if not name:
        raise HomeAssistantError("Invalid filename.")
    return name


def _is_private_remote(request: web.Request) -> bool:
    try:
        import ipaddress

        remote = request.remote
        if not remote:
            return False
        ip = ipaddress.ip_address(remote)
        return bool(ip.is_private)
    except Exception:  # noqa: BLE001
        return False


async def _send_bin_tcp(host: str, port: int, filepath: str, timeout: float = 30.0) -> None:
    """Stream a local .bin/.elf file to host:port over a raw TCP connection."""
    if not os.path.isfile(filepath):
        raise HomeAssistantError(f"Payload file not found: {filepath}")

    file_size = os.path.getsize(filepath)
    _LOGGER.info(
        "Sending payload %s (%d bytes) to %s:%d",
        os.path.basename(filepath),
        file_size,
        host,
        port,
    )

    try:
        _reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
    except (asyncio.TimeoutError, OSError) as err:
        raise HomeAssistantError(f"Cannot reach BinLoader at {host}:{port}: {err}") from err

    try:
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(None, lambda: open(filepath, "rb").read())
        writer.write(data)
        await asyncio.wait_for(writer.drain(), timeout=timeout)
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass

    _LOGGER.info("Payload sent successfully.")


async def _ps4_rpi_install(hass: HomeAssistant, ps4_host: str, ps4_port: int, pkg_url: str) -> dict[str, Any]:
    """
    Call the PS4 Remote Package Installer endpoint on port 12800.

    Common API:
      POST http://<ps4>:<port>/api/install
      Body: {"type":"direct","packages":["http://.../file.pkg"]}
    """
    session = async_get_clientsession(hass)
    endpoint = f"http://{ps4_host}:{ps4_port}/api/install"
    payload = {"type": "direct", "packages": [pkg_url]}

    _LOGGER.info("RPI install: POST %s (pkg=%s)", endpoint, pkg_url)

    # Some builds are slow to respond; also keep connect timeout short.
    timeout = ClientTimeout(total=180, connect=5, sock_connect=5, sock_read=180)

    try:
        # Send raw JSON body for maximum compatibility with simple servers.
        body = json.dumps(payload)
        async with session.post(
            endpoint,
            data=body,
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        ) as resp:
            text = await resp.text()
            if resp.status >= 400:
                raise HomeAssistantError(f"PS4 installer error {resp.status}: {text}")
            try:
                data = await resp.json()
            except Exception:  # noqa: BLE001
                data = {"status": "ok", "raw": text}
            return data
    except asyncio.TimeoutError as err:
        raise HomeAssistantError(f"Timeout talking to PS4 installer at {ps4_host}:{ps4_port}") from err
    except ClientError as err:
        raise HomeAssistantError(f"Cannot reach PS4 installer at {ps4_host}:{ps4_port}: {err}") from err


async def _register_frontend_and_panel_once(hass: HomeAssistant) -> None:
    g = _global(hass)

    if not g["frontend_registered"]:
        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(
                    _JS_STATIC_URL,
                    hass.config.path(f"custom_components/{DOMAIN}/frontend/ps4-goldhen-panel.js"),
                    False,
                )
            ]
        )
        g["frontend_registered"] = True
        _LOGGER.debug("Registered static JS path: %s", _JS_STATIC_URL)

    if not g["panel_registered"]:
        await panel_custom.async_register_panel(
            hass,
            frontend_url_path=_PANEL_URL_PATH,
            webcomponent_name=_PANEL_WEBCOMPONENT,
            module_url=_JS_MODULE_URL,
            sidebar_title=_PANEL_SIDEBAR_TITLE,
            sidebar_icon=_PANEL_SIDEBAR_ICON,
            config={},  # global selector in UI
            require_admin=False,
        )
        g["panel_registered"] = True
        _LOGGER.info("Registered global panel: %s", _PANEL_URL_PATH)

    if g["rpi_cleanup_task"] is None:
        g["rpi_cleanup_task"] = hass.loop.create_task(_rpi_cleanup_loop(hass))


async def _rpi_cleanup_loop(hass: HomeAssistant) -> None:
    while True:
        try:
            await asyncio.sleep(60)
            g = _global(hass)

            # Expire PKG download tokens (PS4 pulls these)
            tokens: dict[str, Any] = g["rpi_tokens"]
            now = _now()
            expired = [t for t, info in tokens.items() if info.get("expires", 0) <= now]
            for token in expired:
                info = tokens.pop(token, None)
                if not info:
                    continue
                path = info.get("path")
                if path and os.path.isfile(path):
                    try:
                        os.remove(path)
                        _LOGGER.info("Deleted expired PKG temp file: %s", path)
                    except OSError:
                        _LOGGER.warning("Failed to delete expired temp file: %s", path)

            # Expire upload tokens (panel uses these)
            up = g[_RPI_UPLOAD_TOKENS_KEY]
            expired_up = [t for t, info in up.items() if info.get("expires", 0) <= now]
            for token in expired_up:
                up.pop(token, None)

        except asyncio.CancelledError:
            return
        except Exception:  # noqa: BLE001
            _LOGGER.exception("RPI cleanup loop error")


@websocket_api.websocket_command({vol.Required("type"): "ps4_goldhen/list_entries"})
@websocket_api.async_response
async def ws_list_entries(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    entries = hass.config_entries.async_entries(DOMAIN)
    out: list[dict[str, Any]] = []
    for entry in entries:
        host = entry.data.get(CONF_PS4_HOST, "")
        out.append(
            {
                "entry_id": entry.entry_id,
                "title": entry.title,
                "ps4_host": host,
                "ftp_port": entry.data.get(CONF_FTP_PORT, DEFAULT_FTP_PORT),
                "binloader_port": entry.data.get(CONF_BINLOADER_PORT, DEFAULT_BINLOADER_PORT),
                "rpi_port": entry.data.get(CONF_RPI_PORT, DEFAULT_RPI_PORT),
            }
        )
    connection.send_result(msg["id"], {"entries": out})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "ps4_goldhen/rpi_install_url",
        vol.Required("entry_id"): str,
        vol.Required("url"): str,
        vol.Optional("port"): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
    }
)
@websocket_api.async_response
async def ws_rpi_install_url(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    entry_id = msg["entry_id"]
    url = msg["url"]
    override_port = msg.get("port")

    root = _ensure_domain_root(hass)
    data = root.get(entry_id)
    if not data:
        connection.send_error(msg["id"], "not_found", "Entry not found")
        return

    ps4_host = data["host"]
    ps4_port = int(override_port or data.get("rpi_port", DEFAULT_RPI_PORT))

    try:
        result = await _ps4_rpi_install(hass, ps4_host, ps4_port, url)
        connection.send_result(msg["id"], {"success": True, "result": result})
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "install_error", str(err))
    except Exception as err:  # noqa: BLE001
        connection.send_error(msg["id"], "unknown_error", str(err))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "ps4_goldhen/rpi_begin_upload",
        vol.Required("entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_rpi_begin_upload(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    entry_id = msg["entry_id"]
    root = _ensure_domain_root(hass)
    if entry_id not in root:
        connection.send_error(msg["id"], "not_found", "Entry not found")
        return

    token = secrets.token_urlsafe(24)
    g = _global(hass)
    g[_RPI_UPLOAD_TOKENS_KEY][token] = {"entry_id": entry_id, "expires": _now() + _RPI_UPLOAD_TOKEN_TTL_SECONDS}
    connection.send_result(msg["id"], {"token": token})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up PS4 GoldHEN integration from a config entry."""
    host = entry.data[CONF_PS4_HOST]
    binloader_port = entry.data.get(CONF_BINLOADER_PORT, DEFAULT_BINLOADER_PORT)
    ftp_port = entry.data.get(CONF_FTP_PORT, DEFAULT_FTP_PORT)
    rpi_port = entry.data.get(CONF_RPI_PORT, DEFAULT_RPI_PORT)

    async def _poll_ftp() -> dict[str, Any]:
        try:
            _reader, writer = await asyncio.wait_for(asyncio.open_connection(host, ftp_port), timeout=TCP_PROBE_TIMEOUT)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass
            return {"ftp_reachable": True}
        except Exception:  # noqa: BLE001
            return {"ftp_reachable": False}

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"{DOMAIN}_{host}",
        update_method=_poll_ftp,
        update_interval=_FTP_POLL_INTERVAL,
    )
    await coordinator.async_config_entry_first_refresh()

    # IMPORTANT: websocket.py expects hass.data[DOMAIN][entry_id] to exist.
    root = _ensure_domain_root(hass)
    root[entry.entry_id] = {
        "coordinator": coordinator,
        "host": host,
        "binloader_port": binloader_port,
        "ftp_port": ftp_port,
        "rpi_port": rpi_port,
    }

    # Register WS commands once
    g = _global(hass)
    if not g["ws_registered"]:
        websocket_api.async_register_command(hass, ws_list_entries)
        websocket_api.async_register_command(hass, ws_rpi_install_url)
        websocket_api.async_register_command(hass, ws_rpi_begin_upload)
        g["ws_registered"] = True

    # Panel + static JS once
    await _register_frontend_and_panel_once(hass)

    # ── Services (kept for automations; not used by global panel buttons) ───────
    _SEND_PAYLOAD_SCHEMA = vol.Schema(
        {
            vol.Required("payload_file"): str,
            vol.Optional("ps4_host"): str,
            vol.Optional("binloader_port"): vol.All(vol.Coerce(int), vol.Range(min=1024, max=65535)),
            vol.Optional("timeout", default=30): vol.All(vol.Coerce(float), vol.Range(min=1)),
        }
    )

    _INSTALL_PKG_SCHEMA = vol.Schema(
        {
            vol.Required("url"): str,
            vol.Optional("ps4_host"): str,
            vol.Optional("port"): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
        }
    )

    async def handle_send_payload(call: ServiceCall) -> None:
        p_file = call.data["payload_file"]
        t_host = call.data.get("ps4_host") or host
        t_port = int(call.data.get("binloader_port") or binloader_port)
        timeout = float(call.data.get("timeout", 30))

        filepath = p_file if os.path.isabs(p_file) else os.path.join(PAYLOAD_DIR, p_file)
        await _send_bin_tcp(t_host, t_port, filepath, timeout)

    async def handle_install_pkg(call: ServiceCall) -> None:
        url = call.data["url"]
        t_host = call.data.get("ps4_host") or host
        t_port = int(call.data.get("port") or rpi_port)
        await _ps4_rpi_install(hass, t_host, t_port, url)

    if not hass.services.has_service(DOMAIN, _SVC_SEND_PAYLOAD):
        hass.services.async_register(DOMAIN, _SVC_SEND_PAYLOAD, handle_send_payload, schema=_SEND_PAYLOAD_SCHEMA)

    if not hass.services.has_service(DOMAIN, _SVC_INSTALL_PKG):
        hass.services.async_register(DOMAIN, _SVC_INSTALL_PKG, handle_install_pkg, schema=_INSTALL_PKG_SCHEMA)

    # ── Existing FTP WebSocket API ──────────────────────────────────────────────
    from .websocket import async_setup as async_setup_websocket

    async_setup_websocket(hass)

    # Existing FTP Views
    hass.http.register_view(PS4FTPDownloadView())
    hass.http.register_view(PS4FTPUploadView())

    # RPI upload/install + token download
    hass.http.register_view(PS4RpiUploadInstallView())
    hass.http.register_view(PS4RpiUploadInstallTokenView())
    hass.http.register_view(PS4RpiPkgDownloadView())

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


class PS4RpiUploadInstallView(HomeAssistantView):
    """Authenticated view: upload a local .pkg and start install via PS4 RPI (port 12800)."""

    url = _RPI_UPLOAD_INSTALL_URL
    name = "api:ps4_goldhen:rpi_upload_install"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]

        try:
            request._client_max_size = _RPI_MAX_UPLOAD_BYTES  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass

        reader = await request.multipart()

        entry_id: str | None = None
        port: int | None = None
        uploaded_filename: str | None = None

        file_part = None
        while True:
            part = await reader.next()
            if part is None:
                break

            if part.name == "entry_id":
                entry_id = (await part.read(decode=True)).decode(errors="ignore").strip()
            elif part.name == "port":
                raw = (await part.read(decode=True)).decode(errors="ignore").strip()
                if raw:
                    port = int(raw)
            elif part.name == "file":
                file_part = part
                uploaded_filename = _safe_filename(part.filename or "upload.pkg")
                break

        if not entry_id or file_part is None or not uploaded_filename:
            return web.json_response({"success": False, "error": "Missing entry_id or file"}, status=400)

        root = _ensure_domain_root(hass)
        entry_data = root.get(entry_id)
        if not entry_data:
            return web.json_response({"success": False, "error": "Entry not found"}, status=404)

        ps4_host = entry_data["host"]
        ps4_port = int(port or entry_data.get("rpi_port", DEFAULT_RPI_PORT))

        tmp_dir = hass.config.path(_RPI_TMP_DIR)
        os.makedirs(tmp_dir, exist_ok=True)

        token = secrets.token_urlsafe(24)
        tmp_path = os.path.join(tmp_dir, f"{token}__{uploaded_filename}")

        size = 0
        try:
            with open(tmp_path, "wb") as fp:
                while True:
                    chunk = await file_part.read_chunk(size=1024 * 1024)
                    if not chunk:
                        break
                    fp.write(chunk)
                    size += len(chunk)

            g = _global(hass)
            g["rpi_tokens"][token] = {
                "path": tmp_path,
                "filename": uploaded_filename,
                "expires": _now() + _RPI_TOKEN_TTL_SECONDS,
            }

            # Force HTTP for PS4 compatibility (avoid HTTPS / cert issues).
            base = f"http://{request.host}"
            download_url = f"{base}/api/ps4_goldhen/rpi/pkg/{token}/{uploaded_filename}"

            install_result = await _ps4_rpi_install(hass, ps4_host, ps4_port, download_url)

            return web.json_response(
                {
                    "success": True,
                    "entry_id": entry_id,
                    "ps4_host": ps4_host,
                    "ps4_port": ps4_port,
                    "filename": uploaded_filename,
                    "bytes_received": size,
                    "download_url": download_url,
                    "install_result": install_result,
                    "note": "Temp file will be auto-deleted after token expiry.",
                }
            )
        except HomeAssistantError as err:
            return web.json_response({"success": False, "error": str(err)}, status=500)
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("Upload/install failed")
            return web.json_response({"success": False, "error": str(err)}, status=500)


class PS4RpiUploadInstallTokenView(HomeAssistantView):
    """Unauthenticated upload endpoint secured by short-lived token + LAN-only remote IP."""

    url = _RPI_UPLOAD_INSTALL_TOKEN_URL
    name = "api:ps4_goldhen:rpi_upload_install_token"
    requires_auth = False

    async def post(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]

        if not _is_private_remote(request):
            return web.json_response({"success": False, "error": "Forbidden"}, status=403)

        token = request.match_info.get("token", "")
        g = _global(hass)
        token_info = g[_RPI_UPLOAD_TOKENS_KEY].get(token)
        if not token_info or token_info.get("expires", 0) <= _now():
            g[_RPI_UPLOAD_TOKENS_KEY].pop(token, None)
            return web.json_response({"success": False, "error": "Token expired"}, status=410)

        entry_id = token_info["entry_id"]
        # One-shot token
        g[_RPI_UPLOAD_TOKENS_KEY].pop(token, None)

        try:
            request._client_max_size = _RPI_MAX_UPLOAD_BYTES  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass

        reader = await request.multipart()

        port: int | None = None
        uploaded_filename: str | None = None
        file_part = None

        while True:
            part = await reader.next()
            if part is None:
                break
            if part.name == "port":
                raw = (await part.read(decode=True)).decode(errors="ignore").strip()
                if raw:
                    port = int(raw)
            elif part.name == "file":
                file_part = part
                uploaded_filename = _safe_filename(part.filename or "upload.pkg")
                break

        if file_part is None or not uploaded_filename:
            return web.json_response({"success": False, "error": "Missing file"}, status=400)

        root = _ensure_domain_root(hass)
        entry_data = root.get(entry_id)
        if not entry_data:
            return web.json_response({"success": False, "error": "Entry not found"}, status=404)

        ps4_host = entry_data["host"]
        ps4_port = int(port or entry_data.get("rpi_port", DEFAULT_RPI_PORT))

        tmp_dir = hass.config.path(_RPI_TMP_DIR)
        os.makedirs(tmp_dir, exist_ok=True)

        pkg_token = secrets.token_urlsafe(24)
        tmp_path = os.path.join(tmp_dir, f"{pkg_token}__{uploaded_filename}")

        size = 0
        try:
            with open(tmp_path, "wb") as fp:
                while True:
                    chunk = await file_part.read_chunk(size=1024 * 1024)
                    if not chunk:
                        break
                    fp.write(chunk)
                    size += len(chunk)

            g2 = _global(hass)
            g2["rpi_tokens"][pkg_token] = {
                "path": tmp_path,
                "filename": uploaded_filename,
                "expires": _now() + _RPI_TOKEN_TTL_SECONDS,
            }

            base = f"http://{request.host}"
            download_url = f"{base}/api/ps4_goldhen/rpi/pkg/{pkg_token}/{uploaded_filename}"

            install_result = await _ps4_rpi_install(hass, ps4_host, ps4_port, download_url)

            return web.json_response(
                {
                    "success": True,
                    "entry_id": entry_id,
                    "ps4_host": ps4_host,
                    "ps4_port": ps4_port,
                    "filename": uploaded_filename,
                    "bytes_received": size,
                    "download_url": download_url,
                    "install_result": install_result,
                }
            )
        except HomeAssistantError as err:
            return web.json_response({"success": False, "error": str(err)}, status=500)
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("Token upload/install failed")
            return web.json_response({"success": False, "error": str(err)}, status=500)


class PS4RpiPkgDownloadView(HomeAssistantView):
    """Unauthenticated download for the PS4 (LAN-only + tokenized)."""

    url = "/api/ps4_goldhen/rpi/pkg/{token}/{filename}"
    name = "api:ps4_goldhen:rpi_pkg_download"
    requires_auth = False

    async def get(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        if not _is_private_remote(request):
            return web.Response(text="Forbidden", status=403)

        token = request.match_info.get("token", "")
        filename = request.match_info.get("filename", "")

        g = _global(hass)
        info = g["rpi_tokens"].get(token)
        if not info:
            return web.Response(text="Not found", status=404)

        if info.get("expires", 0) <= _now():
            g["rpi_tokens"].pop(token, None)
            path = info.get("path")
            if path and os.path.isfile(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
            return web.Response(text="Expired", status=410)

        if _safe_filename(filename) != info.get("filename"):
            return web.Response(text="Not found", status=404)

        path = info.get("path")
        if not path or not os.path.isfile(path):
            return web.Response(text="Not found", status=404)

        resp = web.FileResponse(path)
        resp.headers["Content-Disposition"] = f'attachment; filename="{info.get("filename")}"'
        return resp


class PS4FTPDownloadView(HomeAssistantView):
    """View to download/view files from PS4 via FTP."""

    url = "/api/ps4_goldhen/ftp/download"
    name = "api:ps4_goldhen:ftp_download"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        import ftplib

        hass = request.app["hass"]
        entry_id = request.query.get("entry_id")
        path = request.query.get("path")

        if not entry_id or not path:
            return web.Response(text="Missing entry_id or path", status=400)

        root = _ensure_domain_root(hass)
        data = root.get(entry_id)
        if not data:
            return web.Response(text="Entry not found", status=404)

        host = data["host"]
        port = int(data.get("ftp_port", DEFAULT_FTP_PORT))

        def _get_file() -> bytes:
            buffer = io.BytesIO()
            with ftplib.FTP() as ftp:
                ftp.connect(host, port, timeout=15)
                ftp.login()
                ftp.retrbinary(f"RETR {path}", buffer.write)
                buffer.seek(0)
                return buffer.read()

        try:
            content = await hass.async_add_executor_job(_get_file)
            filename = os.path.basename(path)
            return web.Response(
                body=content,
                content_type="application/octet-stream",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
        except Exception as err:
            return web.Response(text=f"FTP Error: {err}", status=500)


class PS4FTPUploadView(HomeAssistantView):
    """View to upload files to PS4 via FTP."""

    url = "/api/ps4_goldhen/ftp/upload"
    name = "api:ps4_goldhen:ftp_upload"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        import ftplib

        hass = request.app["hass"]

        reader = await request.multipart()
        entry_id = None
        path = None
        file_field = None

        while True:
            part = await reader.next()
            if part is None:
                break
            if part.name == "entry_id":
                entry_id = (await part.read(decode=True)).decode()
            elif part.name == "path":
                path = (await part.read(decode=True)).decode()
            elif part.name == "file":
                file_field = part
                break

        if not all([entry_id, path, file_field]):
            return web.Response(text="Missing entry_id, path, or file", status=400)

        root = _ensure_domain_root(hass)
        data = root.get(entry_id)
        if not data:
            return web.Response(text="Entry not found", status=404)

        host = data["host"]
        port = int(data.get("ftp_port", DEFAULT_FTP_PORT))
        filename = file_field.filename
        full_dest_path = (path.rstrip("/") + "/" + filename).replace("//", "/")

        def _upload_file(file_data: bytes) -> None:
            with ftplib.FTP() as ftp:
                ftp.connect(host, port, timeout=15)
                ftp.login()
                ftp.storbinary(f"STOR {full_dest_path}", io.BytesIO(file_data))

        try:
            content = await file_field.read(decode=True)
            await hass.async_add_executor_job(_upload_file, content)
            return web.json_response({"success": True, "path": full_dest_path})
        except Exception as err:
            return web.Response(text=f"FTP Upload Error: {err}", status=500)


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    root = _ensure_domain_root(hass)
    root.pop(entry.entry_id, None)

    remaining = [k for k in root.keys() if k != "_global"]
    if not remaining:
        hass.services.async_remove(DOMAIN, _SVC_SEND_PAYLOAD)
        hass.services.async_remove(DOMAIN, _SVC_INSTALL_PKG)

        try:
            frontend.async_remove_panel(hass, _PANEL_URL_PATH)
        except Exception:  # noqa: BLE001
            pass

        g = _global(hass)
        task = g.get("rpi_cleanup_task")
        if task:
            task.cancel()

        hass.data.pop(DOMAIN, None)

    return True
