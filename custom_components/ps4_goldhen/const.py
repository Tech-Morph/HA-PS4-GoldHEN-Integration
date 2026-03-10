from __future__ import annotations

DOMAIN = "ps4_goldhen"

# — Config entry keys ———————————————————————————————————————————————————————
CONF_PS4_HOST       = "ps4_host"       # PS4 IP address
CONF_BINLOADER_PORT = "binloader_port" # BinLoader TCP port (default 9090)
CONF_FTP_PORT       = "ftp_port"       # GoldHEN FTP port  (default 2121)
CONF_RPI_PORT       = "rpi_port"       # Remote Package Installer port (default 12800)
CONF_KLOG_PORT      = "klog_port"      # GoldHEN Klog port (default 3232)

# — Defaults ————————————————————————————————————————————————————————————————
DEFAULT_PS4_HOST        = "192.168.x.x"
DEFAULT_BINLOADER_PORT  = 9090
DEFAULT_FTP_PORT        = 2121
DEFAULT_RPI_PORT        = 12800
DEFAULT_KLOG_PORT       = 3232

# — Payload directory on the HA host ————————————————————————————————————————
PAYLOAD_DIR = "/config/ps4_payloads"

# — TCP probe timeout (seconds) —————————————————————————————————————————————
TCP_PROBE_TIMEOUT = 3.0

# — Platforms ———————————————————————————————————————————————————————————————
PLATFORMS: list[str] = ["sensor", "button"]

# — Sensor data keys (from klog parsing) ——
SENSOR_CURRENT_GAME  = "current_game"
SENSOR_CPU_TEMP      = "cpu_temp"
SENSOR_TITLE_ID      = "title_id"
SENSOR_GAME_NAME     = "game_name"
SENSOR_GAME_COVER    = "cover"
SENSOR_KLOG_LAST_LINE = "klog_last_line"

# — HA event fired for every non-noise klog line ——————————————————————————
EVENT_KLOG_LINE = "ps4_goldhen_klog_event"

HOME_SCREEN = "PlayStation Home Screen"

APP_DB_REMOTE = "/system_data/priv/mms/app.db"
APP_DB_LOCAL = "ps4_app.db"

DB_REFRESH_INTERVAL = 3600
