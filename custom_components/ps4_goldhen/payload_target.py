"""Which console and which file a `send_payload` call uses (no HA imports, so the tests can load it)."""
from __future__ import annotations

import os
from collections.abc import Iterable, Mapping


def payload_target(
    consoles: Iterable[Mapping], requested_host: str | None, *, host_key: str, port_key: str, default_port: int
) -> tuple[str, int]:
    """(host, BinLoader port) for the call.

    `ps4_host` picks one of this integration's consoles; without it the first console is used. The port always comes
    from that console's entry. ValueError if no console is set up or the host isn't one of them.
    """
    targets: dict[str, int] = {}
    for data in consoles:
        if host := (data.get(host_key) or "").strip():
            targets.setdefault(host, int(data.get(port_key) or default_port))
    if not targets:
        raise ValueError("No PS4 GoldHEN console is set up")
    requested = (requested_host or "").strip()
    if not requested:
        return next(iter(targets.items()))
    if requested not in targets:
        raise ValueError(f"{requested} is not a PS4 set up in PS4 GoldHEN (set up: {', '.join(sorted(targets))})")
    return requested, targets[requested]


def payload_path(payload_dir: str, payload_file: str) -> str:
    """Full path of a file directly inside payload_dir; ValueError for a path, `..` or a link that leads outside."""
    name = (payload_file or "").strip()
    if not name or name in (".", "..") or os.path.basename(name) != name:
        raise ValueError(f"payload_file must be a file name in {payload_dir}")
    path = os.path.realpath(os.path.join(payload_dir, name))
    if os.path.dirname(path) != os.path.realpath(payload_dir):
        raise ValueError(f"payload_file must be a file name in {payload_dir}")
    return path
