# Development changelog

<!-- ps4state-not-working -->
> [!WARNING]
> `PS4StateJSON.prx` (the PS4State plugin) is under active development and is **not** currently in working order. Do not install or enable it.
>
> The Home Assistant integration works independently of this plugin. Temperature, power, fan, and hardware telemetry should remain unknown without a working, validated producer. The connection repair does not fix or validate this PRX, its firmware compatibility, fan control, audio, or game-saving behavior.
<!-- /ps4state-not-working -->

## 0.9.1 — release preparation

Prepared October 24, 2026. This section describes the planned 0.9.1 release; a version bump or merged preparation PR does not itself publish a tag, release, or asset.

### Security and console targeting

Thanks to [ilooklikeathumb](https://github.com/ilooklikeathumb) for the focused security fixes, follow-up changes, and regression tests in [PR #3](https://github.com/Tech-Morph/HA-PS4-GoldHEN-Integration/pull/3).

- Restricted the panel, custom WebSocket commands, FTP download/upload views, and direct `send_payload` service calls to HA administrators; service calls without a user context remain available for automations.
- Constrained payload files to files directly inside `/config/ps4/payloads` after path resolution, and constrained explicit console hosts to configured integration entries.
- Fixed the panel's payload destination when switching between configured consoles.
- Made Restart and Standby buttons target their own console and preserve the pressing user's context.
- Kept the public cover route cache/metadata-only, without request-triggered FTP.
- Added security and frontend console-switch regressions to CI.

### Upgrade notes

- Non-admin users can no longer open the panel or use its protected commands, transfer URLs, or `send_payload`. Non-admin button presses do not bypass service authorization.
- Move payloads stored elsewhere into `/config/ps4/payloads`. Use a filename, or an absolute path resolving to a file directly inside that directory. Paths resolving outside that directory or into a subdirectory are refused.
- `ps4_host` must match a configured console; omitting it selects the first configured console. Specify it explicitly in multi-console automations.
- A supplied `binloader_port` overrides the entry port for that call; omitting it uses the selected console's configured port.
- Existing payload files are not removed by this release. Bundled files are copied only when the destination name is absent.
- Restart and Standby still require `restart.bin` and `standby.bin`, which are not bundled. Target/context fixes do not make native power control validated.

### Included connection and documentation repairs

This planned release also includes the earlier development repairs recorded below: bounded FTP telemetry reads, separation of FTP connectivity from optional telemetry, one backend klog listener per entry, MLSD-first listings with browser-local timestamps, FTP runtime regression coverage, and corrected setup/service documentation.

### Validation and limits

- The tested security head was `ee34d16ea89c5426a7a852f3599eccdd17d10e59`; it was merged as `886349dcc1302c7bf9b18134b823ecc9bc5b50b5`.
- All 76 Python tests, three frontend assertion scripts, and the panel JavaScript syntax check passed for the security candidate. CI covered Python 3.13, Python 3.14, and Node 24.
- Post-merge Regression tests, Validate, and Validate with hassfest workflows passed for `886349dcc1302c7bf9b18134b823ecc9bc5b50b5`. Release-preparation changes require their own PR checks.
- Live smoke tests confirmed offline startup of an existing entry, panel loading, FTP browsing, received klog output, game recognition, and return-to-home reporting. Successful online connections followed a UI refresh; exhaustive unattended recovery timing was not established.
- Authenticated non-admin browser tests confirmed panel denial and direct-service denial. The service test exercised rejection of an invalid path, not valid payload transfer or execution. See the [public validation record](https://github.com/Tech-Morph/HA-PS4-GoldHEN-Integration/pull/3#issuecomment-6382174291).
- This is not an every-route authorization certification or validation of FTP writes, native binaries, fan control, audio, saves, or all firmware. The larger contributor feature fork is not included.
- Shared app.db/cover caches, host-based entity identities, frozen telemetry freshness, large-transfer limits, and lifecycle cleanup remain follow-up work.

## Historical development checkpoint — October 2, 2026

These entries were recorded as unreleased development work on October 2, 2026, when the component manifest was `0.9.0`. They are preserved as historical context and are included in the planned 0.9.1 release described above; they do not imply a separate published release or issue closure.

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
