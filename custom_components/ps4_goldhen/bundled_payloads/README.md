# Bundled payloads

These files are copied to `/config/ps4/payloads` on the HA host during integration setup. A file is only copied if that destination name doesn't already exist. Nothing is sent or executed automatically.

Add your own `.bin` or `.elf` files to the same HA folder to have them appear in the Payloads tab. Removing a file from this repository won't remove a copy already in HA.

## Before sending anything

There isn't a verified firmware/source list for every binary here yet. Check the payload's source, build, and firmware support before using it; the filename alone isn't enough. Don't send one just to troubleshoot an HA connection problem.

BinLoader needs to be running, normally on port `9090`. A successful send confirms the transfer, not that the payload executed.

`restart.bin` and `standby.bin` aren't included, so the corresponding buttons aren't ready-to-use power controls. PKG installation isn't implemented either.

## Included files

- `Linux-1gb.bin`
- `Linux-2gb.bin`
- `Linux-3gb.bin`
- `Linux-4gb.bin`
- `WebRTE.bin`
- `app-dumper.bin`
- `app2usb.bin`
- `backup.bin`
- `disable-aslr.bin`
- `disable-updates.bin`
- `enable-browser.bin`
- `enable-updates.bin`
- `exit-idu.bin`
- `fan-threshold.bin`
- `ftp.bin`
- `history-blocker.bin`
- `kernel-clock.bin`
- `kernel-dumper.bin`
- `module-dumper.bin`
- `np-fake-signin-ps4.elf`
- `permanent-uart.bin`
- `ps4-debug_v1.1.16.bin`
- `ps4-sflash0-dumper.bin`
- `pup-decrypt.bin`
- `restore.bin`
- `rif-renamer.bin`
- `todex.bin`

These are the actual filenames, including case. Keep similarly named builds from other sources separate so you know which one you're sending.

[Back to the main README](../../../README.md)
