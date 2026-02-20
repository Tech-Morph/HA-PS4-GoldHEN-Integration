from __future__ import annotations

DOMAIN = "ps4_goldhen"

# Config entry keys
CONF_ADDON_URL = "addon_url"  # e.g. http://192.168.1.50:8787
CONF_PS4_HOST = "ps4_host"   # e.g. 192.168.1.14

# Defaults
DEFAULT_ADDON_URL = "http://192.168.1.50:8787"
DEFAULT_PS4_HOST = "192.168.1.14"

# Add-on API endpoints
ENDPOINT_STATUS = "/status"
ENDPOINT_WAKE = "/wake"
ENDPOINT_STANDBY = "/rest"
ENDPOINT_REBOOT = "/reboot"
ENDPOINT_PAYLOAD = "/payload"
ENDPOINT_HEALTH = "/health"

# Platforms
PLATFORMS: list[str] = ["sensor", "button"]
