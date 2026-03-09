"""The PS4 GoldHEN Integration."""
from __future__ import annotations

import asyncio
import contextlib
import ftplib
import io
import json
import logging
import os
import re
import shutil
import sqlite3
import tempfile
import time
from collections import deque
from datetime import timedelta
from functools import partial
from pathlib import Path
from typing import Any

from aiohttp import web
import voluptuous as vol

from homeassistant.components import frontend, panel_custom, websocket_api
from homeassistant.components.frontend import StaticPathConfig
from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    DOMAIN,
    PLATFORMS,
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
    SENSOR_CURRENT_GAME,
    SENSOR_CPU_TEMP,
)

_LOGGER = logging.getLogger(__name__)

_FTP_POLL_INTERVAL = timedelta(seconds=30)
_TITLES_REFRESH_INTERVAL = timedelta(hours=6)

_SVC_SEND_PAYLOAD = "send_payload"
_SVC_REFRESH_TITLES = "refresh_titles"

_PANEL_URL_PATH = "ps4_goldhen"
_PANEL_SIDEBAR_TITLE = "PS4 GoldHEN"
_PANEL_SIDEBAR_ICON = "mdi:sony-playstation"
_PANEL_WEBCOMPONENT = "ps4-goldhen-panel"

_JS_STATIC_URL = "/api/ps4_goldhen/frontend/ps4-goldhen-panel.js"
_JS_MODULE_URL = f"{_JS_STATIC_URL}?v=1.0.0"

_HOME_SCREEN_STATE = "PlayStation Home Screen"
_HOME_SCREEN_APP_ID = "NPXS20001"
_TITLE_ID_RE = re.compile(r"[A-Z]{4}\d{5}")

# ── Klog Patterns ───────────────────────────────────────────────────────────
_KLOG_SL_FOCUS_PATTERN = re.compile(r"\[SL\]\s+AppFocusChanged\s+\[([A-Z0-9]+)\]\s*->\s*\[([A-Z0-9]+)\]", re.IGNORECASE)
_KLOG_CPU_TEMP_PATTERN = re.compile(r"CPU.*?(\d+\.?\d*)\s*[°C]", re.IGNORECASE)

_KLOG_NOISE_PATTERNS = (
    re.compile(r"\bD88391\b", re.IGNORECASE),
    re.compile(r"uhub\d+: giving up port", re.IGNORECASE),
)

def _ensure_domain_root(hass: HomeAssistant) -> dict[str, Any]:
    hass.data.setdefault(DOMAIN, {})
    root = hass.data[DOMAIN]
    root.setdefault("_global", {"panel_registered": False, "frontend_registered": False, "ws_registered": False, "services_registered": False, "views_registered": False})
    return root

def _global(hass: HomeAssistant) -> dict[str, Any]:
    return _ensure_domain_root(hass)["_global"]

