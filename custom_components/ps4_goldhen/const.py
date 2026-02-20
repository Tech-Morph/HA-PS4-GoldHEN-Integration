from __future__ import annotations

DOMAIN = "ps4_goldhen"

# ── Config entry keys ──────────────────────────────────────────────────
CONF_PS4_HOST        = "ps4_host"        # PS4 IP address
CONF_BINLOADER_PORT  = "binloader_port"  # BinLoader TCP port  (default 9090)
CONF_FTP_PORT        = "ftp_port"        # GoldHEN FTP port    (default 2121)
CONF_GOLDHEN_PORT    = "goldhen_port"    # GoldHEN HTTP API    (default 12800)

# ── Defaults ──────────────────────────────────────────────────────────────
DEFAULT_PS4_HOST       = "192.168.x.x"
DEFAULT_BINLOADER_PORT = 9090
DEFAULT_FTP_PORT       = 2121
DEFAULT_GOLDHEN_PORT   = 12800

# ── Payload directory on the HA host ─────────────────────────────────────────
PAYLOAD_DIR = "/config/ps4_payloads"

# ── TCP probe timeout (seconds) ──────────────────────────────────────────────
TCP_PROBE_TIMEOUT = 3.0

# ── GoldHEN HTTP API endpoints ──────────────────────────────────────────────
ENDPOINT_WAKE    = "/api/wake"
ENDPOINT_STANDBY = "/api/standby"
ENDPOINT_REBOOT  = "/api/reboot"

# ── Platforms ──────────────────────────────────────────────────────────────────
PLATFORMS: list[str] = ["sensor", "button"]
