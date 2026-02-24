# Bundled payloads

Payloads are "auto-installed" into /config/ps4_payloads after HACS install, you can add custom payloads to the folder to make them show in the binloader.

Below is a list of what each payload does:


- App2USB.bin: Moves installed PKG games & apps from the internal HDD to an external USB drive.

- app-dumper.bin: Dumps installed games & applications.

- backup.bin: Creates backups of important system data.

- disable-aslr.bin: Disables ASLR (memory randomization), typically for advanced/debug use.

- disable-updates.bin: Blocks system firmware updates.

- enable-browser.bin: Enables the PS4 browser if it’s disabled.

- enable-updates.bin: Re-enables system updates (undoes update-blocking).

- exit-idu.bin: Exits IDU (in-store demo) mode.

- fan-threshold.bin: Adjusts fan threshold / fan behavior to help manage temperatures.

- ftp.bin: Enables FTP access to the PS4 filesystem.

- history-blocker.bin: Prevents browser/activity history from being saved.

- kernel-clock.bin: Modifies the system clock at kernel level.

- kernel-dumper.bin: Dumps kernel memory (advanced users).

- module-dumper.bin: Dumps decrypted system modules (e.g., from /system, /system_ex, /update) to a USB device.

- permanent-uart.bin: Enables UART debugging access (described as enabling hardware-based UART and persisting through updates in at least one payload overview).

- ps4-debug_v1.1.16.bin: PS4Debug is commonly referenced as a debugging/modding-related payload in payload overviews (the specific “what it does” details vary by build/source).

- pup-decrypt.bin: Decrypts firmware PUP files.

- restore.bin: Restores backups or a previous state (often paired conceptually with “Backup”).

- rif-renamer.bin: Renames license (RIF) files.

- todex.bin: Converts/puts the PS4 into “DEX” developer-like mode (advanced).

- WebRTE.bin: Web Realtime Trainer Engine; when used with a trainer site/app, it hooks game memory so cheats can be enabled in real time without manually patching eboot.bin.

- Linux-1gb.bin / Linux-2gb.bin / Linux-3gb.bin / Linux-4gb.bin: Used to activate linux on ps4 (Choose between 1 - 4 GB of RAM)

- ps4-sflash0-dumper.bin: This payload was made for dumping NOR firmware (so called Sflash0) to USB drive instead using FTP.