class KlogStateMachine:
    def __init__(self) -> None:
        self.current_title_id: str | None = None
        self.klog_connected: bool = True

    def snapshot(self) -> dict[str, Any]:
        state = self.current_title_id if self.current_title_id else _HOME_SCREEN_STATE
        return {SENSOR_CURRENT_GAME: state, "title_id": self.current_title_id, "klog_connected": self.klog_connected}

    def ingest(self, line: str) -> bool:
        for pattern in _KLOG_NOISE_PATTERNS:
            if pattern.search(line): return False
        
        m = _KLOG_SL_FOCUS_PATTERN.search(line)
        if m:
            new_app = m.group(2).strip().upper()
            changed = self.current_title_id != (None if new_app == _HOME_SCREEN_APP_ID else new_app)
            self.current_title_id = None if new_app == _HOME_SCREEN_APP_ID else new_app
            return changed
        return False

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    root = _ensure_domain_root(hass)
    
    # Extract data using the keys from your const.py
    host = entry.data[CONF_PS4_HOST]
    klog_port = entry.data.get(CONF_KLOG_PORT, DEFAULT_KLOG_PORT)
    
    klog_state_machine = KlogStateMachine()
    coordinator = DataUpdateCoordinator(hass, _LOGGER, name=f"{DOMAIN}_{entry.entry_id}", update_interval=_FTP_POLL_INTERVAL)
    
    entry_data = {
        "host": host,
        "binloader_port": entry.data.get(CONF_BINLOADER_PORT, DEFAULT_BINLOADER_PORT),
        "ftp_port": entry.data.get(CONF_FTP_PORT, DEFAULT_FTP_PORT),
        "klog_state_machine": klog_state_machine,
        "klog_data": {**klog_state_machine.snapshot(), SENSOR_CPU_TEMP: None},
        "coordinator": coordinator
    }
    root[entry.entry_id] = entry_data

    await _register_frontend_and_panel_once(hass)
    _register_websocket_handlers_once(hass)
    _register_http_views_once(hass)
    _register_services_once(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    entry_data["klog_task"] = hass.loop.create_task(_klog_listener_task(hass, entry.entry_id, host, klog_port, coordinator))
    return True

async def _klog_listener_task(hass: HomeAssistant, entry_id: str, host: str, port: int, coordinator: DataUpdateCoordinator) -> None:
    while True:
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=10)
            entry_data = hass.data[DOMAIN].get(entry_id)
            if not entry_data: break
            
            entry_data["klog_state_machine"].klog_connected = True
            text_buffer = ""
            while True:
                chunk = await reader.read(4096)
                if not chunk: break
                text_buffer += chunk.decode("utf-8", errors="replace")
                lines = text_buffer.split("\n")
                text_buffer = lines[-1]
                
                changed = False
                for line in lines[:-1]:
                    if _parse_klog_line(line, entry_data): changed = True
                
                if changed: 
                    coordinator.async_set_updated_data({**entry_data["klog_data"]})
            
            writer.close()
            await writer.wait_closed()
        except Exception as err:
            _LOGGER.debug("Klog connection lost: %s", err)
        
        await asyncio.sleep(10)

def _parse_klog_line(line: str, entry_data: dict[str, Any]) -> bool:
    state_machine = entry_data["klog_state_machine"]
    changed = state_machine.ingest(line)
    
    klog_data = entry_data["klog_data"]
    klog_data.update(state_machine.snapshot())
    
    m = _KLOG_CPU_TEMP_PATTERN.search(line)
    if m:
        with contextlib.suppress(ValueError):
            klog_data[SENSOR_CPU_TEMP] = float(m.group(1))
            changed = True
    return changed


async def _klog_listener_task(hass: HomeAssistant, entry_id: str, host: str, port: int, coordinator: DataUpdateCoordinator) -> None:
    while True:
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=10)
            entry_data = hass.data[DOMAIN].get(entry_id)
            if entry_data: entry_data["klog_state_machine"].klog_connected = True
            text_buffer = ""
            while True:
                try: chunk = await asyncio.wait_for(reader.read(4096), timeout=30.0)
                except asyncio.TimeoutError: continue
                if not chunk: break
                text_buffer += chunk.decode("utf-8", errors="replace")
                lines = text_buffer.split("\n")
                text_buffer = lines[-1]
                entry_data = hass.data[DOMAIN].get(entry_id)
                if not entry_data: break
                changed = False
                for line in lines[:-1]:
                    line = line.rstrip("\r")
                    if line and _parse_klog_line(line, entry_data): changed = True
                if changed: coordinator.async_set_updated_data({**(coordinator.data or {}), **entry_data["klog_data"]})
            writer.close()
            await writer.wait_closed()
        except asyncio.CancelledError: raise
        except Exception as err: _LOGGER.warning("Klog error: %s", err)
        entry_data = hass.data[DOMAIN].get(entry_id)
        if entry_data:
            entry_data["klog_state_machine"].klog_connected = False
            entry_data["klog_data"]["klog_connected"] = False
            coordinator.async_set_updated_data({**(coordinator.data or {}), **entry_data["klog_data"]})
        await asyncio.sleep(10)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    root = _ensure_domain_root(hass)
    g = root["_global"]
    host = entry.data[CONF_PS4_HOST]
    binloader_port = entry.data.get(CONF_BINLOADER_PORT, DEFAULT_BINLOADER_PORT)
    ftp_port = entry.data.get(CONF_FTP_PORT, DEFAULT_FTP_PORT)
    rpi_port = entry.data.get(CONF_RPI_PORT, DEFAULT_RPI_PORT)
    klog_port = entry.data.get(CONF_KLOG_PORT, DEFAULT_KLOG_PORT)
    titles_file = hass.config.path(f"{DOMAIN}_{entry.entry_id}_titles.json")
    persisted_title_map = await hass.async_add_executor_job(_load_title_map_blocking, titles_file)
    klog_state_machine = KlogStateMachine()
    klog_data = {**klog_state_machine.snapshot(), SENSOR_CPU_TEMP: None}
    coordinator = DataUpdateCoordinator(hass, _LOGGER, name=f"{DOMAIN}_{entry.entry_id}", update_interval=_FTP_POLL_INTERVAL)
    entry_data = {"host": host, "binloader_port": binloader_port, "ftp_port": ftp_port, "rpi_port": rpi_port, "klog_port": klog_port, "titles_file": titles_file, "title_map": persisted_title_map, "title_map_updated_at": 0, "klog_state_machine": klog_state_machine, "klog_data": klog_data, "coordinator": coordinator}
    root[entry.entry_id] = entry_data
    if not g["bundled_payloads_installed"]:
        copied = await hass.async_add_executor_job(_copy_bundled_payloads_to_config)
        g["bundled_payloads_installed"] = True
    await _register_frontend_and_panel_once(hass)
    _register_websocket_handlers_once(hass)
    _register_http_views_once(hass)
    coordinator.async_set_updated_data({**klog_data, "ftp_reachable": False})
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _register_services_once(hass)
    entry_data["klog_task"] = hass.loop.create_task(_klog_listener_task(hass, entry.entry_id, host, klog_port, coordinator))
    entry_data["titles_task"] = hass.loop.create_task(_titles_refresh_task(hass, entry.entry_id, coordinator))
    entry_data["ftp_task"] = hass.loop.create_task(_ftp_poll_task(hass, entry.entry_id, coordinator))
    return True


