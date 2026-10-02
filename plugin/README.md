# PS4State plugin status

<!-- ps4state-not-working -->
> [!WARNING]
> `PS4StateJSON.prx` (the PS4State plugin) is under active development and is **not** currently in working order. Do not install or enable it.
>
> The Home Assistant integration works independently of this plugin. Temperature, power, fan, and hardware telemetry should remain unknown without a working, validated producer. The connection repair does not fix or validate this PRX, its firmware compatibility, fan control, audio, or game-saving behavior.
<!-- /ps4state-not-working -->

The bundled `PS4StateJSON.prx` is retained as a historical/development artifact, not a working or firmware-certified release. This change does not rebuild or replace the binary.

Do not use it to diagnose Home Assistant connection failures. Base FTP/klog integration does not require the PRX. Preserve existing GoldHEN plugin rules; do not create global activation rules or enable the historical binary as a workaround.

Native producer repair and validation remain separate. No private sensor API layout, physical units, power-rail aggregation, fan restoration, audio, game saving, or all-firmware support is certified by the Home Assistant repair.
