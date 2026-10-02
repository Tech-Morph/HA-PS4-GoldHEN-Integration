# PS4StateJSON

> [!WARNING]
> `PS4StateJSON.prx` is under development and is **not** working yet. Do not install or enable it.

I'm still working on this plugin. The PRX in this folder is an old development copy, not a usable release. The Home Assistant connection fixes don't rebuild it or fix its sensor APIs, fan control, audio, or saving behavior.

FTP, klog, and payload sending work without it. Don't load it to fix an HA setup error or get rid of unknown telemetry readings.

There is still work to do on the sensor data, firmware support, fan behavior, and plugin lifetime. A plugin loaded by a game also doesn't mean it will keep updating data on the home screen.

The GoldHEN configuration file is `/data/GoldHEN/plugins.ini`. Leave other plugin rules alone; editing a rule isn't proof that an already loaded plugin has stopped. There are no activation instructions here while this build isn't working.

[Back to the main README](../README.md)
