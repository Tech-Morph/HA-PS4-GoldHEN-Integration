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
    TCP_PROBE_TIMEOUT,
    SENSOR_CURRENT_GAME,
    SENSOR_CPU_TEMP,
    SENSOR_RSX_TEMP,
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
_LOGO_STATIC_URL = "/api/ps4_goldhen/frontend/goldhen_logo.png"
_PAYLOAD_ICONS_STATIC_URL = "/api/ps4_goldhen/frontend/payload_icons"

_BUNDLED_PAYLOADS_DIRNAME = "bundled_payloads"

_HOME_SCREEN_STATE = "PlayStation Home Screen"
_IDLE_STATE = "Idle"
_HOME_SCREEN_APP_ID = "NPXS20001"

_TITLE_ID_RE = re.compile(r"[A-Z]{4}\d{5}")

# ── Primary signals ────────────────────────────────────────────────────────────
# "[SL] AppFocusChanged [OLD] -> [NEW]"  (the [SL] logger is ground truth)
_KLOG_SL_FOCUS_PATTERN = re.compile(
    r"\[SL\]\s+AppFocusChanged\s+\[([A-Z0-9]+)\]\s*->\s*\[([A-Z0-9]+)\]",
    re.IGNORECASE,
)

# launchApp from SceLncService — fires before focus, good early signal
_KLOG_LNC_LAUNCH_PATTERN = re.compile(
    r"\[SceLncService\]\s+launchApp\(([A-Z]{4}\d{5})\)",
    re.IGNORECASE,
)

# Game fully started (BGFT fires after binary is loaded)
_KLOG_BGFT_GAME_START = re.compile(
    r"\[BGFT\].*GameWillStart\(([A-Z]{4}\d{5}),",
    re.IGNORECASE,
)

# Game closed — fires when user quits the app
_KLOG_GAME_CLOSE_PATTERN = re.compile(r"Game Close detected", re.IGNORECASE)
_KLOG_BGFT_GAME_STOPPED = re.compile(
    r"\[BGFT\].*GameStopped\(([A-Z]{4}\d{5}),",
    re.IGNORECASE,
)

# Back to home after app exit:
# "[SceShellUI] OnFocusActiveSceneChanged [ApplicationExitScene : ApplicationExitScene] -> [ContentAreaScene : ContentAreaScene]"
_KLOG_EXIT_TO_HOME_PATTERN = re.compile(
    r"OnFocusActiveSceneChanged\s+\[ApplicationExitScene\s*:\s*ApplicationExitScene\]\s*->\s*\[ContentAreaScene\s*:\s*ContentAreaScene\]",
    re.IGNORECASE,
)

# ── Noise filter ───────────────────────────────────────────────────────────────
_KLOG_NOISE_PATTERNS = (
    re.compile(r"\bD88391\b", re.IGNORECASE),
    re.compile(r"\bfrom tbl_appbrowse_", re.IGNORECASE),
    re.compile(r"\bfrom tblappbrowse", re.IGNORECASE),
    re.compile(r"^\s*<\d+>\s*=+ bindValue", re.IGNORECASE),
    re.compile(r"^\s*<\d+>\s*=+ sql\s*=", re.IGNORECASE),
    re.compile(r"^\s*======== sql\s*=", re.IGNORECASE),
    re.compile(r"^\s*======== bindValue", re.IGNORECASE),
    re.compile(r"^\s*======== limit\s*=", re.IGNORECASE),
    re.compile(r"uhub\d+: giving up port", re.IGNORECASE),
)

_KLOG_CPU_TEMP_PATTERN = re.compile(r"CPU.*?(\d+\.?\d*)\s*[°C]", re.IGNORECASE)
_KLOG_RSX_TEMP_PATTERN = re.compile(r"(?:RSX|GPU).*?(\d+\.?\d*)\s*[°C]", re.IGNORECASE)

_APP_DB_CANDIDATES = (
    "/system_data/priv/mms/app.db",
    "/system_data/priv/mms/app.db.bak",
)


