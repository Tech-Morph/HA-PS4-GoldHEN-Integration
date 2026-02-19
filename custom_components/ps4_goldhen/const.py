from __future__ import annotations

DOMAIN = "ps4_goldhen"

# Config entry keys
CONF_ADDON_URL = "addon_url"       # e.g. http://192.168.1.50:8787
CONF_HOST = "host"                 # PS4 IP - used for direct payload sends
CONF_BINLOADER_PORT = "binloader_port"
CONF_FTP_PORT = "ftp_port"

# Defaults
DEFAULT_ADDON_URL = "http://192.168.1.50:8787"
DEFAULT_BINLOADER_PORT = 9090
DEFAULT_FTP_PORT = 2121
DEFAULT_ADDON_PORT = 8787

# Add-on API endpoints
ENDPOINT_STATUS = "/status"
ENDPOINT_WAKE = "/wake"
ENDPOINT_STANDBY = "/rest"
ENDPOINT_REBOOT = "/reboot"
ENDPOINT_PAYLOAD = "/payload"
ENDPOINT_HEALTH = "/health"

# Platforms
PLATFORMS: list[str] = ["sensor", "button"]
