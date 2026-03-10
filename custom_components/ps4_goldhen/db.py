"""PS4 app.db downloader and game map builder."""
from __future__ import annotations

import contextlib
import ftplib
import io
import logging
import os
import sqlite3
import tempfile
import time
from typing import Any

from .const import APP_DB_REMOTE, APP_DB_LOCAL, DEFAULT_FTP_PORT

_LOGGER = logging.getLogger(__name__)

# Some firmwares use tbl_appbrowse, others tbl_appbrowse_<suffix>
_APPBROWSE_PREFIXES = ("tblappbrowse", "tbl_appbrowse")


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
    """Return {lower_col: actual_col} mapping."""
    rows = conn.execute(f'PRAGMA table_info("{table.replace(chr(34), chr(34)*2)}")').fetchall()
    return {str(r[1]).lower(): str(r[1]) for r in rows}


def _extract_game_map(db_bytes: bytes) -> dict[str, dict[str, Any]]:
    """
    Parse app.db bytes and return:
      { titleId: {"name": str, "cover": str | None} }
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
            tables = _list_appbrowse_tables(conn)
            _LOGGER.debug("app.db scan found tables: %s", tables)

            for table in tables:
                cols = _table_columns(conn, table)

                # Must have at least titleId + titleName
                if "titleid" not in cols or "titlename" not in cols:
                    continue

                tid_col   = cols["titleid"]
                name_col  = cols["titlename"]
                thumb_col = cols.get("thumbnailurl")   # may not exist
                vis_col   = cols.get("visible")

                where = f'WHERE "{vis_col}" = 1' if vis_col else ""
                query = (
                    f'SELECT "{tid_col}", "{name_col}"'
                    + (f', "{thumb_col}"' if thumb_col else "")
                    + f' FROM "{table}" {where}'
                )

                try:
                    rows = conn.execute(query).fetchall()
                except Exception as err:
                    _LOGGER.debug("Skipping table %s: %s", table, err)
                    continue

                for row in rows:
                    tid   = str(row[0]).strip().upper() if row[0] else None
                    tname = str(row[1]).strip()         if row[1] else None
                    cover = str(row[2]).strip()         if thumb_col and row[2] else None

                    if not tid or not tname:
                        continue

                    # Don't overwrite a previously found entry
                    if tid not in game_map:
                        game_map[tid] = {"name": tname, "cover": cover}

        finally:
            conn.close()

    finally:
        if tmp_path:
            with contextlib.suppress(Exception):
                os.unlink(tmp_path)

    _LOGGER.info("app.db scan resolved %d titles", len(game_map))
    return game_map


def download_and_parse(host: str, port: int) -> dict[str, dict[str, Any]]:
    """
    Blocking: FTP-download app.db from PS4 and return the game map.
    Call via hass.async_add_executor_job().
    """
    buffer = io.BytesIO()

    with ftplib.FTP() as ftp:
        ftp.connect(host, port, timeout=20)
        ftp.login()

        # Try primary path, fall back to .bak
        for candidate in (APP_DB_REMOTE, APP_DB_REMOTE + ".bak"):
            buffer.seek(0)
            buffer.truncate()
            try:
                ftp.retrbinary(f"RETR {candidate}", buffer.write)
                db_bytes = buffer.getvalue()
                if db_bytes:
                    _LOGGER.info(
                        "Downloaded %s from PS4 (%d bytes)", candidate, len(db_bytes)
                    )
                    return _extract_game_map(db_bytes)
            except ftplib.error_perm:
                continue

    raise FileNotFoundError("Could not download app.db from PS4 FTP")
