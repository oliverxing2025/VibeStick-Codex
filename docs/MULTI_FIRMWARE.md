# Dual-firmware installation and switching

VibeStick-Codex supports a two-app StickS3 layout:

| Slot | Address | Maximum size | App |
| --- | --- | --- | --- |
| `ota_0` | `0x20000` | `0x300000` (3 MiB) | VibeStick Hourglass Liquid |
| `ota_1` | `0x320000` | `0x300000` (3 MiB) | VibeStick-Codex |

Both apps must target M5Stack StickS3 and use the same partition table. The
recommended companion is
[VibeStick-Hourglass-Liquid](https://github.com/oliverxing2025/VibeStick-Hourglass-Liquid).

## First-time installation

Replace `<port>` with the connected StickS3 serial port. Put the device into
download mode before flashing.

1. Build VibeStick-Codex:

```sh
. /path/to/esp-idf/export.sh
idf.py -C firmware/sticks3 build
```

2. Flash VibeStick-Codex normally once. This installs the bootloader,
partition table, OTA metadata, and an initial application:

```sh
idf.py -C firmware/sticks3 -p <port> flash
```

3. Copy the VibeStick-Codex application image into `ota_1`:

```sh
python -m esptool --chip esp32s3 -p <port> \
  write_flash 0x320000 \
  firmware/sticks3/build/vibe_stick_sticks3.bin
```

4. Download or build VibeStick-Hourglass-Liquid, then write only its
application image into `ota_0`:

```sh
python -m esptool --chip esp32s3 -p <port> \
  write_flash 0x20000 \
  /path/to/vibestick_hourglass_liquid.bin
```

The verified hourglass binary and its SHA-256 are published in the companion
repository's
[`firmware/sticks3/releases/liquid-style-v1/`](https://github.com/oliverxing2025/VibeStick-Hourglass-Liquid/tree/main/firmware/sticks3/releases/liquid-style-v1)
directory.

5. Restart the StickS3 and verify both apps. A fast side-button triple click
switches to the other app and restarts the device.

## Updating one app

To preserve both apps, write only the relevant application image:

```sh
# Update VibeStick-Codex in ota_1
python -m esptool --chip esp32s3 -p <port> \
  write_flash 0x320000 firmware/sticks3/build/vibe_stick_sticks3.bin

# Update Hourglass Liquid in ota_0
python -m esptool --chip esp32s3 -p <port> \
  write_flash 0x20000 /path/to/vibestick_hourglass_liquid.bin
```

Do not run a normal full `idf.py flash` when only updating one app: it may
rewrite the partition table, OTA metadata, or the app stored in `ota_0`.

## Controls and recovery

- Side button, fast triple click: switch firmware and reboot.
- VibeStick-Codex explicitly targets Hourglass in `ota_0`.
- Hourglass explicitly targets VibeStick-Codex in `ota_1`.
- If the target slot is empty, corrupt, oversized, or built for an incompatible
  partition layout, the switch is rejected or the target may fail to boot.
- Recovery: enter StickS3 download mode and repeat the first-time installation.
- After flashing, use the serial monitor and verify which app and OTA slot
  booted. A successful `write_flash` alone does not prove that both apps run.

The Codex app needs the Mac bridge and trusted Wi-Fi. The hourglass app is
standalone and does not need the bridge.
