# PS4 GoldHEN development reference

<!-- ps4state-not-working -->
> [!WARNING]
> `PS4StateJSON.prx` (the PS4State plugin) is under active development and is **not** currently in working order. Do not install or enable it.
>
> The Home Assistant integration works independently of this plugin. Temperature, power, fan, and hardware telemetry should remain unknown without a working, validated producer. The connection repair does not fix or validate this PRX, its firmware compatibility, fan control, audio, or game-saving behavior.
<!-- /ps4state-not-working -->

This file describes the repaired development working tree, not necessarily the published HACS release. Component manifest version: `0.9.0`. Source behavior takes precedence over older documentation and unrelated native-plugin archives.

## Architecture

| File | Responsibility |
|---|---|
| `__init__.py` | Setup/unload, coordinator, klog state machine/listener, database tasks, panel/static registration, FTP/cover HTTP views, and payload service |
| `config_flow.py` | Host/FTP/BinLoader form and bounded setup/options TCP probe |
| `ftp_telemetry.py` | HA-independent, bounded read-only FTP telemetry transport and defensive parser |
| `ftp_listing.py` | MLSD-first directory listing and explicit UTC modification-time contract |
| `websocket.py` | FTP command handlers and entry-filtered raw-klog HA-bus subscriptions |
| `sensor.py` | Current-game, FTP-status, optional telemetry, and diagnostic entities |
| `db.py` | Executor-based FTP app.db download, shared local cache, SQLite title/cover map |
| `button.py` | Restart/Standby wrappers referring to unbundled files; not validated power controls |
| `frontend/ps4-goldhen-panel.js` | Three tabs: FTP, Payloads, Klog; subscription overlap/stale-callback guards |
| `title_resolver.py` | Dormant remote-lookup code; not used by the active name-resolution path |
| `services.yaml` | Metadata for the registered send_payload service only |

The backend owns one klog listener per config entry; the repaired UI subscribes through HA events, never through a second PS4 socket. Raw stream events are distinct from parsed/game-state events. Unsubscribing a panel leaves the backend listener running; no history replay is provided. Entry unload cancels klog/database tasks, but failure/unload/global-registration lifecycle is not fully hardened.

## Configuration and paths

| Constant/contract | Value | Notes |
|---|---|---|
| `DOMAIN` | `ps4_goldhen` | Component directory/service domain |
| `DEFAULT_FTP_PORT` | `2121` | Exposed in setup/options |
| `DEFAULT_BINLOADER_PORT` | `9090` | Exposed; not probed during setup |
| `DEFAULT_KLOG_PORT` | `3232` | Backend default; no current form field |
| `DEFAULT_RPI_PORT` | `12800` | Remote Package Installer default, not a Pi REST port; installation API unimplemented |
| `TCP_PROBE_TIMEOUT` | `3.0` seconds | Setup TCP connect timeout; cleanup is separately bounded |
| `_FTP_POLL_INTERVAL` | `5` seconds | Nominal coordinator interval, not producer sampling frequency |
| `DB_REFRESH_INTERVAL` | `300` seconds | Sleep after each background DB-refresh attempt |
| `PAYLOAD_DIR` | `/config/ps4/payloads` | Shared HA directory |
| `DB_CACHE_DIR` | `/config/ps4/db` | Shared, not per-console |
| `APP_DB_LOCAL` | `/config/ps4/db/app.db` | Shared cache |
| `COVER_CACHE_DIR` | `/config/ps4/covers` | Shared by title ID |
| `APP_DB_REMOTE` | `/system_data/priv/mms/app.db` | Falls back to `.bak` |
| `_PS4STATE_JSON_PATH` | `/data/GoldHEN/ps4_state.json` | Optional telemetry input |
| GoldHEN plugin config | `/data/GoldHEN/plugins.ini` | Preserve unrelated rules; not needed for base setup |
| External power-state entity | `sensor.ps4_state_pi` | Optional user-managed on/rest/offline source, shared across entries |

## Setup and telemetry transport

The form probes FTP TCP reachability without querying firmware, PSN, or BinLoader. The first coordinator refresh attempts optional telemetry and returns transport/measurement health separately. Missing or invalid telemetry must not prevent setup. Klog and database workers are scheduled after that refresh, independently of the presence of valid telemetry.

`TelemetryResult` contains `ftp_reachable`, `values`, and `status`. Reachability means this request completed anonymous FTP authentication; it is not an independent persistent-health monitor. After authentication, a passive/data I/O error preserves that successful control-authentication result. FTP Status exposes `telemetry_status` as an attribute without changing its unique ID.

Transport defaults:

- One-second per-operation timeouts; four-second transfer deadline.
- At most 0.15 seconds of close waiting per writer after transfer/cancellation.
- A maximum JSON body of 65,536 bytes.
- Greeting/multiline, USER/PASS, TYPE, PASV, RETR acceptance, and final completion validation.
- Passive data connections use the control peer address, not an arbitrary advertised host.
- Cleanup closes control/data writers and propagates external cancellation.
- Missing/rejected requests become `ftp_<code>`; malformed JSON (including parser recursion errors) becomes `invalid_json`.

