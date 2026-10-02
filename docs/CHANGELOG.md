# Development changelog

<!-- ps4state-not-working -->
> [!WARNING]
> `PS4StateJSON.prx` (the PS4State plugin) is under active development and is **not** currently in working order. Do not install or enable it.
>
> The Home Assistant integration works independently of this plugin. Temperature, power, fan, and hardware telemetry should remain unknown without a working, validated producer. The connection repair does not fix or validate this PRX, its firmware compatibility, fan control, audio, or game-saving behavior.
<!-- /ps4state-not-working -->

## Unreleased — connection and documentation repairs

Recorded October 2, 2026. These entries describe development changes, not a published release. The component manifest remains `0.9.0`; no GitHub release or issue closure is implied.

### Home Assistant transport and UI

- Added bounded, validated FTP telemetry transport with socket cleanup, size limits, and cancellation propagation.
- Separated authenticated FTP status from optional telemetry availability; dynamic readings clear on failed/invalid fetches.
- Preserved authenticated status when a later passive/data I/O operation fails.
- Bounded setup/options TCP socket cleanup and handled JSON parser recursion failures.
- Exposed telemetry_status on the existing FTP Status entity.
- Consolidated klog ownership in one backend listener per entry; panel subscriptions use HA events with overlap/stale-callback guards.
- Restored the asyncio import used by FTP handlers and added full-module regression tests.
- Added MLSD-first listings, explicit UTC timestamps, browser-local rendering, and scoped FTP/editor HTML escaping; ambiguous LIST dates remain unchanged.

### Documentation and service metadata

- Corrected GoldHEN configuration path to /data/GoldHEN/plugins.ini and made optional native telemetry distinct from initial HA setup.
- Documented five-second telemetry polling, 300-second background DB-refresh sleep, and /config/ps4 directories.
- Described three actual panel tabs and the three current configuration fields; RPI is not a Pi REST port.
- Removed unsupported promises of Game Library UI, PKG/PS5 installation, calibrated telemetry, continuous home-screen sampling, and validated fan/audio/save behavior.
- Removed unregistered install_pkg service metadata; registered services and runtime Python code are unchanged by this docs-only update.
- Corrected payload filenames/icon inventory and distinguished resource copying from execution.
- Removed mismatched version/minimum-HA badges and recorded tested versus pending behavior.

### Evidence and remaining checks

The developer reported 56 passing Python tests, frontend checks, live FTP control success, and ftp_reachable=true / telemetry_status=ftp_550 on October 2. The rejected telemetry request validates bounded handling, not file absence, producer execution, or measurement accuracy.

The owner subsequently reported successful latest-patch deployment with verified transport/sensor hashes, working FTP/klog/payload functionality, offline HA startup, and recovery. Fresh new-entry configuration, firmware 9.00 reporter confirmation, native producer repair, frozen-file freshness, and unrelated hardening remain pending. No broad firmware certification is claimed. Keep issue #1 open pending reporter confirmation.
