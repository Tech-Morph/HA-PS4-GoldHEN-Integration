# Project: Home Assistant ↔ PS4 GoldHEN

## Goal
Build a HACS integration that connects to a jailbroken PS4 running GoldHEN and provides:
- Payload sender to BinLoader (9090)
- Sensors: CPU & RSX temps
- Sensors: current game/app
- Controls: view/change (launch) game/app

## Current status (Phase 1 implemented)
✅ Payload sender:
- HA service `ps4_goldhen.send_payload` streams a local .bin over TCP to the PS4 BinLoader port.

✅ Health sensors:
- TCP reachability sensor for BinLoader (default 9090)
- TCP reachability sensor for FTP (default 2121)

## Known constraints / research notes
- GoldHEN release notes list an FTP server (2121) and BinLoader server (9090).
- GoldHEN warns BinLoader is experimental; payloads can crash the console.

## Phase 2 (needs a telemetry/control API)
We still need a verified mechanism to:
- Read CPU + RSX/SOC temps programmatically over the network
- Identify the currently running title
- Launch/switch titles

Options:
A) Use an existing payload/service that exposes this over the network (ex: PS4Debug or another telemetry payload).
B) Write a small custom PS4 payload that exposes:
   - GET /temps -> { cpu_c, rsx_c }
   - GET /title -> { title_id, title_name }
   - POST /launch { title_id }

Next step for you:
- Tell me what you already run on the PS4 besides GoldHEN (PS4Debug? Orbis Toolbox? any overlay/sysinfo plugin?).
- If you can, share what firmware + GoldHEN version you’re on and whether you can run additional payloads at boot.

## Change log
- 0.1.0: Initial HACS integration: payload sender + connectivity sensors
