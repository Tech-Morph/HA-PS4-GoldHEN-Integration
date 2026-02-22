# PS4 GoldHEN — Home Assistant Integration

![version](https://img.shields.io/badge/version-0.8.1-blue)

A [HACS](https://hacs.xyz) custom integration for Home Assistant that provides:

- A sidebar **dashboard panel** (FTP + BinLoader tools).
- A service to send `.bin` / `.elf` payloads to GoldHEN BinLoader over TCP.
- An FTP reachability sensor (safe periodic polling of FTP only).

---

## Features

- **Sidebar dashboard** — appears in Home Assistant’s sidebar as “PS4 GoldHEN” with icon `mdi:sony-playstation`.
- **BinLoader sender** — sends selected payloads to the configured PS4 BinLoader port (default 9090).
- **FTP dashboard tools** — browse/list, download, upload, rename, delete, and edit text files via FTP.
- **FTP connectivity sensor** — polls GoldHEN FTP (default 2121) every 30 seconds and reports reachable/unreachable.

> BinLoader (9090) is intentionally not polled on a schedule — repeated probe connections can destabilize the GoldHEN BinLoader service. Payloads are only sent on demand.

---

## Requirements

| What | Detail |
|------|--------|
| PS4 firmware | GoldHEN installed and running |
| BinLoader | enabled in GoldHEN, listening on port **9090** (configurable) |
| FTP | GoldHEN FTP enabled on port **2121** (configurable) |
| Payload files | `.bin` / `.elf` placed in `/config/ps4_payloads/` on the HA host |

---

## Install via HACS (Custom Repository)

1. Install HACS if you haven’t already: https://hacs.xyz
2. In Home Assistant: **HACS → Integrations**
3. Open the menu (⋮) → **Custom repositories**
4. Add this repository URL:

   `https://github.com/Tech-Morph/HA-PS4-GoldHEN-Integration`

5. Set **Category** to **Integration**
6. Click **Add**
7. Find “PS4 GoldHEN — Home Assistant Integration” in HACS and click **Download**
8. Restart Home Assistant
9. Go to **Settings → Devices & Services → Add Integration → “PS4 GoldHEN”**
10. Enter:
    - PS4 IP / Host
    - BinLoader port (default 9090)
    - FTP port (default 2121)

---
