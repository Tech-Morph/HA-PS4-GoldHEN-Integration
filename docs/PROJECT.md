# HA-PS4-GoldHEN-Integration — Project Reference

Home Assistant custom integration (HACS) to control and monitor a PS4 running GoldHEN network services.

---

## Goals

- Provide a clean HA sidebar panel for PS4 tools: FTP browser, BinLoader payload sender, live Klog viewer, and a GoldHEN Dashboard.
- Expose useful HA sensor entities: current game (with resolved names), FTP online status, CPU/SoC temperature, power draw, fan duty, and hardware diagnostics.
- Automatically resolve game titles and cover art from the PS4's local `app.db` — no remote API keys or cloud dependency.
- Keep everything local-first and LAN-friendly.
- Avoid fragile one-off scripts by using HA-native services, WebSocket APIs, and `CoordinatorEntity`.

---

## Architecture

### Frontend
`custom_components/ps4_goldhen/frontend/ps4-goldhen-panel.js`
Web component registered as a custom sidebar panel. Communicates exclusively via HA WebSocket API and the two HTTP endpoints.

### Backend Modules

| File | Responsibility |
|---|---|
| `__init__.py` | Integration setup, `KlogStateMachine`, `_klog_listener_task`, `_db_refresh_task`, `_poll_ftp_json`, FTP HTTP views, WebSocket registrations, payload service |
| `sensor.py` | All sensor entities — `CoordinatorEntity` subclasses for game, FTP status, temperatures, power, fan duty, and hardware diagnostics |
| `db.py` | FTP download of `app.db`, SQLite parse, game map builder (`download_and_parse`) |
| `button.py` | Button platform entities |
| `config_flow.py` | UI config flow for host/port setup |
| `const.py` | All constants: domain, port defaults, sensor keys, file paths, intervals |
| `websocket.py` | All WebSocket command handlers: FTP list/delete/rename/mkdir/get_text/put_text, klog_subscribe |
| `title_resolver.py` | Optional remote fallback: resolves CUSA title IDs via Sony TMDB2 / ver.xml |

---

## Data Flow

### FTP JSON Poll → Telemetry Sensors
```
DataUpdateCoordinator (every 3 seconds)
  └─► _poll_ftp_json
        ├─► async PASV FTP → RETR /data/GoldHEN/ps4_state.json
        ├─► Parses: cpu_temp, soc_temp, soc_power_w, cpu_power_w,
        │           gpu_power_w, total_power_w, fan_duty,
        │           fw_version, hw_model, console_id
        └─► coordinator.async_set_updated_data()
              └─► All CoordinatorEntity sensors update simultaneously
```

### Klog → Game State Sensor
```
PS4 Klog TCP Stream
  └─► _klog_listener_task (background task per entry)
        └─► _parse_klog_line
              ├─► KlogStateMachine.ingest()  → updates current_title_id
              ├─► Injects game_name / game_cover from entry_data["game_map"]
              └─► coordinator.async_set_updated_data()
                    └─► PS4CurrentGameSensor.native_value (CoordinatorEntity)
```

### app.db → game_map → Sensor
```
_db_refresh_task (runs on startup + every DB_REFRESH_INTERVAL seconds)
  └─► hass.async_add_executor_job(db.download_and_parse)
        ├─► ftplib: RETR /system_data/priv/mms/app.db
        └─► sqlite3: scan tblappbrowse* tables → { titleId: {name, cover} }
  └─► entry_data["game_map"] updated
  └─► If a game is currently running → coordinator push with resolved name
```

### Pi Sensor → Power State
```
sensor.ps4_state_pi  (external — user-managed)
  └─► async_track_state_change_event → PS4CurrentGameSensor._on_pi_state_change
        └─► Overrides native_value with "Rest Mode" or "Off" as appropriate
```

---

## WebSocket Commands

| Command | Description |
|---|---|
| `ps4_goldhen/list_entries` | List all configured PS4 entries (host, ports) |
| `ps4_goldhen/list_payloads` | List `.bin`/`.elf` files from payload directory |
| `ps4_goldhen/ftp_list_dir` | List a PS4 FTP directory |
| `ps4_goldhen/ftp_delete` | Delete a file or empty dir on the PS4 |
| `ps4_goldhen/ftp_rename` | Rename / move a file or dir on the PS4 |
| `ps4_goldhen/ftp_mkdir` | Create a directory on the PS4 |
| `ps4_goldhen/ftp_get_text` | Read a text file from the PS4 |
| `ps4_goldhen/ftp_put_text` | Write a text file to the PS4 |
| `ps4_goldhen/klog_subscribe` | Subscribe to live klog stream (event per line) |

## HTTP Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/ps4_goldhen/ftp/download` | GET | Download a file from PS4 via FTP |
| `/api/ps4_goldhen/ftp/upload` | POST (multipart) | Upload a file to PS4 via FTP |
| `/api/ps4_goldhen/cover/{entry_id}/{title_id}` | GET | Serve game cover art — CDN redirect or FTP fetch from `/user/appmeta/` |

---

## Sensor Entities

### `sensor.ps4_goldhen_current_game`
- **State:** Resolved game name from `app.db`, or `PlayStation Home Screen`, `Rest Mode`, `Off`
- **Attributes:** `title_id`, `game_name`, `game_cover`, `cover_url`, `state_classification`, `pi_state`, `klog_connected`, `state_reason`, `pending_title_id`, `state_signal_line`

### `sensor.ps4_goldhen_ftp_status`
- **State:** `online` / `offline`
- Polled via FTP JSON fetch every **3 seconds**

