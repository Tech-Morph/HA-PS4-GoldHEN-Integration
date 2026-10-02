# Payload icon assets

This directory is served under `/api/ps4_goldhen/frontend/payload_icons/`. The frontend normalizes the payload name and maps it to an icon filename. Filenames and case below match the current panel mapping.

A payload with no mapping uses the GoldHEN logo. A mapped but missing image can still produce a broken image; the mapping is not an existence/compatibility check. Icons do not prove payload execution safety or firmware support.

## Mapped filenames

- `Linux-1gb.png`
- `Linux-2gb.png`
- `Linux-3gb.png`
- `Linux-4gb.png`
- `WebRTE.png`
- `app-dumper.png`
- `app2usb.png`
- `backup.png`
- `disable-aslr.png`
- `disable-updates.png`
- `enable-browser.png`
- `enable-updates.png`
- `exit-idu.png`
- `fan-threshold.png`
- `ftp.png`
- `history-blocker.png`
- `kernel-clock.png`
- `kernel-dumper.png`
- `module-dumper.png`
- `permanent-uart.png`
- `ps4-debug_v1.1.16.png`
- `ps4-sflash0-dumper.png`
- `pup-decrypt.png`
- `restore.png`
- `rif-renamer.png`
- `todex.png`

The panel adds an icon cache token. This is an asset directory, not a payload installation directory; executable resources belong in HA's `/config/ps4/payloads`.

[Main documentation](../../../../README.md)