async def _ftp_poll_task(hass: HomeAssistant, entry_id: str, coordinator: DataUpdateCoordinator) -> None:
    while True:
        await asyncio.sleep(_FTP_POLL_INTERVAL.total_seconds())
        entry_data = hass.data[DOMAIN].get(entry_id)
        if not entry_data: return
        reachable = False
        try:
            with ftplib.FTP() as ftp:
                ftp.connect(entry_data["host"], int(entry_data["ftp_port"]), timeout=5)
                ftp.login()
                reachable = True
        except Exception: pass
        coordinator.async_set_updated_data({**(coordinator.data or {}), **entry_data["klog_data"], "ftp_reachable": reachable})


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    entry_data = hass.data[DOMAIN].get(entry.entry_id, {})
    for task_key in ("klog_task", "titles_task", "ftp_task"):
        task = entry_data.get(task_key)
        if task and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError): await task
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok: hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


def _register_services_once(hass: HomeAssistant) -> None:
    g = _global(hass)
    if g["services_registered"]: return
    g["services_registered"] = True

    async def handle_send_payload(call: ServiceCall) -> None:
        entry_id = call.data.get("entry_id")
        filename = call.data.get("filename")
        if not filename: raise HomeAssistantError("filename is required")
        target_eid = entry_id or next((eid for eid in hass.data[DOMAIN] if not eid.startswith("_")), None)
        if not target_eid: raise HomeAssistantError("No PS4 entry found")
        edata = hass.data[DOMAIN][target_eid]
        filepath = os.path.join(PAYLOAD_DIR, filename)
        if not os.path.isfile(filepath): raise HomeAssistantError(f"File not found: {filepath}")
        await _send_bin_tcp(edata["host"], edata["binloader_port"], filepath)

    async def handle_refresh_titles(call: ServiceCall) -> None:
        entry_id = call.data.get("entry_id")
        target_eid = entry_id or next((eid for eid in hass.data[DOMAIN] if not eid.startswith("_")), None)
        if not target_eid: raise HomeAssistantError("No PS4 entry found")
        await _refresh_titles_cache(hass, target_eid, hass.data[DOMAIN][target_eid]["coordinator"])

    hass.services.async_register(DOMAIN, _SVC_SEND_PAYLOAD, handle_send_payload, schema=vol.Schema({vol.Optional("entry_id"): str, vol.Required("filename"): str}))
    hass.services.async_register(DOMAIN, _SVC_REFRESH_TITLES, handle_refresh_titles, schema=vol.Schema({vol.Optional("entry_id"): str}))


