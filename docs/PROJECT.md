# HA-PS4-GoldHEN-Integration — Project

Home Assistant custom integration (HACS) to control and monitor a PS4 running GoldHEN network services.

## Goals

- Provide a clean Home Assistant sidebar panel for PS4 tools:
  - FTP file browser (browse, upload, download, delete, rename, edit text).
  - BinLoader payload sender (send .bin/.elf to port 9090).
  - Live Klog viewer (stream PS4 kernel/app log output into the UI).
- Keep everything local-first and LAN-friendly.
- Avoid fragile “one-off” scripts by using HA-native services + websocket APIs.

## Current Features

### Sidebar panel UI
- Tabs: FTP, BinLoader, Klog
- PS4 selector (supports multiple configured consoles)

### FTP
- Websocket directory listing
- Download via signed path (auth/sign_path)
- Upload via authenticated POST
- Text editor: read/write small text files over FTP

### BinLoader
- Payload listing from HA filesystem (payload directory returned by backend)
- Service call to send payload over raw TCP to the PS4 BinLoader port

### Klog
- Subscribe UI to backend stream and append to in-panel log box
- Auto-connect when opening the Klog tab, disconnect on tab-leave/entry-switch

## Architecture Notes

- Frontend: `custom_components/ps4_goldhen/frontend/ps4-goldhen-panel.js`
- Backend:
  - Websocket commands:
    - `ps4_goldhen/list_entries`
    - `ps4_goldhen/list_payloads`
    - `ps4_goldhen/ftp_*` commands (list, delete, rename, get_text, put_text)
    - `ps4_goldhen/klog_subscribe` (stream events)
  - HTTP endpoints:
    - `/api/ps4_goldhen/ftp/download`
    - `/api/ps4_goldhen/ftp/upload`

## Roadmap

- Klog improvements:
  - Add “tail N lines” on connect.
  - Add filters (contains / regex).
  - Add “copy”, “download log”, and “pause” buttons.
- PKG workflows:
  - Upload PKG to HA and deliver/install via chosen mechanism (TBD).
- Better error reporting in UI:
  - Connection diagnostics (ports reachable, service running, auth issues).
- Unit/integration tests for websocket schemas and filesystem operations.

## Development Workflow

- Keep websocket message shapes stable (prefer HA `event` envelope for streams).
- Ensure cleanup on unsubscribe/disconnect (avoid orphan tasks).
- Prefer async I/O, and avoid blocking calls in the event loop.
