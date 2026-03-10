"""PS4 app.db downloader and game map builder."""
from __future__ import annotations

import contextlib
import ftplib
import io
import logging
import os
import sqlite3
import tempfile
from typing import Any

from .const import APP_DB_REMOTE, DEFAULT_FTP_PORT

_LOGGER = logging.getLogger(__name__)


def _list_appbrowse_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT name FROM sqlite_master
        WHERE type = 'table'
          AND (
            lower(name) LIKE 'tblappbrowse%'
            OR lower(name) LIKE 'tbl_appbrowse%'
          )
        ORDER BY name
        """
    ).fetchall()
    return [str(r[0]) for r in rows if r and r[0]]


def _table_columns(conn: sqlite3.Connection, table: str) -> dict[str, str]:
    """Return {lower_col_name: actual_col_name} for every column in table."""
    escaped = table.replace('"', '""')
    rows = conn.execute(f'PRAGMA table_info("{escaped}")').fetchall()
    return {str(r[1]).lower(): str(r[1]) for r in rows}


def _extract_game_map(db_bytes: bytes) -> dict[str, dict[str, Any]]:
    """
    Parse raw app.db bytes.
    Returns { titleId: {"name": str, "cover": str | None} }
    """
    game_map: dict[str, dict[str, Any]] = {}
    tmp_path = ""

    try:
        with tempfile.NamedTemporaryFile(
            prefix="ps4gh_appdb_", suffix=".db", delete=False
        ) as tmp:
            tmp.write(db_bytes)
            tmp_path = tmp.name

        conn = sqlite3.connect(tmp_path)
        conn.row_factory = sqlite3.Row

        try:
            # Log every table in the DB for debugging
            all_tables = [
                r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                ).fetchall()
            ]
            _LOGGER.warning("app.db tables: %s", all_tables)

            tables = _list_appbrowse_tables(conn)
            _LOGGER.warning("app.db appbrowse tables found: %s", tables)

            for table in tables:
                cols = _table_columns(conn, table)
                _LOGGER.warning("Table %s columns: %s", table, list(cols.keys()))

                if "titleid" not in cols or "titlename" not in cols:
                    _LOGGER.warning(
                        "Skipping table %s — missing titleid or titlename", table
                    )
                    continue

                tid_col   = cols["titleid"]
                name_col  = cols["titlename"]

                # Cover: try thumbnailurl first, then metadatapath
                cover_col = (
                    cols.get("thumbnailurl")
                    or cols.get("metadatapath")
                )
                vis_col   = cols.get("visible")

                select_cols = f'"{tid_col}", "{name_col}"'
                if cover_col:
                    select_cols += f', "{cover_col}"'

                where = f'WHERE "{vis_col}" = 1' if vis_col else ""
                query = f'SELECT {select_cols} FROM "{table}" {where}'

                _LOGGER.warning("Executing: %s", query)

                try:
                    rows = conn.execute(query).fetchall()
                except Exception as err:
                    _LOGGER.warning("Query failed on %s: %s", table, err)
                    continue

                _LOGGER.warning("Table %s returned %d rows", table, len(rows))

                for row in rows:
                    tid   = str(row[0]).strip().upper() if row[0] else None
                    tname = str(row[1]).strip()         if row[1] else None
                    cover = str(row[2]).strip()         if cover_col and len(row) > 2 and row[2] else None

                    if not tid or not tname:
                        continue

                    if tid not in game_map:
                        game_map[tid] = {"name": tname, "cover": cover}

        finally:
            conn.close()

    finally:
        if tmp_path:
            with contextlib.suppress(Exception):
                os.unlink(tmp_path)

    _LOGGER.warning("app.db total resolved: %d titles", len(game_map))
    return game_map


def download_and_parse(host: str, port: int) -> dict[str, dict[str, Any]]:
    """
    Blocking — FTP-download app.db from the PS4 and return the game map.
    Call via hass.async_add_executor_job().
    """
    _LOGGER.warning("Attempting app.db download from %s:%d", host, port)
    buffer = io.BytesIO()

    with ftplib.FTP() as ftp:
        ftp.connect(host, port, timeout=20)
        ftp.login()

        for candidate in (APP_DB_REMOTE, APP_DB_REMOTE + ".bak"):
            buffer.seek(0)
            buffer.truncate()
            try:
                ftp.retrbinary(f"RETR {candidate}", buffer.write)
                db_bytes = buffer.getvalue()
                if db_bytes:
                    _LOGGER.warning(
                        "Downloaded %s from PS4 (%d bytes)", candidate, len(db_bytes)
                    )
                    return _extract_game_map(db_bytes)
            except ftplib.error_perm as err:
                _LOGGER.warning("FTP RETR %s failed: %s", candidate, err)
                continue

    raise FileNotFoundError("Could not download app.db from PS4 FTP")
