# PS4 GoldHEN — Home Assistant Integration

![version](https://img.shields.io/badge/version-0.7.2-blue)

A [HACS](https://hacs.xyz) custom integration for Home Assistant that lets you send `.bin` payloads to a **PS4 running GoldHEN** via the BinLoader TCP service.

---

## Features (v0.5.0)

- **Send Payloads** — stream any `.bin` file to GoldHEN BinLoader over TCP (default port 9090).
- **FTP Connectivity Sensor** — polls GoldHEN FTP (default port 2121) every 30 s and reports `online` / `offline`.
  > BinLoader (9090) is intentionally **not** polled on a schedule — repeated probe connections can destabilise the GoldHEN BinLoader service. Payloads are only sent on demand.

---

## Requirements

| What | Detail |
|------|--------|
| PS4 firmware | GoldHEN installed and running |
| BinLoader | enabled in GoldHEN, listening on port **9090** (configurable) |
| FTP | GoldHEN FTP enabled on port **2121** (configurable) |
| Payload files | `.bin` files placed in `/config/ps4_payloads/` on the HA host |

---

## Install via HACS

1. **HACS → Integrations → ⋮ → Custom repositories**
2. Add `https://github.com/Tech-Morph/HA-PS4-GoldHEN-Integration` as type **Integration**.
3. Click **Download**.
4. Restart Home Assistant.
5. **Settings → Devices & Services → Add Integration → "PS4 GoldHEN"**.
6. Enter your PS4 IP, BinLoader port, and FTP port.

---

## Usage

### Service: `ps4_goldhen.send_payload`

Send a payload from Home Assistant to GoldHEN BinLoader.

```yaml
service: ps4_goldhen.send_payload
data:
  payload_file: goldhen.bin        # filename inside /config/ps4_payloads/
  # ps4_host: 192.168.1.100        # optional override
  # binloader_port: 9090           # optional override
  # timeout: 30                    # optional, seconds
```

**Payload directory:** `/config/ps4_payloads/` (created automatically on HA host).

---

## Roadmap

See [docs/PROJECT.md](docs/PROJECT.md) for planned features:
- PS4 temperature sensors (via GoldHEN API)
- Current game title sensor
- App / game switching
- More to come...

---

## License

MIT
