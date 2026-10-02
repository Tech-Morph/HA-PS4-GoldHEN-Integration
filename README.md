# PS4 GoldHEN — Home Assistant Integration

<!-- ps4state-not-working -->
> [!WARNING]
> `PS4StateJSON.prx` (the PS4State plugin) is under active development and is **not** currently in working order. Do not install or enable it.
>
> The Home Assistant integration works independently of this plugin. Temperature, power, fan, and hardware telemetry should remain unknown without a working, validated producer. The connection repair does not fix or validate this PRX, its firmware compatibility, fan control, audio, or game-saving behavior.
<!-- /ps4state-not-working -->

A Home Assistant custom integration and sidebar panel for a PS4 running GoldHEN network services. FTP and klog provide the base features; native PS4StateJSON telemetry is optional and under separate repair.

[Add this repository to HACS](https://my.home-assistant.io/redirect/hacs_repository/?owner=Tech-Morph&repository=HA-PS4-GoldHEN-Integration&category=integration)

## Repair status

The connection, klog, and FTP-listing repairs described here are development work, not a claim that published releases already contain them. Check the installed files/revision before following repair-specific instructions. The component manifest currently declares version `0.9.0`; there is no separate `1.0.0` release claim in this documentation.

Current evidence as of October 2, 2026:

- 56 Python tests and the frontend syntax/assertion checks passed on the development host.
- A controlled local FTP server reproduces the old setup hang when `RETR` returns `550` but the passive socket stays idle; the repaired transport returns a result instead of waiting indefinitely.
- Owner-reported checks on firmware 11.00: installed transport/sensor hashes matched; FTP, klog, and payload functionality worked; offline HA startup and recovery passed. A separate Pi probe authenticated FTP and returned a bounded `ftp_550`. This does not establish successful telemetry retrieval, native measurements, or firmware 9.00 compatibility.
- Issue #1 reported firmware 9.00 and Home Assistant 2026.8. Reporter validation of the repair remains pending.
- Native sensor APIs, fan control, PRX firmware compatibility, audio, game saving, and frozen legacy telemetry detection are not validated by the connection repair.

See [development reference](docs/PROJECT.md) and [development changelog](docs/CHANGELOG.md).

## Requirements and compatibility

To add the integration, GoldHEN must be running and its configured FTP TCP port must be reachable. The setup flow does not ask for a PSN/Second Screen pairing code, inspect a firmware version string, or probe BinLoader.

| Feature | Required PS4 capability | Default port |
|---|---|---|
| Initial connection, FTP browser, local app database download | GoldHEN FTP with anonymous login | `2121` |
| Game-state parsing and live logs | GoldHEN klog/debug log server | `3232` |
| Explicit payload sending | GoldHEN BinLoader and a separately validated payload | `9090` |
| Temperature/power/fan/hardware data | Validated producer exporting the legacy JSON contract through FTP | FTP port |

PS4StateJSON, fan-control plugins, and BinLoader are not prerequisites for initial setup. Enable each optional service only for the feature you need.

The network transport has no firmware-offset table. Protocol-based connection behavior is separate from native plugin/payload compatibility; there is no all-firmware certification. No minimum Home Assistant version is certified by this repair. Earlier repairs were observed on the owner's HA 2026.9.4 installation; test the latest patch on your actual HA installation before declaring it supported.

An optional external `sensor.ps4_state_pi` reporting `on`, `rest`, or `offline` improves power-state classification. Without it, do not assume reliable powered-off versus Rest Mode classification from klog alone. See [PS4 State Monitor](https://github.com/Tech-Morph/PS4-State-Monitor).

## Installation and configuration

### HACS

1. Add `Tech-Morph/HA-PS4-GoldHEN-Integration` as an Integration custom repository.
2. Download PS4 GoldHEN and restart Home Assistant.
3. Open Settings → Devices & Services → Add Integration → PS4 GoldHEN.
4. Enter the PS4 host, FTP port, and BinLoader port.

A HACS download/update is not a way to obtain unpublished workbench patches. It may overwrite manually installed test code.

### Manual installation

Copy `custom_components/ps4_goldhen` from the intended revision into your HA configuration's `custom_components` directory, preserving a backup of existing code. Restart Home Assistant, then add the integration through the UI. For HA OS, manage Core from its Terminal & SSH app; do not substitute commands intended for the separate development host.

| UI field | Default | Used for |
|---|---|---|
| PS4 IP Address | Enter your LAN address | Console connection |
| FTP Port | `2121` | Setup TCP check and FTP operations |
| BinLoader Port | `9090` | Explicit payload sending; not probed during setup |

Klog and RPI ports are not exposed by the current setup/options form. The backend defaults are klog `3232` and RPI `12800`; RPI denotes Remote Package Installer, not a Raspberry Pi REST sensor. PKG installation is not implemented.

Multiple entries may be added, but multi-console behavior is not fully isolated: app.db/cover caches are shared, and payload/button targeting has known limitations. Changing a host can also affect host-based entity identity.

## Features and limits

### Sidebar panel

The current panel has three tabs: FTP, Payloads, and Klog. There is no separate Game Library or Dashboard tab.

- FTP: browse directories, download/upload files, rename, delete, and edit text. Delete handles files or empty directories, not recursive directory deletion. Large file/text operations are not fully streaming or strictly size-bounded.
- Payloads: list `.bin`/`.elf` files from HA's `/config/ps4/payloads` and explicitly send them to BinLoader. A transfer success message confirms bytes sent, not execution or firmware compatibility.
- Klog: subscribe to the integration's raw log events. The repaired backend owns one PS4 klog connection per entry; opening more HA panel subscriptions does not create extra PS4 sockets. Leaving the tab removes the UI subscription, not the backend listener. No history replay is implemented; the panel keeps up to 800 received lines locally.

Close external klog consumers when testing the HA backend. A panel subscription label alone does not prove that the PS4 TCP connection is live; received lines are the evidence.

### FTP dates and game metadata

Directory listing prefers MLSD facts. Explicit MLSD modification timestamps are interpreted as UTC and displayed in the browser's local timezone. LIST fallback is used only when MLSD is explicitly unsupported; its ambiguous date strings are preserved without invented years or timezones. Differences between the server's LIST and MLSD years are not corrected cosmetically.

The integration downloads `/system_data/priv/mms/app.db` at background-task startup and then every 300 seconds, after each refresh attempt completes. It resolves names locally and falls back to title IDs while metadata is unavailable. There is no Game Library UI. The included `title_resolver.py` is not wired into this active path.

The active title-name path uses the local database. Known cover URLs from that database can redirect the browser to an external CDN; do not describe all cover rendering as cloud-free. Without a known CDN cover or cached icon, the current-game sensor uses the PlayStation icon fallback.

### Sensor contract

| Entity group | Source and limitations |
|---|---|
| Current Game | Klog state machine with app.db name lookup; Rest/Off overrides depend on the external Pi-state entity |
| FTP Status | `online` after successful FTP authentication, independently of optional telemetry; includes `telemetry_status` |
| CPU/SoC Temperature | Optional legacy `cpu_temp`/`soc_temp`, displayed as °C; physical labels/scaling need producer validation |
| SoC/CPU/GPU/Total Power | Optional legacy watt keys; rail layout and total aggregation are not calibrated system-meter measurements |
| Fan Duty | Optional percentage supplied by the producer; not RPM or proof of measured physical fan speed |
| Firmware/Hardware/Console ID | Optional diagnostic strings from the producer; not independently measured by HA |

Numeric bounds are defensive parser checks, not calibration. Failed/invalid telemetry reads clear dynamic measurements to unknown; static diagnostic values may remain cached. A successful read of a frozen legacy file can still show old values: freshness expiry is not implemented. Avoid publishing console identifiers from diagnostic output.

## Optional telemetry and plugin configuration

HA polls `/data/GoldHEN/ps4_state.json` on a nominal five-second coordinator interval. Producer publication frequency is a separate property and is not changed by this patch.

The transport validates the FTP greeting, anonymous login, binary mode, passive response, transfer acceptance, and completion. Defaults are one second per bounded operation, a four-second transfer deadline, up to 0.15 seconds of close waiting per socket after transfer/cancellation, and a 65,536-byte telemetry limit. External cancellation propagates. The setup TCP probe has a separate three-second connect timeout and bounded cleanup. These limits do not apply to every FTP browser/database/payload operation.

| `telemetry_status` | Meaning |
|---|---|
| `ok` | A recognized JSON object was fetched and parsed; not proof of valid/fresh measurements |
| `ftp_550` | Server rejected a request with FTP 550; with authenticated FTP, this does not block the base integration |
| `invalid_json` | Retrieved data could not satisfy the parser contract |
| `timeout` | A bounded transport operation/deadline expired; check `ftp_reachable` separately |
| `connection_error` | An I/O/connection failure; check `ftp_reachable` separately |
| `protocol_error` | Malformed protocol data, size-limit violation, or another transport validation failure |
| Other `ftp_<code>` | An FTP response was rejected at the relevant protocol step |

`ftp_550` does not prove the file is absent. Missing files, access restrictions, or other server-side rejection reasons need separate evidence. Do not delete or rename an existing telemetry file to manufacture a test case.

The correct GoldHEN configuration path is `/data/GoldHEN/plugins.ini`; plugin binaries may reside in `/data/GoldHEN/plugins/`. Preserve unrelated title sections/rules. Initial HA setup does not require editing that file. Editing a rule does not prove an already loaded plugin has unloaded.

Historical PS4StateJSON builds include fan and privilege-related behavior under investigation. Do not enable or distribute an old binary as a workaround for an HA setup timeout. A title-loaded PRX is not evidence of continuous home-screen sampling. Native producer deployment, API validation, and audio/save testing remain a separate project.

## Payload service and buttons

The registered payload service is `ps4_goldhen.send_payload`. Use a payload whose source, checksum, firmware target, and behavior you have independently reviewed. Nothing is sent automatically by the connection repair.

Example of the service shape only; `your-reviewed-payload.bin` is not a supplied file:

```yaml
action: ps4_goldhen.send_payload
data:
  payload_file: your-reviewed-payload.bin
  ps4_host: 192.168.1.100
  binloader_port: 9090
  timeout: 30
```

A bare filename is resolved under `/config/ps4/payloads`; the legacy implementation also accepts absolute paths and has no complete safe-root policy. In multi-console setups, provide both host and BinLoader port explicitly rather than trusting the global default. The timeout bounds TCP connect/drain operations, not the complete file-read/transfer/close lifetime.

Bundled resources are copied to HA's payload directory during integration setup if a destination filename is absent. Existing files are not overwritten and no payload is executed merely by copying. The connection repair does not certify the bundled binaries; see [payload inventory](custom_components/ps4_goldhen/bundled_payloads/README.md).

Restart and Standby buttons reference `restart.bin` and `standby.bin`, which are not bundled. Their service calls also lack an explicit console target. Do not describe them as working, validated power controls. `ps4_goldhen.install_pkg` is not registered/implemented; RPI/etaHEN/PS5 installation is not a supported feature.

## Troubleshooting and validation

- Setup cancelled while fetching telemetry: confirm that the installed revision contains the bounded helper. Do not change firmware, send a payload, or install a PRX to fix the HA transport.
- FTP Status online with `ftp_550`: FTP authenticated, but the request was rejected. Unknown dynamic telemetry is expected; inspect the actual server response before diagnosing producer state.
- Connection error with FTP offline: check the actual IP, enabled GoldHEN FTP service, and configured port; obtain the underlying connection/banner/login exception before changing code.
- Current Game shows a title ID: metadata may not have loaded. Check app.db logs and the five-minute background refresh; the shared cache is not per-console isolation.
- Klog subscribed but no lines: verify received output, backend connection logs, and competing external clients. UI subscription is not a TCP connectivity test.
- Wrong-looking FTP year: compare explicit MLSD facts with LIST. Do not rewrite server-provided years to the current year.
- Unknown temperature/power/fan data: the optional producer may be unavailable, invalid, or unvalidated. Key counts and common version strings do not establish binary identity.

For public reports, include HA version, integration revision/file hashes, firmware, exact GoldHEN build, telemetry status, and relevant logs with identifiers/credentials redacted. Do not expose FTP/BinLoader/klog externally. The current integration is not fully security-hardened: authorization policy, large transfers, cache isolation, cover routes, and payload path validation remain review items.

Run the local suites from the development repository:

```bash
python3 -B tests/test_ftp_telemetry.py
python3 -B tests/test_issue1_connection.py
python3 -B tests/test_klog_shared.py
python3 -B tests/test_websocket_ftp_runtime.py
python3 -B tests/test_ftp_listing.py
node --check custom_components/ps4_goldhen/frontend/ps4-goldhen-panel.js
node tests/test_klog_frontend.cjs
node tests/test_ftp_listing_frontend.cjs
git diff --check
```

These use mocks/stubs and loopback sockets, not a complete Home Assistant test environment or native PS4 compatibility suite. Owner-reported HA deployment, offline startup, and recovery checks passed. Fresh new-entry configuration and reporter firmware 9.00 validation remain separate checks. Preserve code/config backups and test rollback before production rollout.

## Support and license

[Support Tech-Morph](https://ko-fi.com/techmorph). MIT license; see [LICENSE](LICENSE).
