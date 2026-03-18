from __future__ import annotations

DOMAIN = "ps4_goldhen"

# — Config entry keys ———————————————————————————————————————————————————————
CONF_PS4_HOST       = "ps4_host"
CONF_BINLOADER_PORT = "binloader_port"
CONF_FTP_PORT       = "ftp_port"
CONF_RPI_PORT       = "rpi_port"
CONF_KLOG_PORT      = "klog_port"

# — Defaults ————————————————————————————————————————————————————————————————
DEFAULT_PS4_HOST        = "192.168.x.x"
DEFAULT_BINLOADER_PORT  = 9090
DEFAULT_FTP_PORT        = 2121
DEFAULT_RPI_PORT        = 12800
DEFAULT_KLOG_PORT       = 3232

PAYLOAD_DIR       = "/config/ps4_payloads"
TCP_PROBE_TIMEOUT = 3.0
PLATFORMS: list[str] = ["sensor", "button"]

# — Sensor data keys ————————————————————————————————————————————————————————
SENSOR_CURRENT_GAME   = "current_game"
SENSOR_CPU_TEMP       = "cpu_temp"
SENSOR_SOC_TEMP       = "soc_temp"
SENSOR_TITLE_ID       = "title_id"
SENSOR_GAME_NAME      = "game_name"
SENSOR_GAME_COVER     = "cover"
SENSOR_KLOG_LAST_LINE = "klog_last_line"

# — Power sensor keys (watts from PS4StateJSON) —————————————————————————————
SENSOR_SOC_POWER   = "soc_power_w"
SENSOR_CPU_POWER   = "cpu_power_w"
SENSOR_GPU_POWER   = "gpu_power_w"
SENSOR_TOTAL_POWER = "total_power_w"

EVENT_KLOG_LINE = "ps4_goldhen_klog_event"
HOME_SCREEN     = "PlayStation Home Screen"

APP_DB_REMOTE        = "/system_data/priv/mms/app.db"
APP_DB_LOCAL         = "ps4_app.db"
DB_REFRESH_INTERVAL  = 3600
