"""Structured FTP listings with an explicit UTC timestamp contract."""
from __future__ import annotations

from datetime import datetime, timezone
import ftplib
import posixpath
import re
from typing import Any


def parse_modify(value: str | None) -> str | None:
    """Parse RFC 3659 modify values as UTC, never as HA's local timezone."""
    if not value or not re.fullmatch(r"\d{14}(?:\.\d+)?", value):
        return None
    whole, _, fraction = value.partition(".")
    try:
        dt = datetime.strptime(whole, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        if fraction:
            dt = dt.replace(microsecond=int((fraction + "000000")[:6]))
        return dt.isoformat().replace("+00:00", "Z")
    except ValueError:
        return None


def _size(value: str | None) -> int | None:
    try:
        result = int(value)
        return result if result >= 0 else None
    except (ValueError, TypeError):
        return None


def _path(parent: str, name: str) -> str:
    return posixpath.join(parent.rstrip("/") or "/", name)


def _valid_name(name: str) -> bool:
    return bool(name) and name not in (".", "..") and not any(c in name for c in ("/", "\r", "\n", "\0"))


def list_directory(ftp: ftplib.FTP, path: str) -> list[dict[str, Any]]:
    """Use MLSD; fall back only on explicit command-not-supported replies."""
    path = path or "/"
    if not path.startswith("/") or any(c in path for c in ("\r", "\n", "\0")):
        raise ValueError("Invalid FTP directory path")
    ftp.cwd(path)
    entries: list[dict[str, Any]] = []
    try:
        for name, original in ftp.mlsd():
            facts = {str(k).lower(): str(v) for k, v in original.items()}
            kind = facts.get("type", "").lower()
            if kind in ("cdir", "pdir") or not _valid_name(name):
                continue
            is_dir = kind == "dir"
            modified = parse_modify(facts.get("modify"))
            entries.append({
                "name": name, "path": _path(path, name), "is_dir": is_dir,
                "size": 0 if is_dir else _size(facts.get("size")),
                "modified": modified or "Unknown",
                "modified_utc": modified,
                "permissions": facts.get("unix.mode", facts.get("perm", "")),
                "listing_source": "mlsd",
            })
    except ftplib.error_perm as exc:
        if str(exc)[:3] not in {"500", "501", "502", "504"}:
            raise
        entries = []
        raw: list[str] = []
        ftp.retrlines("LIST", raw.append)
        for line in raw:
            parts = line.split(None, 8)
            if len(parts) < 9:
                continue
            name = parts[8]
            if not _valid_name(name):
                continue
            is_dir = parts[0].startswith("d")
            entries.append({
                "name": name, "path": _path(path, name), "is_dir": is_dir,
                "size": 0 if is_dir else _size(parts[4]),
                "modified": " ".join(parts[5:8]),
                "modified_utc": None,
                "permissions": parts[0], "listing_source": "list",
            })
    return sorted(entries, key=lambda entry: (not entry["is_dir"], entry["name"].lower()))