### `sensor.ps4_goldhen_cpu_temperature`
- **State:** Float °C
- Polled from `ps4_state.json` via FTP every **3 seconds**

### `sensor.ps4_goldhen_soc_temperature`
- **State:** Float °C
- Polled from `ps4_state.json` via FTP every **3 seconds**

### `sensor.ps4_goldhen_soc_power` / `cpu_power` / `gpu_power` / `total_power`
- **State:** Float W
- Polled from `ps4_state.json` via FTP every **3 seconds**

### `sensor.ps4_goldhen_fan_duty`
- **State:** Integer % (PWM duty cycle: `duty * 100 / 255`)
- Polled from `ps4_state.json` via FTP every **3 seconds**
- Reflects the duty byte set by the PRX fan curve — not physical RPM percentage

### `sensor.ps4_goldhen_firmware_version` *(Diagnostic)*
- **State:** String (e.g. `11.00`)
- Resolved once at plugin load, static for session lifetime

### `sensor.ps4_goldhen_hardware_model` *(Diagnostic)*
- **State:** String (e.g. `CUH-1001A`)
- Auto-detected from Neo flag + firmware, or overridden via `/data/GoldHEN/ps4_state.conf`

### `sensor.ps4_goldhen_console_id` *(Diagnostic)*
- **State:** 32-character hex IDPS string
- Resolved once at plugin load, static for session lifetime

---

## PS4StateJSON PRX

The `PS4StateJSON.prx` GoldHEN plugin is the data source for all telemetry sensors. It runs as a background thread on the PS4 and:

1. Reads CPU temp, SoC temp, and power rails from hardware registers
2. Controls the fan via **syscall 532** using a stepped duty curve
3. Resolves `fw_version`, `hw_model`, and `console_id` at load time
4. Writes all values to `/data/GoldHEN/ps4_state.json` every **3 seconds**

### Fan Curve

| Die Temp | Duty Byte | ~Duty % |
|---|---|---|
| < 60°C | `0x66` | 40% |
| 60–65°C | `0x80` | 50% |
| 65–72°C | `0x8C` | 55% |
| 72–76°C | `0x9E` | 62% |
| 76–80°C | `0xAD` | 68% |
| 80–85°C | `0xBF` | 75% |
| 85–90°C | `0xD9` | 85% |
| > 90°C | `0xFF` | 100% |

Duty is only written on change. On plugin unload, fan control is returned to firmware via `sc532_duty(0)`.

---

## Services

### `ps4_goldhen.send_payload`
```yaml
service: ps4_goldhen.send_payload
data:
  payload_file: GoldHEN.bin
  ps4_host: 192.168.1.100        # optional
  binloader_port: 9090           # optional
  timeout: 30                    # optional
```

---

## Constants Reference (`const.py`)

| Constant | Default | Description |
|---|---|---|
| `DEFAULT_FTP_PORT` | `2121` | GoldHEN FTP port |
| `DEFAULT_BINLOADER_PORT` | `9090` | GoldHEN BinLoader port |
| `DEFAULT_KLOG_PORT` | `3232` | GoldHEN klog port |
| `DEFAULT_RPI_PORT` | `8080` | Pi REST sensor port |
| `PAYLOAD_DIR` | `/config/ps4_payloads` | Local payload storage directory |
| `APP_DB_REMOTE` | `/system_data/priv/mms/app.db` | FTP path to PS4 app database |
| `DB_REFRESH_INTERVAL` | `3600` | Seconds between app.db refreshes |
| `TCP_PROBE_TIMEOUT` | `3.0` | Seconds for FTP reachability probe |
| `HOME_SCREEN` | `PlayStation Home Screen` | State string for home screen |
| `SENSOR_FAN_DUTY` | `fan_duty` | Fan PWM duty cycle key |
| `SENSOR_FW_VERSION` | `fw_version` | Firmware version key |
| `SENSOR_HW_MODEL` | `hw_model` | Hardware model key |
| `SENSOR_CONSOLE_ID` | `console_id` | Console IDPS key |

---

## Roadmap

- [ ] Klog: add "tail N lines" on connect, regex filter, copy/download/pause buttons
- [ ] Dashboard tab: show currently playing game card with cover art
- [ ] PKG install workflow: upload PKG to HA and deliver to PS4
- [ ] Diagnostics: connection health card in HA device page
- [ ] Unit tests for WebSocket schemas and `KlogStateMachine`
- [ ] HACS default repository submission

---

## Development Notes

- Keep WebSocket message shapes stable — prefer the HA `event` envelope for streams.
- All entry teardown goes through `async_unload_entry` which cancels both `klog_task` and `db_task`.
- `db.py` uses only stdlib (`ftplib`, `sqlite3`, `tempfile`) — no extra dependencies.
- `_poll_ftp_json` is the single point that merges FTP telemetry into coordinator data. All new sensor keys from `ps4_state.json` should be parsed and stored here, then exposed via a `CoordinatorEntity` in `sensor.py`.
- `_parse_klog_line` handles game state only — do not route telemetry through klog.
- The `KlogStateMachine` uses a priority-ordered signal chain — do not reorder the match blocks.
- Poll interval is controlled by `_FTP_POLL_INTERVAL` in `__init__.py` (currently `timedelta(seconds=3)`). All sensors share this single coordinator interval.
- Diagnostic sensors (`fw_version`, `hw_model`, `console_id`) are static for the session — they are written by the PRX on every JSON update but should not be used in high-frequency automations.
