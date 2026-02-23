# PS4 GoldHEN — Home Assistant Integration

![version](https://img.shields.io/badge/version-0.8.2-blue)

A [HACS](https://hacs.xyz) + sidebar panel for managing a PS4 running GoldHEN network services.

## What it does

From Home Assistant, you get a PS4 sidebar panel with tabs:

- **FTP**
  - Browse PS4 files/folders
  - Upload/download files
  - Rename/delete
  - Edit text files (read/write)

- **BinLoader**
  - List payloads from the HA payload directory
  - Send a payload to the PS4 BinLoader TCP port (commonly 9090)

- **Klog**
  - Display live PS4 log output in the UI
  - Auto-connects when you open the Klog tab (you can still disconnect manually)

## Requirements

- A PS4 on your LAN.
- GoldHEN running and its network services enabled (FTP/BinLoader/Klog as applicable).
- Home Assistant with HACS installed.

## Installation (HACS)

1. Add this repository to HACS as a Custom Repository (Integration).
2. Install the integration.
3. Restart Home Assistant.
4. Add/configure the integration in the UI.

## Configuration

Configure your PS4 host/IP and ports in the integration config flow.

Typical ports (may vary by your setup):
- FTP: 2121
- BinLoader: 9090
- Klog: 3232

## Usage

### Sidebar panel
Open the sidebar entry for the integration.

- Select your PS4 from the dropdown.
- Use:
  - FTP tab to browse/upload/edit.
  - BinLoader tab to send payloads.
  - Klog tab to see live logs.

### Klog notes

The PS4 Klog stream is typically “single-client” style.
This integration is designed so the UI subscribes to the integration (HA websocket),
not directly to the PS4, so you can keep recording logs while still viewing them.

If you see logs in `nc` but not in the UI:
- Make sure the integration backend is actually emitting websocket events for `ps4_goldhen/klog_subscribe`.
- Ensure no other part of your setup is consuming the only available klog connection.

## Troubleshooting

- If FTP listing works but uploads fail:
  - Check HA auth/session and verify the `/api/ps4_goldhen/ftp/upload` endpoint returns 200.
- If BinLoader “Send” says success but nothing happens:
  - Confirm PS4 host/port and that BinLoader is enabled.
- If Klog connects but box stays empty:
  - Confirm the backend is sending messages shaped like:
    - `{ type: "event", event: { line: "..." } }`
    - (the panel also accepts `{ line: "..." }` as a fallback)

## Contributing

PRs welcome. Please keep websocket schemas consistent and ensure all subscriptions clean up correctly.
