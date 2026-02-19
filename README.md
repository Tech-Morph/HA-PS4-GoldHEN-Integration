# PS4 GoldHEN (Home Assistant custom integration)

Phase 1 features:
- Send payloads (.bin) to GoldHEN BinLoader (default port 9090).
- Basic connectivity sensors for BinLoader (9090) and FTP (2121).

See docs/PROJECT.md for roadmap (temps, current title, app switching).

## Install (HACS)
1. HACS → Integrations → Custom repositories → add this repo as type "Integration"
2. Install
3. Restart Home Assistant
4. Settings → Devices & services → Add integration → "PS4 GoldHEN"

## Usage
### Service: ps4_goldhen.send_payload
- Place payloads under: /config/ps4_payloads/
- Call the service with e.g. payload_file: "my_payload.bin"
