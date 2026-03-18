# PS4 GoldHEN — Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
![version](https://img.shields.io/badge/version-0.9.0-blue)
![HA](https://img.shields.io/badge/Home%20Assistant-2024.1%2B-brightgreen)
![license](https://img.shields.io/github/license/Tech-Morph/HA-PS4-GoldHEN-Integration)
[![Ko-fi](https://img.shields.io/badge/Support%20Me-Ko--fi-FF5E5B?style=flat-square&logo=ko-fi&logoColor=white)](https://ko-fi.com/techmorph)

A fully local Home Assistant integration and sidebar panel for managing a **PS4 running GoldHEN** network services — no cloud, no polling services, no extra dependencies.

[![Add to HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Tech-Morph&repository=HA-PS4-GoldHEN-Integration&category=integration)

---

## ✨ Features

### 🎮 Sensors

| Entity | Description |
|---|---|
| **Current Game** | Resolved game title from the PS4's `app.db` (e.g. `God of War`) — falls back to Title ID if DB hasn't loaded yet. State reflects `Rest Mode`, `Off`, or `PlayStation Home Screen` automatically. |
| **FTP Status** | `online` / `offline` based on polling the PS4 FTP port every 5 seconds. |
| **CPU Temperature** | Real-time CPU die temp polled from `ps4_state.json` via FTP every 5 seconds (°C). Requires the PS4StateJSON PRX plugin — see below. |
| **SoC Temperature** | Real-time SoC board temp polled from `ps4_state.json` via FTP every 5 seconds (°C). Requires the PS4StateJSON PRX plugin — see below. |
| **SoC Power** | SoC power draw in watts (e.g. `13.2`), polled from `ps4_state.json`. |
| **CPU Power** | CPU power draw in watts, polled from `ps4_state.json`. |
| **GPU Power** | GPU power draw in watts, polled from `ps4_state.json`. |
| **Total Power** | Total system power draw in watts, polled from `ps4_state.json`. |

> **Note:** Temperature and power sensors will show `unknown` until `ps4_state.json` is successfully fetched. They update every 5 seconds while the PS4 is on and the PRX is loaded.

---

#### PS4StateJSON PRX Setup

To enable temperature, power, and fan sensors, install the **PS4StateJSON** PRX as a GoldHEN plugin. This replaces the older `SysInfo.prx` approach — telemetry is now written to a JSON file on the PS4 filesystem and polled by HA over FTP rather than parsed from klog.

**Build from source:**

```bash
cd ~/ps4_tools/PS4StateJSON && make && \
  curl -T PS4StateJSON.prx ftp://<PS4_IP>:2121/data/GoldHEN/plugins/PS4StateJSON.prx
```

**Install:**

1. Copy `PS4StateJSON.prx` to `/data/GoldHEN/plugins/` on your PS4 (via FTP).
2. Create or edit `/data/GoldHEN/plugins/plugin.ini` to include:

```ini
[default]
/data/GoldHEN/plugins/PS4StateJSON.prx
```

3. Cold boot the PS4. The PRX starts a background thread that writes telemetry to `/data/GoldHEN/ps4_state.json` every 10 seconds:

```json
{
  "cpu_temp": 71,
  "soc_temp": 70,
  "fan_duty": 191,
  "soc_power_w": 13.2,
  "cpu_power_w": 1.2,
  "gpu_power_w": 11.5,
  "total_power_w": 20.9,
  "fw_version": "0.0-prototype",
  "sdk_version": "0x11008001",
  "hw_model": "DG1000FGF84HT",
  "tick": 1
}
```

HA polls this file via FTP every **5 seconds** and merges the values into the coordinator — no klog dependency for telemetry.

The PRX also manages the PS4 fan curve automatically based on die temperature:

| Die Temp | Fan Duty |
|---|---|
| < 60°C | 45% |
| ≥ 60°C | 60% |
| ≥ 65°C | 75% |
| ≥ 72°C | 85% |
| ≥ 78°C | 95% |

---

#### Current Game — Extra Attributes

| Attribute | Value |
|---|---|
| `title_id` | Raw PS4 Title ID (e.g. `CUSA12345`) |
| `game_name` | Resolved name from `app.db` |
| `game_cover` | Cover art URL from `app.db` |
| `state_classification` | `game` / `home_screen` / `rest` / `off` |
| `pi_state` | Raw state from your Pi REST sensor |
| `klog_connected` | Whether the klog stream is live |
| `state_reason` | Which klog signal last triggered a state change |
| `pending_title_id` | Title ID seen in launch signal, not yet confirmed |
| `state_signal_line` | The raw klog line that caused the last state change |

---

### 🗂️ Sidebar Panel (GoldHEN Dashboard)

A full web-component panel added to your HA sidebar with four tabs:

#### FTP Browser
- Browse the full PS4 filesystem
- Upload files from your PC/phone directly to the PS4
- Download files from the PS4 to your browser
- Delete files and folders
- Rename and move files
- Edit small text files in-browser (read/write)

#### BinLoader
- Lists all `.bin` / `.elf` payloads from `/config/ps4_payloads/`
- Send any payload over raw TCP to the PS4 BinLoader port with one click
- Bundled payloads are automatically copied to `/config/ps4_payloads/` on first run

#### Klog Viewer
- Live streaming PS4 kernel/app log output in the panel
- Auto-connects when you open the tab
- Disconnects cleanly on tab switch or panel close
- Backend holds the klog connection — the UI subscribes via HA WebSocket so you never lose logs while the panel is closed

#### Game Library (app.db)
- Automatically downloads `app.db` from the PS4 over FTP on startup
- Parses all installed titles and icons, populating the `Current Game` sensor with real names
- Refreshes on a configurable interval (default: 1 hour)

---

### ⚙️ Service

`ps4_goldhen.send_payload` — Send any payload file to the PS4 BinLoader port.

```yaml
service: ps4_goldhen.send_payload
data:
  payload_file: GoldHEN.bin      # filename inside /config/ps4_payloads/ or absolute path
  ps4_host: 192.168.1.100        # optional override
  binloader_port: 9090           # optional override
  timeout: 30                    # optional, seconds
```

---

## 📋 Requirements

- **PS4** on your LAN running **GoldHEN** with network services enabled
- **Home Assistant** 2024.1 or newer
- **HACS** installed in Home Assistant
- GoldHEN services enabled:
  - FTP (default port `2121`)
  - BinLoader (default port `9090`)
  - Klog / Debug Log Server (default port `3232`)
- *(Optional)* A Raspberry Pi or other device running a REST sensor at `sensor.ps4_state_pi` reporting `on` / `rest` / `offline` for accurate power state detection — see [PS4 State Monitor](https://github.com/Tech-Morph/PS4-State-Monitor)
- *(Optional)* `PS4StateJSON.prx` GoldHEN plugin for temperature, fan, and power sensors — see [PS4StateJSON PRX Setup](#ps4statejson-prx-setup)

---

## 🚀 Installation

### Method 1 — HACS (Recommended)

1. Click the button below to open HACS and add this repository:

   [![Add to HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Tech-Morph&repository=HA-PS4-GoldHEN-Integration&category=integration)

   Or manually: **HACS → Integrations → ⋮ → Custom Repositories** → add `Tech-Morph/HA-PS4-GoldHEN-Integration` as type `Integration`.

2. Search for **PS4 GoldHEN** in HACS and click **Download**.
3. **Restart Home Assistant.**
4. Go to **Settings → Devices & Services → Add Integration** → search **PS4 GoldHEN**.
5. Fill in the config form (see below).

### Method 2 — Manual

1. Download or clone this repository.
2. Copy the `custom_components/ps4_goldhen` folder into your HA `config/custom_components/` directory.
3. Restart Home Assistant.
4. Go to **Settings → Devices & Services → Add Integration** → search **PS4 GoldHEN**.

---

## 🔧 Configuration

All configuration is done via the UI config flow. No `configuration.yaml` editing required.

| Field | Default | Description |
|---|---|---|
| **PS4 Host / IP** | — | LAN IP address of your PS4 |
| **FTP Port** | `2121` | GoldHEN FTP server port |
| **BinLoader Port** | `9090` | GoldHEN BinLoader TCP port |
| **Klog Port** | `3232` | GoldHEN debug log server port |
| **RPI Port** | `8080` | Port of your optional Pi REST sensor |

You can configure **multiple PS4 consoles** — add the integration again for each one.

---

## 📂 Payload Directory

Payloads are stored in `/config/ps4_payloads/` on your HA instance. Any `.bin` or `.elf` file placed here will appear in the BinLoader tab and be available to the `send_payload` service.

Bundled payloads included with the integration are copied here automatically on first run.

---

## 📡 Power State Detection

The **Current Game** sensor uses a two-source logic for power state:

1. **`sensor.ps4_state_pi`** — If you have a Pi (or any device) exposing a REST sensor at this entity ID with states `on` / `rest` / `offline`, the integration uses it to detect Rest Mode and powered-off states cleanly.
2. **klog stream** — When the PS4 is `on`, the klog state machine tracks foreground app changes in real time via multiple signal patterns (`[SL] AppFocusChanged`, `[BGFT] GameWillStart`, `GameStopped`, etc.).

If you don't have a Pi sensor, the integration still works — it will track game state from klog and assume `on` when klog is connected.

---

## 🌡️ Telemetry Architecture

Temperature and power data no longer depend on klog. Instead:

1. **PS4StateJSON.prx** runs as a GoldHEN plugin on the PS4, writing `/data/GoldHEN/ps4_state.json` every 10 seconds.
2. **Home Assistant** polls this file over FTP every **5 seconds** using a raw async PASV FTP connection.
3. Values are merged directly into the coordinator data and pushed to all sensor entities immediately.

This means sensors update even on the PS4 home screen (not just while a game is running), and telemetry is no longer lost if the klog connection drops or reconnects.

The PRX also implements an **automatic fan curve** — it reads die and board temperatures every 10 seconds and adjusts the fan duty cycle via syscall 532, overriding GoldHEN's default fan management.

---

## 🎮 Game Title & Art Resolution

On startup (and every hour by default), the integration:

1. Connects to the PS4 over FTP
2. Downloads `app.db` from `/system_data/priv/mms/app.db`
3. Parses the installed app library using SQLite
4. Builds an in-memory game map: `{ CUSA12345: { name: "...", cover: "..." } }`

This map populates `sensor.ps4_goldhen_current_game` with human-readable game names and drives the `game_name` / `game_cover` attributes. If the PS4 is offline at startup, the sensor falls back to the raw Title ID and retries on the next refresh cycle.

---

## 🔍 Troubleshooting

### Sensors show `unavailable` after install
- Fully restart HA after installation, not just a reload.
- Check **Settings → System → Logs** and filter for `ps4_goldhen`.

### Current Game shows Title ID instead of game name
- The PS4 may have been offline when HA started — wait for the next hourly refresh, or restart HA with the PS4 on.
- Check HA logs for `app.db` — table names and row counts are logged at startup.

### Temperature / power sensors show `unknown`
- `PS4StateJSON.prx` must be installed as a GoldHEN plugin — see [PS4StateJSON PRX Setup](#ps4statejson-prx-setup).
- Confirm the file exists on the PS4:
  ```bash
  curl -s ftp://<PS4_IP>:2121/data/GoldHEN/ps4_state.json
  ```
- If the file is missing, the PRX may not have loaded — check `plugin.ini` and confirm a **cold boot** was performed (not just a GoldHEN reload).

### Power values look wrong
- Power sensors now report in **watts** (e.g. `13.2 W`), not milliwatts. Update any existing automations or dashboard cards that referenced the old milliwatt values.

### FTP not working
- Confirm GoldHEN FTP is enabled and the PS4 is reachable on the configured port.
- GoldHEN FTP is unauthenticated — do not set credentials.

### Klog not streaming
- Only one client can connect to the GoldHEN klog port at a time — make sure nothing else (e.g. `nc`) is consuming it.
- The HA backend holds the klog connection persistently; the panel UI subscribes via WebSocket and does not connect directly.

### BinLoader send says success but nothing happens
- Confirm BinLoader is enabled in GoldHEN settings.
- Verify the PS4 host and port in the integration config.

---

## 🤝 Contributing

PRs are welcome. Please:
- Keep WebSocket message schemas consistent with existing handlers.
- Ensure all async tasks and subscriptions clean up on unload.
- Prefer `async` I/O — avoid blocking calls on the event loop.
- Test with at least one real or mocked PS4 FTP/klog endpoint.

---

## 💛 Support

If this integration saves you time or brings value to your setup, consider supporting development:

[![Ko-fi](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-Ko--fi-FF5E5B?style=for-the-badge&logo=ko-fi&logoColor=white)](https://ko-fi.com/techmorph)

---

## 📄 License

MIT — see [LICENSE](LICENSE).