def _ensure_domain_root(hass: HomeAssistant) -> dict[str, Any]:
    hass.data.setdefault(DOMAIN, {})
    root: dict[str, Any] = hass.data[DOMAIN]
    root.setdefault("_global", {})
    g: dict[str, Any] = root["_global"]
    g.setdefault("panel_registered", False)
    g.setdefault("frontend_registered", False)
    g.setdefault("ws_registered", False)
    g.setdefault("bundled_payloads_installed", False)
    g.setdefault("services_registered", False)
    g.setdefault("views_registered", False)
    return root


def _global(hass: HomeAssistant) -> dict[str, Any]:
    root = _ensure_domain_root(hass)
    return root["_global"]


def _titles_file_path(hass: HomeAssistant) -> str:
    return hass.config.path(f"{DOMAIN}_titles.json")


def _copy_bundled_payloads_to_config() -> int:
    src_dir = Path(__file__).parent / _BUNDLED_PAYLOADS_DIRNAME
    dst_dir = Path(PAYLOAD_DIR)

    if not src_dir.exists() or not src_dir.is_dir():
        return 0

    dst_dir.mkdir(parents=True, exist_ok=True)
    copied = 0

    for p in sorted(src_dir.iterdir()):
        if not p.is_file() or p.suffix.lower() not in (".bin", ".elf"):
            continue
        dst = dst_dir / p.name
        if dst.exists():
            continue
        shutil.copy2(str(p), str(dst))
        copied += 1

    return copied


def _list_payloads_blocking(payload_dir: str) -> list[str]:
    p = Path(payload_dir)
    p.mkdir(parents=True, exist_ok=True)
    items: list[str] = []
    hidden = {"linux.bin"}

    for entry in sorted(p.iterdir(), key=lambda e: e.name):
        name = entry.name
        if name.lower() in hidden:
            continue
        if entry.is_file() and (name.lower().endswith(".bin") or name.lower().endswith(".elf")):
            items.append(name)

    return items


def _normalize_title_id(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip().upper()
    if _TITLE_ID_RE.fullmatch(value):
        return value
    return None


def _normalize_title_map(raw_map: Any) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}

    if not isinstance(raw_map, dict):
        return out

    for key, value in raw_map.items():
        title_id = _normalize_title_id(str(key))
        if not title_id:
            continue

        if isinstance(value, str):
            name = value.strip()
            if not name:
                continue
            out[title_id] = {"name": name, "source": "manual"}
            continue

        if not isinstance(value, dict):
            continue

        name = str(value.get("name", "")).strip()
        if not name:
            continue

        item = dict(value)
        item["name"] = name
        item["source"] = str(item.get("source", "manual")).strip() or "manual"
        out[title_id] = item

    return out


def _load_title_map_blocking(file_path: str) -> dict[str, dict[str, Any]]:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as err:
        _LOGGER.warning("Unable to read title map %s: %s", file_path, err)
        return {}

    return _normalize_title_map(raw)


def _save_title_map_blocking(file_path: str, title_map: dict[str, dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(title_map.items())), f, indent=2, ensure_ascii=False)


