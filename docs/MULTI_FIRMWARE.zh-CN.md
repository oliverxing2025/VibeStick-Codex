# 双固件安装与切换

VibeStick-Codex 使用 StickS3 双应用布局：

| 分区 | 地址 | 最大容量 | 固件 |
| --- | --- | --- | --- |
| `ota_0` | `0x20000` | `0x300000`（3 MiB） | VibeStick 液态沙漏 |
| `ota_1` | `0x320000` | `0x300000`（3 MiB） | VibeStick-Codex |

两个固件必须都面向 M5Stack StickS3，并使用完全相同的分区表。推荐搭配
[VibeStick-Hourglass-Liquid](https://github.com/oliverxing2025/VibeStick-Hourglass-Liquid)。

## 首次安装

把 `<port>` 换成 StickS3 的实际串口，并在刷写前让设备进入下载模式。

1. 编译 VibeStick-Codex：

```sh
. /path/to/esp-idf/export.sh
idf.py -C firmware/sticks3 build
```

2. 先完整刷入一次 VibeStick-Codex，用来安装 Bootloader、分区表、OTA 数据和
初始应用：

```sh
idf.py -C firmware/sticks3 -p <port> flash
```

3. 把 VibeStick-Codex 应用镜像写入 `ota_1`：

```sh
python -m esptool --chip esp32s3 -p <port> \
  write_flash 0x320000 \
  firmware/sticks3/build/vibe_stick_sticks3.bin
```

4. 下载或编译 VibeStick 液态沙漏，只把它的应用镜像写入 `ota_0`：

```sh
python -m esptool --chip esp32s3 -p <port> \
  write_flash 0x20000 \
  /path/to/vibestick_hourglass_liquid.bin
```

经过实机验证的沙漏镜像及其 SHA-256 位于配套仓库的
[`firmware/sticks3/releases/liquid-style-v1/`](https://github.com/oliverxing2025/VibeStick-Hourglass-Liquid/tree/main/firmware/sticks3/releases/liquid-style-v1)
目录。

5. 重启 StickS3，并分别检查两个应用。快速三连击侧键会切换到另一个固件并
自动重启。

## 只更新一个固件

为了保留两个应用，只写入对应的应用镜像：

```sh
# 更新 ota_1 中的 VibeStick-Codex
python -m esptool --chip esp32s3 -p <port> \
  write_flash 0x320000 firmware/sticks3/build/vibe_stick_sticks3.bin

# 更新 ota_0 中的液态沙漏
python -m esptool --chip esp32s3 -p <port> \
  write_flash 0x20000 /path/to/vibestick_hourglass_liquid.bin
```

只更新其中一个应用时，不要执行普通的完整 `idf.py flash`；它可能重写分区表、
OTA 数据或 `ota_0` 中的应用。

## 操作与恢复

- 快速三连击侧键：切换固件并重启。
- VibeStick-Codex 会明确切换到 `ota_0` 的沙漏。
- 沙漏会明确切换到 `ota_1` 的 VibeStick-Codex。
- 如果目标分区为空、镜像损坏、超过 3 MiB，或使用了不兼容的分区表，切换会
  被拒绝，或者目标固件无法正常启动。
- 恢复方法：让 StickS3 进入下载模式，重新执行“首次安装”。
- 刷写后应打开串口监视器，确认实际启动的固件和 OTA 分区。只看到
  `write_flash` 成功，不代表两个固件都能正常运行。

Codex 固件需要 Mac Bridge 和可信 Wi-Fi；沙漏固件可独立运行，不需要 Bridge。
