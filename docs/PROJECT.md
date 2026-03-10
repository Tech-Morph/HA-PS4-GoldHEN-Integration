# HA-PS4-GoldHEN-Integration — Project Reference

Home Assistant custom integration (HACS) to control and monitor a PS4 running GoldHEN network services.

---

## Goals

- Provide a clean HA sidebar panel for PS4 tools: FTP browser, BinLoader payload sender, live Klog viewer, and a GoldHEN Dashboard.
- Expose useful HA sensor entities: current game (with resolved names), FTP online status, and CPU temperature.
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
| `__init__.py` | Integration setup, `KlogStateMachine`, `_klog_listener_task`, `_db_refresh_task`, FTP HTTP views, WebSocket registrations, payload service |
| `sensor.py` | `PS4CurrentGameSensor`, `PS4FTPStatusSensor`, `PS4CPUTempSensor` — all `CoordinatorEntity` |
| `db.py` | FTP download of `app.db`, SQLite parse, game map builder (`download_and_parse`) |
| `button.py` | Button platform entities |
| `config_flow.py` | UI config flow for host/port setup |
| `const.py` | All constants: domain, port defaults, sensor keys, file paths, intervals |
| `websocket.py` | All WebSocket command handlers: FTP list/delete/rename/mkdir/get_text/put_text, klog_subscribe |
| `title_resolver.py` | Optional remote fallback: resolves CUSA title IDs via Sony TMDB2 / ver.xml |

---

## Data Flow

### Klog → Sensor
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

---

## Sensor Entities

### `sensor.ps4_goldhen_current_game`
- **State:** Resolved game name from `app.db`, or `PlayStation Home Screen`, `Rest Mode`, `Off`
- **Attributes:** `title_id`, `game_name`, `game_cover`, `state_classification`, `pi_state`, `klog_connected`, `state_reason`, `pending_title_id`, `state_signal_line`

### `sensor.ps4_goldhen_ftp_status`
- **State:** `online` / `offline`
- TCP probe to FTP port every 30 seconds

### `sensor.ps4_goldhen_cpu_temperature`
- **State:** Float °C
- Parsed live from klog stream

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
- `_parse_klog_line` is the single point that merges klog state machine output with the game map. Any new sensor data from klog should flow through here.
- The `KlogStateMachine` uses a priority-ordered signal chain — do not reorder the match blocks.