The setup/options TCP probe separately bounds close waiting. Telemetry timeout limits do not establish deadlines for app.db, cover fetching, browser file operations, or payload sending.

## Data contracts

Recognized legacy numeric keys are `cpu_temp`, `soc_temp`, `soc_power_w`, `cpu_power_w`, `gpu_power_w`, `total_power_w`, and `fan_duty`. Diagnostic keys are `fw_version`, `hw_model`, and `console_id`. The HA consumer displays legacy temperature keys as °C, power keys as W, and fan duty as percent; physical calibration is the native producer's unresolved responsibility.

Parser checks accept finite, nonboolean measurements within defensive limits: temperatures 1–150, power 0–1000, fan duty 0–100. These are not API unit conversions, physical-sensor certification, or evidence that overlapping power rails form an accurate total. Diagnostics are string inputs capped at 128 characters.

Failed/invalid fetches clear dynamic readings. Static diagnostics may remain cached. A nonempty object must contain a recognized field; accepted JSON can still contain null/invalid measurements. `ok` therefore does not mean all measurements are valid, current, or physically accurate. Legacy sequence/timestamp/frozen-file expiry is absent.

The wrapper snapshots klog state after awaiting the fetch so it does not overwrite concurrent game updates. Do not treat a passive `550`, missing key, matching version string, or shared binary filename as proof of native plugin presence/load/identity.

## FTP listing and UI contracts

MLSD `modify` fields are parsed as UTC with optional fractional seconds. The panel converts explicit timestamps to browser-local time. Fallback LIST dates stay verbatim because year/timezone may be ambiguous. Fallback is limited to explicit unsupported-command replies 500/501/502/504; permission and transport errors are not hidden through fallback.

The panel escapes FTP table/editor content. That scoped repair is not a complete audit of all innerHTML, permission checks, routes, or transfer limits. Raw-klog events are limited to 8,192 characters per line and an unfinished listener line is bounded to 65,536 characters. Frontend generations and connection guards suppress overlapping or obsolete subscriptions.

WebSocket commands:

- `ps4_goldhen/list_entries`
- `ps4_goldhen/list_payloads`
- `ps4_goldhen/ftp_list_dir`
- `ps4_goldhen/ftp_delete`
- `ps4_goldhen/ftp_rename`
- `ps4_goldhen/ftp_mkdir`
- `ps4_goldhen/ftp_get_text`
- `ps4_goldhen/ftp_put_text`
- `ps4_goldhen/klog_subscribe`

HTTP endpoints are FTP download (GET), FTP upload (POST multipart), and cover GET at `/api/ps4_goldhen/cover/{entry_id}/{title_id}`. FTP views require HA authentication. The legacy cover view does not; title/path validation and authorization policy still need review. Known cover metadata can redirect to external CDN URLs.

## Payload and native boundaries

Only `ps4_goldhen.send_payload` is registered. It uses a global handler that captures setup defaults; multi-console callers should provide both host and BinLoader port. The current buttons do not do this. `restart.bin`/`standby.bin` are absent from the bundled resources. PKG/RPI/etaHEN/PS5 installation is not implemented.

Sending bytes is not confirmed payload execution. Legacy absolute/relative payload-path handling is not fully restricted to a safe root. Resource copying is nonexecuting, skips existing destination names, and does not remove previously copied resources when a bundled file is removed later.

PS4StateJSON is a separate native producer under repair. This HA connection repair does not change/validate PRX APIs, private output layouts, privilege operations, thread lifetime, fan control/restoration, or audio/game saving. Title-loaded PRX lifetime does not prove home-screen telemetry. Preserve unrelated plugins.ini rules and original native projects.

## Validation and open work

Five Python suites contain 56 tests: FTP telemetry 17, issue connection 13, shared klog 8, full-module FTP handlers 7, listings 11. Separate Node syntax and two assertion scripts cover frontend behavior. Test counts describe the current development tree, not future versions or a full HA/native compatibility suite.

Issue-connection tests use loopback sockets and import the complete integration module with HA interfaces stubbed. Setup tests record worker creation and skip live worker/frontend/platform behavior. Existing suites also use mocks and selected-function extraction. Keep these limits explicit.

Reported October 2 evidence: all 56 tests passed on the Pi; the owner's live FTP control operations and bounded telemetry rejection passed. The owner subsequently reported verified installed transport/sensor hashes, working FTP/klog/payload functionality, successful offline HA startup, and recovery when services returned. Fresh new-entry configuration and firmware 9.00 reporter validation remain pending. FTP 550 is not successful JSON publication or measurement validation, and reported payload functionality is not a firmware/provenance certification.

Remaining work includes frozen telemetry expiry, safe producer firmware matrix, payload targeting/path policies, cache isolation, entity-identity migration, authorization/routes/large transfers, DB refresh single-flight, setup/unload cleanup, and full HA/browser/runtime tests. Do not mark these completed through documentation changes.

[README](../README.md) · [development changelog](CHANGELOG.md)
