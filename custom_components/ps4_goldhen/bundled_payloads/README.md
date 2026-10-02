# Bundled payload resources

The integration copies absent `.bin`/`.elf` resources from this folder to HA's `/config/ps4/payloads` during integration setup. It does not overwrite existing destination names, send a payload, or execute one just by copying. Removing a resource here does not delete a previously copied or custom HA file.

The Payloads tab lists those HA-local resources. Sending requires explicit user action and a running BinLoader, default TCP 9090. A transfer success message is not execution confirmation.

## Compatibility and safety

This repository does not provide a verified per-binary source/firmware/provenance manifest. Names are inventory labels, not proof of behavior or compatibility. Inspect trusted source/build identity and independently validate a payload for your console before use. Do not send bundled tools to diagnose an HA connection timeout. No firmware update, fan-control, privilege, kernel, or storage-modification behavior is certified by the HA repair.

`restart.bin` and `standby.bin` are not included; the corresponding button entities are not validated bundled power controls. PKG installation is not implemented.

## Exact bundled filenames

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

This inventory includes an ELF resource as well as BIN resources; case and punctuation reflect the actual files. Do not substitute similarly named binaries from unrelated archives.

[Main documentation](../../../README.md)
