# Project / Roadmap — PS4 GoldHEN (Home Assistant)

This integration focuses on stable day-to-day tools for a GoldHEN-enabled PS4 inside Home Assistant.

## Current scope

- Sidebar dashboard panel:
  - FTP browser/editor (browse, download, upload, rename, delete, edit text)
  - BinLoader sender (send `.bin` / `.elf` payloads on demand)
- HA service: `ps4_goldhen.send_payload`
- FTP reachability sensor (polls FTP only)

## Explicitly out of scope (for now)

- Remote PKG / Remote Package Installer support.
  - Rationale: it adds security and reliability pitfalls (auth, large file handling, PS4 HTTP compatibility), and isn’t needed for the core goal of payload delivery + FTP management.

## Planned / ideas

- GoldHEN API sensors (if stable across versions):
  - Console temperature / fan
  - Current title / running app
  - Free space info
- Quality-of-life:
  - Payload library management in the UI (upload payloads into `/config/ps4_payloads/`)
  - Optional “favorites” payload list per PS4 entry
- Diagnostics:
  - Better error reporting for FTP failures and BinLoader connection issues

## Notes

- BinLoader should not be polled; only connect when sending a payload.
- For dashboard assets, keep the logo as a transparent PNG for best appearance.
