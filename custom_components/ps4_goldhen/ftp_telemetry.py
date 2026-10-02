"""Bounded, read-only FTP telemetry transport; no Home Assistant dependency."""
from __future__ import annotations

import asyncio
import json
import math
import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TelemetryResult:
    ftp_reachable: bool
    values: dict[str, Any] | None
    status: str


class FTPReplyError(Exception):
    def __init__(self, code: int) -> None:
        self.code = code
        super().__init__(f"FTP reply {code}")


def parse_telemetry(body: bytes) -> dict[str, Any]:
    parsed = json.loads(body.decode("utf-8-sig"))
    if not isinstance(parsed, dict) or not parsed:
        raise ValueError("Telemetry must be a nonempty JSON object")
    values: dict[str, Any] = {}
    numeric = {
        "cpu_temp": (1, 150), "soc_temp": (1, 150),
        "soc_power_w": (0, 1000), "cpu_power_w": (0, 1000),
        "gpu_power_w": (0, 1000), "total_power_w": (0, 1000),
        "fan_duty": (0, 100),
    }
    for key, (low, high) in numeric.items():
        value = parsed.get(key)
        if (isinstance(value, (int, float)) and not isinstance(value, bool)
                and math.isfinite(value) and low <= value <= high):
            values[key] = value
        else:
            values[key] = None
    for key in ("fw_version", "hw_model", "console_id"):
        value = parsed.get(key)
        values[key] = value if isinstance(value, str) and len(value) <= 128 else None
    if not any(key in parsed for key in values):
        raise ValueError("Telemetry has no recognized fields")
    return values


async def async_fetch_telemetry(
    host: str, port: int, path: str,
    *, operation_timeout: float = 1.0, total_timeout: float = 4.0,
    max_bytes: int = 65536,
) -> TelemetryResult:
    """Return transport and telemetry health separately; preserve cancellation."""
    if not path.startswith("/") or "\r" in path or "\n" in path:
        raise ValueError("Invalid telemetry path")
    if operation_timeout <= 0 or total_timeout <= 0 or max_bytes < 1:
        raise ValueError("Invalid transport limits")
    control_writer = data_writer = None
    reachable = False

    async def bounded(awaitable):
        return await asyncio.wait_for(awaitable, timeout=operation_timeout)

    async def reply(reader) -> tuple[int, str]:
        raw = await bounded(reader.readline())
        if not raw:
            raise ConnectionError("FTP control connection closed")
        if len(raw) > 4096:
            raise ValueError("FTP reply too long")
        first = raw.decode("utf-8", errors="replace").rstrip("\r\n")
        match = re.match(r"^(\d{3})([ -])(.*)$", first)
        if match is None:
            raise ValueError("Malformed FTP reply")
        code = int(match.group(1))
        if match.group(2) == "-":
            for _ in range(64):
                raw = await bounded(reader.readline())
                if not raw or len(raw) > 4096:
                    raise ValueError("Incomplete FTP multiline reply")
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                if line.startswith(f"{code} "):
                    return code, line
            raise ValueError("FTP multiline reply too long")
        return code, first

    async def command(reader, value: str) -> tuple[int, str]:
        control_writer.write((value + "\r\n").encode("ascii"))
        await bounded(control_writer.drain())
        return await reply(reader)

    async def close(writer) -> None:
        if writer is not None:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), timeout=0.15)
            except (TimeoutError, OSError):
                pass

    try:
        async with asyncio.timeout(total_timeout):
            reader, control_writer = await bounded(
                asyncio.open_connection(host, port, limit=4096)
            )
            code, _ = await reply(reader)
            if code == 120:
                code, _ = await reply(reader)
            if code != 220:
                raise FTPReplyError(code)
            code, _ = await command(reader, "USER anonymous")
            if code == 331:
                code, _ = await command(reader, "PASS anonymous@")
            if code != 230:
                raise FTPReplyError(code)
            reachable = True
            code, _ = await command(reader, "TYPE I")
            if code != 200:
                raise FTPReplyError(code)
            code, line = await command(reader, "PASV")
            if code != 227:
                raise FTPReplyError(code)
            match = re.search(r"\((\d+,\d+,\d+,\d+,\d+,\d+)\)", line)
            if match is None:
                raise ValueError("Malformed PASV reply")
            nums = [int(n) for n in match.group(1).split(",")]
            if any(n > 255 for n in nums):
                raise ValueError("Invalid PASV octet")
            data_port = nums[4] * 256 + nums[5]
            if data_port == 0:
                raise ValueError("Invalid PASV port")
            peer = control_writer.get_extra_info("peername")
            data_host = peer[0] if peer else host
            data_reader, data_writer = await bounded(
                asyncio.open_connection(data_host, data_port)
            )
            code, _ = await command(reader, f"RETR {path}")
            if code not in (125, 150):
                raise FTPReplyError(code)
            body = bytearray()
            while True:
                chunk = await bounded(data_reader.read(4096))
                if not chunk:
                    break
                body.extend(chunk)
                if len(body) > max_bytes:
                    raise ValueError("Telemetry exceeds size limit")
            code, _ = await reply(reader)
            if code not in (226, 250):
                raise FTPReplyError(code)
            try:
                values = parse_telemetry(bytes(body))
            except (ValueError, UnicodeError, OverflowError, RecursionError):
                return TelemetryResult(True, None, "invalid_json")
            return TelemetryResult(True, values, "ok")
    except asyncio.CancelledError:
        raise
    except FTPReplyError as err:
        return TelemetryResult(reachable, None, f"ftp_{err.code}")
    except TimeoutError:
        return TelemetryResult(reachable, None, "timeout")
    except (OSError, ConnectionError):
        return TelemetryResult(reachable, None, "connection_error")
    except (ValueError, OverflowError):
        return TelemetryResult(reachable, None, "protocol_error")
    finally:
        try:
            await close(data_writer)
        finally:
            await close(control_writer)