def _merge_title_maps(
    discovered: dict[str, dict[str, Any]],
    persisted: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    merged = dict(discovered)

    for title_id, item in persisted.items():
        existing = merged.get(title_id, {})
        merged[title_id] = {**existing, **item}

    return dict(sorted(merged.items()))


def _ftp_read_file(ftp: ftplib.FTP, remote_path: str) -> bytes:
    buffer = io.BytesIO()
    ftp.retrbinary(f"RETR {remote_path}", buffer.write)
    return buffer.getvalue()


def _download_app_db_bytes(host: str, port: int) -> tuple[str, bytes]:
    last_error: Exception | None = None

    with ftplib.FTP() as ftp:
        ftp.connect(host, int(port), timeout=20)
        ftp.login()

        for candidate in _APP_DB_CANDIDATES:
            try:
                db_bytes = _ftp_read_file(ftp, candidate)
                if db_bytes:
                    return candidate, db_bytes
            except Exception as err:
                last_error = err

    if last_error:
        raise last_error

    raise FileNotFoundError("Unable to download app.db from PS4 FTP")


def _sqlite_escape_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _sqlite_table_columns(conn: sqlite3.Connection, table_name: str) -> dict[str, str]:
    escaped = _sqlite_escape_ident(table_name)
    rows = conn.execute(f"PRAGMA table_info({escaped})").fetchall()
    mapping: dict[str, str] = {}

    for row in rows:
        col_name = str(row[1])
        mapping[col_name.lower()] = col_name

    return mapping


def _list_appbrowse_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND (
            lower(name) LIKE 'tblappbrowse%'
            OR lower(name) LIKE 'tbl_appbrowse%'
          )
        ORDER BY name
        """
    ).fetchall()

    return [str(row[0]) for row in rows if row and row[0]]


def _build_select_for_appbrowse_table(table_name: str, columns: dict[str, str]) -> str | None:
    required = {"titleid", "titlename"}
    if not required.issubset(columns):
        return None

    aliases = {
        "titleid": "titleId",
        "titlename": "titleName",
        "metadatapath": "metaDataPath",
        "thumbnailurl": "thumbnailUrl",
        "hddlocation": "hddLocation",
        "externalhddappstatus": "externalHddAppStatus",
        "contentid": "contentId",
        "contenttype": "contentType",
        "category": "category",
        "pathinfo": "pathInfo",
        "visible": "visible",
    }

    select_parts: list[str] = []
    for key, alias in aliases.items():
        if key in columns:
            select_parts.append(f'{_sqlite_escape_ident(columns[key])} AS "{alias}"')

    if not select_parts:
        return None

    sql = f"SELECT {', '.join(select_parts)} FROM {_sqlite_escape_ident(table_name)}"

    if "visible" in columns:
        sql += f" WHERE {_sqlite_escape_ident(columns['visible'])} = 1"

    return sql


def _extract_title_map_from_app_db_bytes(db_bytes: bytes, db_path: str) -> dict[str, dict[str, Any]]:
    title_map: dict[str, dict[str, Any]] = {}
    temp_path = ""

    try:
        with tempfile.NamedTemporaryFile(prefix="ps4_goldhen_appdb_", suffix=".db", delete=False) as tmp:
            tmp.write(db_bytes)
            temp_path = tmp.name

        conn = sqlite3.connect(temp_path)
        try:
            conn.row_factory = sqlite3.Row

            tables = _list_appbrowse_tables(conn)
            _LOGGER.warning("PS4 app.db scan found %d app-browse tables", len(tables))

            total_rows = 0

            for table_name in tables:
                columns = _sqlite_table_columns(conn, table_name)
                query = _build_select_for_appbrowse_table(table_name, columns)

                if not query:
                    _LOGGER.debug("Skipping table %s because required columns were not found", table_name)
                    continue

                rows = conn.execute(query).fetchall()
                _LOGGER.warning("PS4 app.db table %s returned %d visible rows", table_name, len(rows))
                total_rows += len(rows)

                for row in rows:
                    title_id = _normalize_title_id(row["titleId"] if "titleId" in row.keys() else None)
                    title_name = str(row["titleName"]).strip() if "titleName" in row.keys() and row["titleName"] is not None else ""

                    if not title_id or not title_name:
                        continue

                    item: dict[str, Any] = {
                        "name": title_name,
                        "source": "ps4_app_db",
                        "db_path": db_path,
                        "db_table": table_name,
                        "last_seen": int(time.time()),
                    }

                    for key in (
                        "metaDataPath",
                        "thumbnailUrl",
                        "hddLocation",
                        "externalHddAppStatus",
                        "contentId",
                        "contentType",
                        "category",
                        "pathInfo",
                    ):
                        if key in row.keys() and row[key] is not None:
                            item[key] = row[key]

                    existing = title_map.get(title_id)
                    if existing:
                        if existing.get("source") != "manual":
                            title_map[title_id] = {**existing, **item}
                    else:
                        title_map[title_id] = item

            _LOGGER.warning("PS4 app.db scan processed %d rows total", total_rows)
        finally:
            conn.close()
    finally:
        if temp_path:
            with contextlib.suppress(Exception):
                os.unlink(temp_path)

    _LOGGER.warning("PS4 app.db scan resolved %d titles with names", len(title_map))
    return title_map


def _build_title_map_from_ps4(host: str, port: int) -> dict[str, dict[str, Any]]:
    db_path, db_bytes = _download_app_db_bytes(host, port)
    _LOGGER.warning("Downloaded PS4 app.db from %s (%d bytes)", db_path, len(db_bytes))
    return _extract_title_map_from_app_db_bytes(db_bytes, db_path)


async def _refresh_titles_cache(
    hass: HomeAssistant,
    entry_id: str,
    coordinator: DataUpdateCoordinator,
) -> None:
    entry_data = hass.data[DOMAIN].get(entry_id)
    if not entry_data:
        return

    file_path = entry_data["titles_file"]
    persisted = await hass.async_add_executor_job(_load_title_map_blocking, file_path)
    _LOGGER.warning("Persisted title map count before refresh: %d", len(persisted))

    discovered: dict[str, dict[str, Any]] = {}
    try:
        discovered = await hass.async_add_executor_job(
            _build_title_map_from_ps4,
            entry_data["host"],
            entry_data["ftp_port"],
        )
    except Exception as err:
        _LOGGER.warning("Failed refreshing title map from PS4 %s: %s", entry_data["host"], err)

    _LOGGER.warning("Discovered title map count from PS4: %d", len(discovered))

    merged = _merge_title_maps(discovered, persisted)
    await hass.async_add_executor_job(_save_title_map_blocking, file_path, merged)

    entry_data["title_map"] = merged
    entry_data["title_map_updated_at"] = int(time.time())

    coordinator.async_set_updated_data(
        {
            **(coordinator.data or {}),
            **entry_data["klog_data"],
            "title_map_updated_at": entry_data["title_map_updated_at"],
        }
    )


async def _titles_refresh_task(
    hass: HomeAssistant,
    entry_id: str,
    coordinator: DataUpdateCoordinator,
) -> None:
    while True:
        try:
            await _refresh_titles_cache(hass, entry_id, coordinator)
        except asyncio.CancelledError:
            _LOGGER.info("Title refresh task cancelled")
            raise
        except Exception as err:
            _LOGGER.warning("Title refresh task error for %s: %s", entry_id, err)

        await asyncio.sleep(_TITLES_REFRESH_INTERVAL.total_seconds())


async def _register_frontend_and_panel_once(hass: HomeAssistant) -> None:
    g = _global(hass)

    if not g["frontend_registered"]:
        payload_icons_dir = hass.config.path(f"custom_components/{DOMAIN}/frontend/payload_icons")
        await hass.async_add_executor_job(partial(os.makedirs, payload_icons_dir, exist_ok=True))

        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(
                    _JS_STATIC_URL,
                    hass.config.path(f"custom_components/{DOMAIN}/frontend/ps4-goldhen-panel.js"),
                    False,
                ),
                StaticPathConfig(
                    _LOGO_STATIC_URL,
                    hass.config.path(f"custom_components/{DOMAIN}/frontend/goldhen_logo.png"),
                    False,
                ),
                StaticPathConfig(_PAYLOAD_ICONS_STATIC_URL, payload_icons_dir, False),
            ]
        )
        g["frontend_registered"] = True

    if not g["panel_registered"]:
        await panel_custom.async_register_panel(
            hass,
            frontend_url_path=_PANEL_URL_PATH,
            webcomponent_name=_PANEL_WEBCOMPONENT,
            module_url=_JS_MODULE_URL,
            sidebar_title=_PANEL_SIDEBAR_TITLE,
            sidebar_icon=_PANEL_SIDEBAR_ICON,
            config={},
            require_admin=False,
        )
        g["panel_registered"] = True


async def _send_bin_tcp(host: str, port: int, filepath: str, timeout: float = 30.0) -> None:
    loop = asyncio.get_running_loop()

    try:
        data = await loop.run_in_executor(None, lambda: open(filepath, "rb").read())
    except Exception as err:
        raise HomeAssistantError(f"Cannot read payload file {filepath}: {err}") from err

    _LOGGER.info("Sending payload %s to %s:%d", os.path.basename(filepath), host, port)

    try:
        _reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
        writer.write(data)
        await asyncio.wait_for(writer.drain(), timeout=timeout)
        writer.close()
        await writer.wait_closed()
        _LOGGER.info("Payload sent successfully.")
    except Exception as err:
        raise HomeAssistantError(f"Connection to PS4 BinLoader failed: {err}") from err


def _is_real_game_title_id(value: str | None) -> bool:
    if not value:
        return False
    value = value.strip().upper()
    return bool(_TITLE_ID_RE.fullmatch(value)) and not value.startswith("NPXS")


class KlogStateMachine:
    """
    Resolve the current PS4 foreground state from the klog stream.

    Signal priority (highest → lowest):
      1. [SL] AppFocusChanged [OLD] -> [NEW]   ← ground truth for foreground app
      2. [BGFT] GameWillStart(TITLEID, …)       ← game binary loaded & starting
      3. [SceLncService] launchApp(TITLEID)     ← early launch signal
      4. Game Close detected / GameStopped      ← game exited
      5. OnFocusActiveSceneChanged …Exit→Content← back to home after close
    """

    def __init__(self) -> None:
        self.current_title_id: str | None = None   # None = home screen
        self.last_reason = "init"
        self.last_signal_line = ""
        self.recent_lines: deque[str] = deque(maxlen=250)
        self.klog_connected: bool = True

        # Pending launch: we saw launchApp but not yet [SL] AppFocusChanged
        self._pending_launch: str | None = None

    # ── public API ─────────────────────────────────────────────────────────────

    def snapshot(self) -> dict[str, Any]:
        state = self.current_title_id if self.current_title_id else _HOME_SCREEN_STATE
        return {
            SENSOR_CURRENT_GAME: state,
            "title_id": self.current_title_id,
            "state_reason": self.last_reason,
            "state_signal_line": self.last_signal_line,
            "pending_title_id": self._pending_launch,
            "klog_connected": self.klog_connected,
        }

    def ingest(self, line: str) -> bool:
        """Process one klog line. Returns True if state changed."""
        self.recent_lines.append(line[-300:])
        self.klog_connected = True

        # Fast-path: skip noise
        for pattern in _KLOG_NOISE_PATTERNS:
            if pattern.search(line):
                return False

        # ── 1. [SL] AppFocusChanged — GROUND TRUTH ────────────────────────────
        m = _KLOG_SL_FOCUS_PATTERN.search(line)
        if m:
            new_app = m.group(2).strip().upper()
            if _is_real_game_title_id(new_app):
                # Focused on a real game
                return self._set(new_app, "sl_focus_game", line)
            elif new_app == _HOME_SCREEN_APP_ID:
                # Focused back on shell — only go home if we were in a game
                if self.current_title_id is not None:
                    return self._set(None, "sl_focus_home", line)
            return False

        # ── 2. [BGFT] GameWillStart — game binary is loaded ───────────────────
        m = _KLOG_BGFT_GAME_START.search(line)
        if m:
            tid = m.group(1).strip().upper()
            if _is_real_game_title_id(tid):
                self._pending_launch = tid
                # Commit immediately as a strong signal
                return self._set(tid, "bgft_game_will_start", line)

        # ── 3. [SceLncService] launchApp — early indicator ────────────────────
        m = _KLOG_LNC_LAUNCH_PATTERN.search(line)
        if m:
            tid = m.group(1).strip().upper()
            if _is_real_game_title_id(tid):
                self._pending_launch = tid
                # Don't commit yet — wait for [SL] AppFocusChanged or GameWillStart
                self.last_reason = "lnc_launch_pending"
                self.last_signal_line = line[-300:]
                return False

        # ── 4. Game closed ────────────────────────────────────────────────────
        if _KLOG_GAME_CLOSE_PATTERN.search(line):
            if self.current_title_id is not None:
                return self._set(None, "game_close_detected", line)

        m = _KLOG_BGFT_GAME_STOPPED.search(line)
        if m:
            tid = m.group(1).strip().upper()
            if self.current_title_id == tid:
                return self._set(None, "bgft_game_stopped", line)

        # ── 5. Exit scene → ContentArea = back to home screen ─────────────────
        if _KLOG_EXIT_TO_HOME_PATTERN.search(line):
            if self.current_title_id is not None:
                return self._set(None, "exit_scene_to_home", line)

        return False

    # ── internal ───────────────────────────────────────────────────────────────

    def _set(self, title_id: str | None, reason: str, line: str) -> bool:
        changed = self.current_title_id != title_id
        self.current_title_id = title_id
        self._pending_launch = None
        self.last_reason = reason
        self.last_signal_line = line[-300:]
        return changed


def _parse_klog_line(line: str, entry_data: dict[str, Any]) -> bool:
    state_machine: KlogStateMachine = entry_data["klog_state_machine"]
    state_changed = state_machine.ingest(line)

    klog_data = entry_data["klog_data"]
    klog_data.update(state_machine.snapshot())

    m = _KLOG_CPU_TEMP_PATTERN.search(line)
    if m:
        with contextlib.suppress(ValueError):
            klog_data[SENSOR_CPU_TEMP] = float(m.group(1))

    m = _KLOG_RSX_TEMP_PATTERN.search(line)
    if m:
        with contextlib.suppress(ValueError):
            klog_data[SENSOR_RSX_TEMP] = float(m.group(1))

    return state_changed


async def _klog_listener_task(
    hass: HomeAssistant,
    entry_id: str,
    host: str,
    port: int,
    coordinator: DataUpdateCoordinator,
) -> None:
    _LOGGER.info("Starting klog listener for %s:%d", host, port)

    while True:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=10
            )
            _LOGGER.info("Connected to klog at %s:%d", host, port)

            entry_data = hass.data[DOMAIN].get(entry_id)
            if entry_data:
                entry_data["klog_state_machine"].klog_connected = True

            text_buffer = ""

            while True:
                try:
                    chunk = await asyncio.wait_for(reader.read(4096), timeout=30.0)
                except asyncio.TimeoutError:
                    continue

                if not chunk:
                    _LOGGER.warning("Klog connection closed by PS4")
                    break

                text_buffer += chunk.decode("utf-8", errors="replace")
                lines = text_buffer.split("\n")
                text_buffer = lines[-1]

                entry_data = hass.data[DOMAIN].get(entry_id)
                if not entry_data:
                    break

                changed = False
                for line in lines[:-1]:
                    line = line.rstrip("\r")
                    if line:
                        if _parse_klog_line(line, entry_data):
                            changed = True

                if changed:
                    coordinator.async_set_updated_data(
                        {
                            **(coordinator.data or {}),
                            **entry_data["klog_data"],
                        }
                    )

            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

        except asyncio.CancelledError:
            _LOGGER.info("Klog listener task cancelled")
            raise
        except Exception as err:
            _LOGGER.warning("Klog connection error for %s:%d: %s", host, port, err)

        entry_data = hass.data[DOMAIN].get(entry_id)
        if entry_data:
            entry_data["klog_state_machine"].klog_connected = False
            entry_data["klog_data"]["klog_connected"] = False
            coordinator.async_set_updated_data(
                {
                    **(coordinator.data or {}),
                    **entry_data["klog_data"],
                }
            )

        _LOGGER.info("Reconnecting to klog in 10s...")
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

    persisted_title_map = await hass.async_add_executor_job(
        _load_title_map_blocking, titles_file
    )

    klog_state_machine = KlogStateMachine()
    klog_data: dict[str, Any] = {
        **klog_state_machine.snapshot(),
        SENSOR_CPU_TEMP: None,
        SENSOR_RSX_TEMP: None,
    }

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"{DOMAIN}_{entry.entry_id}",
        update_interval=_FTP_POLL_INTERVAL,
    )

    entry_data: dict[str, Any] = {
        "host": host,
        "binloader_port": binloader_port,
        "ftp_port": ftp_port,
        "rpi_port": rpi_port,
        "klog_port": klog_port,
        "titles_file": titles_file,
        "title_map": persisted_title_map,
        "title_map_updated_at": 0,
        "klog_state_machine": klog_state_machine,
        "klog_data": klog_data,
        "coordinator": coordinator,
    }
    root[entry.entry_id] = entry_data

    if not g["bundled_payloads_installed"]:
        copied = await hass.async_add_executor_job(_copy_bundled_payloads_to_config)
        if copied:
            _LOGGER.info("Installed %d bundled payloads to %s", copied, PAYLOAD_DIR)
        g["bundled_payloads_installed"] = True

    await _register_frontend_and_panel_once(hass)
    _register_websocket_handlers_once(hass)
    _register_http_views_once(hass)

    initial_data: dict[str, Any] = {
        **klog_data,
        "ftp_reachable": False,
    }
    coordinator.async_set_updated_data(initial_data)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _register_services_once(hass)

    klog_task = hass.loop.create_task(
        _klog_listener_task(hass, entry.entry_id, host, klog_port, coordinator)
    )
    titles_task = hass.loop.create_task(
        _titles_refresh_task(hass, entry.entry_id, coordinator)
    )
    ftp_task = hass.loop.create_task(
        _ftp_poll_task(hass, entry.entry_id, coordinator)
    )

    entry_data["klog_task"] = klog_task
    entry_data["titles_task"] = titles_task
    entry_data["ftp_task"] = ftp_task

    return True


async def _ftp_poll_task(
    hass: HomeAssistant,
    entry_id: str,
    coordinator: DataUpdateCoordinator,
) -> None:
    while True:
        await asyncio.sleep(_FTP_POLL_INTERVAL.total_seconds())

        entry_data = hass.data[DOMAIN].get(entry_id)
        if not entry_data:
            return

        host = entry_data["host"]
        ftp_port = entry_data["ftp_port"]

        reachable = False
        try:
            with ftplib.FTP() as ftp:
                ftp.connect(host, int(ftp_port), timeout=5)
                ftp.login()
                reachable = True
        except Exception:
            pass

        coordinator.async_set_updated_data(
            {
                **(coordinator.data or {}),
                **entry_data["klog_data"],
                "ftp_reachable": reachable,
            }
        )


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    entry_data = hass.data[DOMAIN].get(entry.entry_id, {})

    for task_key in ("klog_task", "titles_task", "ftp_task"):
        task = entry_data.get(task_key)
        if task and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok


def _register_services_once(hass: HomeAssistant) -> None:
    g = _global(hass)
    if g["services_registered"]:
        return
    g["services_registered"] = True

    async def handle_send_payload(call: ServiceCall) -> None:
        entry_id = call.data.get("entry_id")
        filename = call.data.get("filename")

        if not filename:
            raise HomeAssistantError("filename is required")

        target_entry_id = entry_id
        if not target_entry_id:
            for eid, edata in hass.data[DOMAIN].items():
                if eid.startswith("_"):
                    continue
                target_entry_id = eid
                break

        if not target_entry_id:
            raise HomeAssistantError("No PS4 GoldHEN integration entry found")

        entry_data = hass.data[DOMAIN].get(target_entry_id)
        if not entry_data:
            raise HomeAssistantError(f"Entry {target_entry_id} not found")

        filepath = os.path.join(PAYLOAD_DIR, filename)
        if not os.path.isfile(filepath):
            raise HomeAssistantError(f"Payload file not found: {filepath}")

        await _send_bin_tcp(
            entry_data["host"],
            entry_data["binloader_port"],
            filepath,
        )

    async def handle_refresh_titles(call: ServiceCall) -> None:
        entry_id = call.data.get("entry_id")

        target_entry_id = entry_id
        if not target_entry_id:
            for eid in hass.data[DOMAIN]:
                if not eid.startswith("_"):
                    target_entry_id = eid
                    break

        if not target_entry_id:
            raise HomeAssistantError("No PS4 GoldHEN integration entry found")

        entry_data = hass.data[DOMAIN].get(target_entry_id)
        if not entry_data:
            raise HomeAssistantError(f"Entry {target_entry_id} not found")

        coordinator = entry_data["coordinator"]
        await _refresh_titles_cache(hass, target_entry_id, coordinator)

    hass.services.async_register(
        DOMAIN,
        _SVC_SEND_PAYLOAD,
        handle_send_payload,
        schema=vol.Schema(
            {
                vol.Optional("entry_id"): str,
                vol.Required("filename"): str,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        _SVC_REFRESH_TITLES,
        handle_refresh_titles,
        schema=vol.Schema({vol.Optional("entry_id"): str}),
    )


def _register_http_views_once(hass: HomeAssistant) -> None:
    g = _global(hass)
    if g["views_registered"]:
        return
    g["views_registered"] = True

    class PayloadListView(HomeAssistantView):
        url = "/api/ps4_goldhen/payloads"
        name = "api:ps4_goldhen:payloads"
        requires_auth = True

        async def get(self, request):
            items = await hass.async_add_executor_job(
                _list_payloads_blocking, PAYLOAD_DIR
            )
            return web.Response(
                text=json.dumps(items),
                content_type="application/json",
            )

    class PayloadUploadView(HomeAssistantView):
        url = "/api/ps4_goldhen/payloads/upload"
        name = "api:ps4_goldhen:payloads:upload"
        requires_auth = True

        async def post(self, request):
            reader = await request.multipart()
            field = await reader.next()

            if not field or field.name != "file":
                return web.Response(status=400, text="Expected file field")

            filename = field.filename or "unknown.bin"
            safe_name = os.path.basename(filename)

            if not (safe_name.lower().endswith(".bin") or safe_name.lower().endswith(".elf")):
                return web.Response(status=400, text="Only .bin or .elf files are allowed")

            os.makedirs(PAYLOAD_DIR, exist_ok=True)
            dest = os.path.join(PAYLOAD_DIR, safe_name)

            with open(dest, "wb") as f:
                while True:
                    chunk = await field.read_chunk()
                    if not chunk:
                        break
                    f.write(chunk)

            return web.Response(
                text=json.dumps({"ok": True, "filename": safe_name}),
                content_type="application/json",
            )

    class TitleMapView(HomeAssistantView):
        url = "/api/ps4_goldhen/titles"
        name = "api:ps4_goldhen:titles"
        requires_auth = True

        async def get(self, request):
            merged: dict[str, Any] = {}
            for eid, edata in hass.data[DOMAIN].items():
                if eid.startswith("_") or not isinstance(edata, dict):
                    continue
                for tid, info in edata.get("title_map", {}).items():
                    if tid not in merged:
                        merged[tid] = info

            return web.Response(
                text=json.dumps(merged, ensure_ascii=False),
                content_type="application/json",
            )

    hass.http.register_view(PayloadListView)
    hass.http.register_view(PayloadUploadView)
    hass.http.register_view(TitleMapView)


def _register_websocket_handlers_once(hass: HomeAssistant) -> None:
    g = _global(hass)
    if g["ws_registered"]:
        return
    g["ws_registered"] = True

    @websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/state"})
    @websocket_api.async_response
    async def ws_state(hass: HomeAssistant, connection, msg):
        result = {}
        for eid, edata in hass.data[DOMAIN].items():
            if eid.startswith("_") or not isinstance(edata, dict):
                continue
            coordinator = edata.get("coordinator")
            result[eid] = {
                "klog_data": edata.get("klog_data", {}),
                "coordinator_data": coordinator.data if coordinator else {},
                "title_map_count": len(edata.get("title_map", {})),
            }
        connection.send_result(msg["id"], result)

    @websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/payloads"})
    @websocket_api.async_response
    async def ws_payloads(hass: HomeAssistant, connection, msg):
        items = await hass.async_add_executor_job(_list_payloads_blocking, PAYLOAD_DIR)
        connection.send_result(msg["id"], {"payloads": items})

    @websocket_api.websocket_command(
        {
            vol.Required("type"): f"{DOMAIN}/send_payload",
            vol.Required("filename"): str,
            vol.Optional("entry_id"): str,
        }
    )
    @websocket_api.async_response
    async def ws_send_payload(hass: HomeAssistant, connection, msg):
        filename = msg["filename"]
        entry_id = msg.get("entry_id")

        target_eid = entry_id
        if not target_eid:
            for eid in hass.data[DOMAIN]:
                if not eid.startswith("_"):
                    target_eid = eid
                    break

        if not target_eid or target_eid not in hass.data[DOMAIN]:
            connection.send_error(msg["id"], "not_found", "No PS4 entry found")
            return

        edata = hass.data[DOMAIN][target_eid]
        filepath = os.path.join(PAYLOAD_DIR, filename)

        if not os.path.isfile(filepath):
            connection.send_error(msg["id"], "not_found", f"Payload not found: {filename}")
            return

        try:
            await _send_bin_tcp(edata["host"], edata["binloader_port"], filepath)
            connection.send_result(msg["id"], {"ok": True})
        except HomeAssistantError as err:
            connection.send_error(msg["id"], "send_failed", str(err))

    websocket_api.async_register_command(hass, ws_state)
    websocket_api.async_register_command(hass, ws_payloads)
    websocket_api.async_register_command(hass, ws_send_payload)
