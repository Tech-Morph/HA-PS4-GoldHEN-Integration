# PS4 GoldHEN — Home Assistant Integration

> [!WARNING]
> I'm still working on `PS4StateJSON.prx` (PS4State). It is **not** working yet. Do not install or enable it.
>
> FTP, klog, and payload sending don't need the plugin. Temperature, power, fan, and hardware telemetry still need a working plugin before those readings can be relied on.

I built this to bring my GoldHEN PS4 into Home Assistant without needing a Second Screen pairing code. It adds file browsing, payload sending, live logs, and sensors for FTP status and the current game.

See the [changelog](docs/CHANGELOG.md) for changes and the [project notes](docs/PROJECT.md) for the backend details. If you're testing a fix from an issue or PR, use that exact revision; an older HACS release may not include it.

## Setup

You need Home Assistant and a PS4 on your LAN with GoldHEN running. FTP is the only PS4 service needed to add the integration.

| Service | Default port | Used for |
|---|---|---|
| FTP | `2121` | Setup, file browsing, and downloading `app.db` |
| Klog / debug log server | `3232` | Live logs and game tracking |
| BinLoader | `9090` | Sending payloads |

The setup flow doesn't probe BinLoader or check a firmware version. Leave optional services disabled if you're not using them.

### HACS

1. [Add the repository to HACS](https://my.home-assistant.io/redirect/hacs_repository/?owner=Tech-Morph&repository=HA-PS4-GoldHEN-Integration&category=integration), or add `Tech-Morph/HA-PS4-GoldHEN-Integration` as an Integration custom repository.
2. Download PS4 GoldHEN and restart Home Assistant.
3. Go to Settings → Devices & Services → Add Integration → PS4 GoldHEN.
4. Enter the PS4 IP address, FTP port, and BinLoader port.

### Manual install

Copy `custom_components/ps4_goldhen` from the revision you want into your HA configuration's `custom_components` folder. Back up the existing component first, restart HA, then add the integration through the UI. A HACS update or redownload can overwrite a manually installed test build.

The form only exposes the host, FTP port, and BinLoader port. Klog uses the backend default of `3232`. RPI means Remote Package Installer, not a Raspberry Pi REST sensor; PKG installation isn't implemented.

## The panel

| Tab | What it does |
|---|---|
| FTP | Browse, upload, download, rename, delete files or empty directories, and edit text |
| Payloads | List `.bin` and `.elf` files on the HA host and send a selected file to BinLoader |
| Klog | Show live PS4 logs through the backend listener |

There isn't a separate Game Library or Dashboard tab. The current-game sensor uses klog and names from the PS4's `app.db`. Names come from the local database, but cover art can use an external CDN URL from that database.

The repaired backend owns one klog connection per entry. The panel subscribes to it rather than opening another PS4 connection. There is no history replay, and a subscription label isn't proof of received logs. Close competing klog clients if the panel stays empty.

## Payloads

Payload files live at `/config/ps4/payloads` on the HA host. Bundled files are copied there during setup only if the destination name doesn't exist. Nothing is sent or executed just by copying it, and removing a bundled file later won't remove an existing HA copy.

Check a payload's source and firmware support before sending it. A successful transfer confirms bytes sent, not execution. There isn't a verified compatibility list for every bundled binary yet. See the [payload README](custom_components/ps4_goldhen/bundled_payloads/README.md).

The service is `ps4_goldhen.send_payload`. This example uses a placeholder filename:

```yaml
action: ps4_goldhen.send_payload
data:
  payload_file: your-reviewed-payload.bin
  ps4_host: 192.168.1.100
  binloader_port: 9090
  timeout: 30
```

For multiple consoles, set both host and port explicitly. Global defaults and button targeting still need work. The service accepts absolute paths as well as filenames, and its path handling isn't fully restricted yet. The timeout isn't a whole-transfer deadline.

`restart.bin` and `standby.bin` aren't bundled, so don't treat those buttons as working power controls. There is no `install_pkg` service or PS5 installer.

## PS4State and telemetry

Don't load the old PRX to fix an HA connection problem or get rid of unknown sensors. Its sensor APIs, fan behavior, firmware support, audio, and saving still need work.

HA checks `/data/GoldHEN/ps4_state.json` on a nominal five-second interval. The repaired read has operation timeouts, a four-second transfer deadline, bounded cleanup, and a 65,536-byte JSON limit. Missing, invalid, or stalled telemetry should no longer hang setup. Those limits don't cover every other FTP/database/payload operation.

FTP Status includes `telemetry_status`. FTP can stay online with `ftp_550` after successful login; that code means a request was rejected, not necessarily that the file is missing. `ok` means recognized JSON was fetched, not that every reading is valid or fresh. See the [project notes](docs/PROJECT.md) for the other statuses.

Failed or invalid reads clear dynamic measurements, but static details can stay cached. Frozen old JSON isn't detected yet. Temperature labels/scaling and power totals aren't verified; fan duty isn't RPM. Don't publish console identifiers from diagnostic output.

GoldHEN's configuration file is `/data/GoldHEN/plugins.ini`, with binaries under `/data/GoldHEN/plugins/`. Neither needs editing for base HA setup. Leave other plugin rules alone; changing a rule doesn't prove an already loaded plugin stopped. A game-loaded plugin isn't proof of continuous home-screen telemetry either.

## Testing and known issues

My testing has been on firmware 11.00. The 56 Python tests and frontend checks passed, and I've tested FTP, klog, payload functionality, offline HA startup, and reconnection. Firmware 9.00 / HA 2026.8 still needs confirmation from the reporter in [issue #1](https://github.com/Tech-Morph/HA-PS4-GoldHEN-Integration/issues/1). Fresh new-entry setup is separate from restarting an existing entry.

These tests use mocks, HA stubs, and loopback FTP servers. They don't replace testing in HA or prove native-plugin compatibility. I haven't established a minimum supported HA version or support for every firmware. The [project notes](docs/PROJECT.md) describe the test suites. Run the Python scripts with `python3 -B tests/<test_file>.py`, the frontend scripts with `node tests/<test_file>.cjs`, and the JS syntax check with `node --check custom_components/ps4_goldhen/frontend/ps4-goldhen-panel.js`.

- Game names refresh from app.db at background-task startup, then 300 seconds after each attempt. Names fall back to title IDs while unavailable.
- Reliable Rest Mode/off detection needs an external `sensor.ps4_state_pi` with `on`, `rest`, or `offline` states. See [PS4 State Monitor](https://github.com/Tech-Morph/PS4-State-Monitor).
- MLSD timestamps are shown in browser-local time. LIST fallback dates stay as the server returned them; years and timezones aren't guessed.
- Multiple entries can be added, but app.db and cover caches are shared. Changing an IP can also affect host-based entity IDs.
- Large transfers, permissions, cover routes, payload paths, and setup/unload cleanup still need work. Keep the PS4 services on your LAN.

For bug reports, include the HA version, firmware, exact GoldHEN build, integration revision, and relevant logs. Remove credentials and console identifiers first.

## Support and license

If you find this useful, you can [support my work on Ko-fi](https://ko-fi.com/techmorph).

MIT license. See [LICENSE](LICENSE).
