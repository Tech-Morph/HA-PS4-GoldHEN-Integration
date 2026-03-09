from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
from dataclasses import dataclass

from aiohttp import ClientError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# TMDB2 JSON format (PS4): /tmdb2/<TITLEID_00>_<HMAC-SHA1>/<TITLEID_00>.json
# Hash seed: "<TITLEID>_00" (e.g. CUSA00001_00)
# Key is the known PlayStation TMDB HMAC key referenced publicly in multiple places.
# Source for format/key/seed examples: PSDevWiki and Apollo-PS4 discussion.
_TMDB_HMAC_SHA1_KEY_HEX = (
    "F5DE66D2680E255B2DF79E74F890EBF349262F618BCAE2A9ACCDEE5156CE8DF2"
    "CDF2D48C71173CDC2594465B87405D197CF1AED3B7E9671EEB56CA6753C2E6B0"
)

# Update XML format: https://gs-sec.ww.np.dl.playstation.net/plo/np/<TITLEID>/<HMAC-SHA256>/ <TITLEID>-ver.xml
# Hash seed: "np_<TITLEID>"
# Commonly shared key for generating the URL.
_PLO_HMAC_SHA256_KEY_HEX = "AD62E37F905E06BC19593142281C112CEC0E7EC3E97EFDCAEFCDBAAFA6378D84"


@dataclass
class TitleLookupResult:
    title_id: str
    name: str | None
    source: str | None
    error: str | None = None


class PS4TitleResolver:
    """Resolve PS4 Title IDs (CUSAxxxxx) to human-readable game names."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._cache: dict[str, TitleLookupResult] = {
            "NPXS20001": TitleLookupResult("NPXS20001", "PlayStation Home Screen", "static"),
        }

    async def async_resolve(self, title_id: str) -> TitleLookupResult:
        title_id = (title_id or "").strip()
        if not title_id:
            return TitleLookupResult(title_id, None, None, "empty title_id")

        if title_id in self._cache:
            return self._cache[title_id]

        if title_id.startswith("NPXS"):
            res = TitleLookupResult(title_id, f"System App ({title_id})", "system")
            self._cache[title_id] = res
            return res

        # Only attempt remote lookups for typical PS4 game IDs.
        if not re.match(r"^CUSA\d{5}$", title_id):
            res = TitleLookupResult(title_id, title_id, "unknown_format")
            self._cache[title_id] = res
            return res

        # Try TMDB2 JSON first (usually best metadata).
        res = await self._async_try_tmdb2_json(title_id)
        if res.name:
            self._cache[title_id] = res
            return res

        # Fallback: try update ver.xml (often includes a title attribute).
        res2 = await self._async_try_update_ver_xml(title_id)
        if res2.name:
            self._cache[title_id] = res2
            return res2

        # Final fallback: return raw ID
        final = TitleLookupResult(title_id, title_id, "fallback", error=res.error or res2.error)
        self._cache[title_id] = final
        return final

    def _tmdb2_hash(self, title_id: str) -> str:
        key = bytes.fromhex(_TMDB_HMAC_SHA1_KEY_HEX)
        seed = f"{title_id}_00"
        mac = hmac.new(key, seed.encode("utf-8"), hashlib.sha1)
        return mac.hexdigest().upper()

    async def _async_try_tmdb2_json(self, title_id: str) -> TitleLookupResult:
        session = async_get_clientsession(self._hass)
        hash_hex = self._tmdb2_hash(title_id)
        url = (
            f"https://tmdb.np.dl.playstation.net/tmdb2/"
            f"{title_id}_00_{hash_hex}/{title_id}_00.json"
        )

        try:
            async with session.get(url, timeout=8) as resp:
                if resp.status != 200:
                    return TitleLookupResult(title_id, None, None, f"tmdb2 http {resp.status}")

                # Some Sony endpoints may not send perfect content-type headers
                raw = await resp.text()
                data = json.loads(raw)
                name = data.get("name") or data.get("title")  # observed variations
                if isinstance(name, str) and name.strip():
                    return TitleLookupResult(title_id, name.strip(), "tmdb2")

                return TitleLookupResult(title_id, None, None, "tmdb2 missing name field")

        except (asyncio.TimeoutError, ClientError, json.JSONDecodeError) as err:
            return TitleLookupResult(title_id, None, None, f"tmdb2 error: {err}")

    async def _async_try_update_ver_xml(self, title_id: str) -> TitleLookupResult:
        session = async_get_clientsession(self._hass)

        try:
            key = bytes.fromhex(_PLO_HMAC_SHA256_KEY_HEX)
            seed = f"np_{title_id}"
            mac = hmac.new(key, seed.encode("utf-8"), hashlib.sha256)
            hash_hex = mac.hexdigest()

            url = (
                f"https://gs-sec.ww.np.dl.playstation.net/plo/np/"
                f"{title_id}/{hash_hex}/{title_id}-ver.xml"
            )

            async with session.get(url, timeout=8) as resp:
                if resp.status != 200:
                    return TitleLookupResult(title_id, None, None, f"ver.xml http {resp.status}")

                xml = await resp.text()

                # Common pattern: title="Game Name"
                m = re.search(r'title\s*=\s*"([^"]+)"', xml, re.IGNORECASE)
                if m and m.group(1).strip():
                    return TitleLookupResult(title_id, m.group(1).strip(), "ver.xml")

                return TitleLookupResult(title_id, None, None, "ver.xml missing title attribute")

        except (asyncio.TimeoutError, ClientError, ValueError) as err:
            return TitleLookupResult(title_id, None, None, f"ver.xml error: {err}")