def _register_http_views_once(hass: HomeAssistant) -> None:
    g = _global(hass)
    if g["views_registered"]: return
    g["views_registered"] = True

    class PayloadListView(HomeAssistantView):
        url, name, requires_auth = "/api/ps4_goldhen/payloads", "api:ps4_goldhen:payloads", True
        async def get(self, request):
            items = await hass.async_add_executor_job(_list_payloads_blocking, PAYLOAD_DIR)
            return web.Response(text=json.dumps(items), content_type="application/json")

    class PayloadUploadView(HomeAssistantView):
        url, name, requires_auth = "/api/ps4_goldhen/payloads/upload", "api:ps4_goldhen:payloads:upload", True
        async def post(self, request):
            reader = await request.multipart()
            field = await reader.next()
            if not field or field.name != "file": return web.Response(status=400, text="Expected file")
            safe_name = os.path.basename(field.filename or "unknown.bin")
            if not (safe_name.lower().endswith((".bin", ".elf"))): return web.Response(status=400, text="Invalid extension")
            os.makedirs(PAYLOAD_DIR, exist_ok=True)
            dest = os.path.join(PAYLOAD_DIR, safe_name)
            with open(dest, "wb") as f:
                while True:
                    chunk = await field.read_chunk()
                    if not chunk: break
                    f.write(chunk)
            return web.Response(text=json.dumps({"ok": True, "filename": safe_name}), content_type="application/json")

    class TitleMapView(HomeAssistantView):
        url, name, requires_auth = "/api/ps4_goldhen/titles", "api:ps4_goldhen:titles", True
        async def get(self, request):
            merged = {}
            for eid, edata in hass.data[DOMAIN].items():
                if not eid.startswith("_") and isinstance(edata, dict):
                    merged.update(edata.get("title_map", {}))
            return web.Response(text=json.dumps(merged, ensure_ascii=False), content_type="application/json")

    hass.http.register_view(PayloadListView())
    hass.http.register_view(PayloadUploadView())
    hass.http.register_view(TitleMapView())


def _register_websocket_handlers_once(hass: HomeAssistant) -> None:
    g = _global(hass)
    if g["ws_registered"]: return
    g["ws_registered"] = True

    @websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/state"})
    @websocket_api.async_response
    async def ws_state(hass, connection, msg):
        res = {eid: {"klog_data": ed.get("klog_data", {}), "coordinator_data": ed["coordinator"].data, "title_map_count": len(ed.get("title_map", {}))} for eid, ed in hass.data[DOMAIN].items() if not eid.startswith("_")}
        connection.send_result(msg["id"], res)

    @websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/payloads"})
    @websocket_api.async_response
    async def ws_payloads(hass, connection, msg):
        items = await hass.async_add_executor_job(_list_payloads_blocking, PAYLOAD_DIR)
        connection.send_result(msg["id"], {"payloads": items})

    @websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/send_payload", vol.Required("filename"): str, vol.Optional("entry_id"): str})
    @websocket_api.async_response
    async def ws_send_payload(hass, connection, msg):
        filename, target_eid = msg["filename"], msg.get("entry_id") or next((eid for eid in hass.data[DOMAIN] if not eid.startswith("_")), None)
        if not target_eid or target_eid not in hass.data[DOMAIN]: return connection.send_error(msg["id"], "not_found", "No PS4 found")
        filepath = os.path.join(PAYLOAD_DIR, filename)
        if not os.path.isfile(filepath): return connection.send_error(msg["id"], "not_found", "Payload missing")
        try:
            await _send_bin_tcp(hass.data[DOMAIN][target_eid]["host"], hass.data[DOMAIN][target_eid]["binloader_port"], filepath)
            connection.send_result(msg["id"], {"ok": True})
        except HomeAssistantError as err: connection.send_error(msg["id"], "send_failed", str(err))

    websocket_api.async_register_command(hass, ws_state)
    websocket_api.async_register_command(hass, ws_payloads)
    websocket_api.async_register_command(hass, ws_send_payload)
