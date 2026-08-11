<div align="center">
  <img src="assets/brand/vibestick-icon.svg" alt="VibeStick-Codex 图标" width="104">
  <h1>VibeStick-Codex</h1>
  <p><strong>一个放在手边的 Codex 硬件伴侣。</strong></p>
  <p>
    用 M5Stack StickS3 查看实时状态、额度、任务反馈，<br>
    并通过按住说话快速输入。
  </p>
  <p>
    <a href="#项目概览">项目概览</a> ·
    <a href="#当前开发版本">v0.2.1</a> ·
    <a href="#安装">安装</a> ·
    <a href="#配置说明">配置</a> ·
    <a href="#常见问题排查">排查</a> ·
    <a href="#隐私">隐私</a> ·
    <a href="README.md">English</a>
  </p>
  <p>
    <img alt="CI" src="https://github.com/oliverxing2025/VibeStick-Codex/actions/workflows/ci.yml/badge.svg">
    <img alt="硬件：M5Stack StickS3" src="https://img.shields.io/badge/hardware-M5Stack%20StickS3-EA1D2C">
    <img alt="平台：macOS" src="https://img.shields.io/badge/platform-macOS-111111">
    <img alt="ESP-IDF：5.5" src="https://img.shields.io/badge/ESP--IDF-5.5-E7352C">
    <img alt="版本：0.2.1" src="https://img.shields.io/badge/version-0.2.1-F3A712">
    <img alt="许可证：MIT" src="https://img.shields.io/badge/license-MIT-3DA639">
  </p>
  <br>
  <img src="assets/screenshots/vibestick-codex-portrait-dashboard-v2.png" alt="VibeStick-Codex 竖屏仪表盘产品效果图" width="480">
</div>

## 当前开发版本

`0.2.1` 新增了经过共享令牌验证的局域网自动发现。StickS3 连上 Wi-Fi 后会
自动寻找已安装的 Bridge，连接失败时也会重新寻找，因此 Mac 通过 DHCP
取得新 IP 时无需重新编译固件。固件中配置的地址仅作为备用。最新正式
Release 仍为 `v0.2.0`。

## v0.2.0 更新与升级说明

发布于2026年8月1日。固件下载和完整发布说明见
[v0.2.0 Release](https://github.com/oliverxing2025/VibeStick-Codex/releases/tag/v0.2.0)。

相对 v0.1.5，本版本主要更新如下：

- **任务状态小人动画：**横屏在 Codex 工作时显示跑步小人，等待人工批准时
  显示等待小人，任务完成时显示庆祝动画。
- **WAIT 状态判断更可靠：**待处理的权限或批准请求优先于普通近期活动，设备会
  正确进入 `WAITING`，不会继续误显示为 `RUNNING`。
- **横屏布局重新整理：**时钟、电池、当月 Token、任务计数和额度颗粒矩阵均按
  StickS3 紧凑屏幕重新调整尺寸与位置。
- **Token 含义更清楚：**当月数值是输入 Token 加输出 Token，缓存上下文包含在
  输入 Token 内；它表示模型总处理量，不是 OpenAI 订阅额度或实际账单。
- **动画素材完整收录：**仓库新增经过检查的源图、设备预览和固件 Sprite，覆盖
  `RUNNING`、`WAITING`、`DONE` 三种状态。
- **版本号统一为 0.2.0：**固件、Bridge、协议示例、硬件文档、问题模板和发布
  说明使用同一版本号。

### 升级方式

| 下载文件 | 写入地址 | 适用场景 | 保留内容 |
| --- | ---: | --- | --- |
| `VibeStick-Codex-v0.2.0-app.bin` | `0x320000` | 已确认身份和布局的 Codex + Hourglass 双固件设备，仅更新 Codex 槽位 | 不改动 Hourglass 槽、分区表、OTA 元数据和 NVS |
| `VibeStick-Codex-v0.2.0-full-install.bin` | `0x0` | 全新独立安装，或明确要替换现有固件布局 | 会替换 bootloader、分区表、OTA 元数据和 `0x20000` 应用 |

> [!WARNING]
> 写入前必须核对实体设备身份、分区布局、镜像和地址。双固件设备更新 Codex 时
> 只能把应用镜像写入 `0x320000`；完整镜像会替换多固件布局。公开发布固件不含
> Wi-Fi、Bridge 或 API 私密配置，因此首次启动会保持离线，需要在本地加入私人
> 配置后重新构建。

## 项目概览

VibeStick-Codex 把 StickS3 变成一个专注的 Codex 实体窗口：把经常查看的信息从桌面移到手边，并把常用操作放到两个实体按键上。

| | 能力 | 作用 |
| --- | --- | --- |
| **01** | 实时状态 | 显示 Wi-Fi、时间、电量、Codex 状态、状态小人动画和声音提醒。 |
| **02** | 额度一览 | 查看剩余额度、已用比例、当前额度周期 Token 和重置时间。 |
| **03** | 按住说话 | 按住录音、松开转写，并把文字填入 Codex 供检查。 |
| **04** | 自适应界面 | 自动在详细竖屏主页和紧凑横屏任务视图之间切换。 |

## 设备体验

<table>
  <tr>
    <td width="42%" align="center">
      <img src="assets/screenshots/vibestick-codex-voice-input.png" alt="VibeStick-Codex 按住说话界面产品效果图" width="100%">
    </td>
    <td width="58%" align="center">
      <img src="assets/screenshots/vibestick-codex-landscape-dashboard-v3.png" alt="VibeStick-Codex 横屏仪表盘产品效果图" width="100%">
    </td>
  </tr>
  <tr>
    <td valign="top">
      <strong>按住说话</strong><br>
      按住正面蓝键开始录音，松开后自动转写，并把结果填入 Codex 供检查。
    </td>
    <td valign="top">
      <strong>自适应横屏仪表盘</strong><br>
      横放设备即可查看实时状态、电量、当月用量、额度重置倒计时、任务数量和两个额度周期。
    </td>
  </tr>
</table>

### 横屏和竖屏显示说明

| 界面 | 显示内容 | 含义 |
| --- | --- | --- |
| **横屏** | `RUNNING` / `WAITING` / `DONE` / `ERROR` / `OFFLINE` | 当前 Codex 或 bridge 状态。 |
| **横屏** | 像素小人动画 | Codex 工作时跑步、等待人工批准时等待、任务完成时庆祝。 |
| **横屏** | 电池图标与百分比 | StickS3 本机测得的实际剩余电量。 |
| **横屏** | 顶部中间的 Token 数，例如 `50.7M` | 当前自然月从月初至今观测到的输入 Token 加输出 Token。缓存上下文包含在输入 Token 中，因此这个“总处理量”可能远高于新输入文字或非缓存计费输入；`K`、`M`、`B` 分别表示千、百万和十亿。 |
| **横屏** | 美元数值，例如 `$1.6K` | 按已观测到的当月输入、缓存输入和输出 Token、配置的模型价格表及 [OpenAI API 价格](https://openai.com/api/pricing/)换算出的 API 等值美元估算；它不是 OpenAI 实际账单或订阅扣费。 |
| **横屏** | `6D00H` / `0H51M` | 一周额度和 5 小时额度距离重置还剩多少天、小时或分钟。 |
| **横屏** | `RUN` / `WAIT` / `FIN` | 正在运行、等待操作，以及当前本地自然日内已完成的任务数。 |
| **横屏** | `5H` / `1W` 百分比和颗粒矩阵 | 5 小时额度与一周额度的剩余百分比；中间蓝线分隔两个独立周期。 |
| **竖屏** | `1W FUNDS` / `5H FUNDS` | 一周额度和 5 小时额度的剩余百分比。 |
| **竖屏** | `TODAY` | Bridge 根据一周额度的当日观测样本推算出的本地当天消耗百分比。 |
| **竖屏** | `TOKEN` | 当前滚动七天额度周期内累计的 Token，不是自然周、当天或自然月用量；额度周期重置后重新计算。 |

横屏与竖屏都会显示连接/运行状态和本地时间。Bridge 暂时无法取得的数据会显示为不可用，不会用猜测值代替。

当 Codex 任务正在等待权限或人工批准时，`WAITING` 的优先级高于普通的近期活动。这样状态小人和任务计数会突出当前需要用户处理的动作，不会继续把任务显示成普通运行状态。

当月 Token 是本地活动计数，不代表 OpenAI 订阅额度或实际账单。重复读取的缓存上下文仍计入已处理的输入 Token；旁边的美元数值在估算 API 等值费用时，会另外采用缓存输入价格。

> [!NOTE]
> 以上图片为产品效果图，个别细节可能与当前实机固件略有差异。

## 平台支持

| 平台 | 当前支持情况 |
| --- | --- |
| **macOS** | 完整支持当前安装流程，包括 bridge、HUD、Codex 桌面控制、自动粘贴和 Mac 麦克风兜底。 |
| **Windows** | 暂未提供完整支持。可以按照 Espressif 官方方式构建和烧录固件，但 Windows 版 bridge 安装、HUD、Codex 桌面控制及自动粘贴尚未实现。 |

因此，下面涉及电脑端集成的步骤以 macOS 为准；纯固件构建和烧录步骤可参考 Espressif 的对应平台文档执行。

## 开始前的准备

- [ ] M5Stack StickS3｜一根 USB-C 数据线｜一台 Mac
- [ ] Wi-Fi（必须是 2.4GHz） 名称｜Wi-Fi密码｜语音识别模型 API Key
- [ ] 语音转写 API Key。默认示例使用与 OpenAI 接口兼容的 [SiliconFlow](https://cloud.siliconflow.cn/)；也可以改用其他兼容服务的 `base_url` 和模型名称。

<p align="center"><strong>初始化 → 配置 → 烧录 → 安装 bridge → 验证</strong></p>

## 安装

你可以手动执行，也可以交给 Codex。

> 说明：标 👤 的步骤是需要人亲自动手的物理操作，例如插线、长按/短按电源键、在系统设置里授权。AI agent 请按顺序执行 shell 步骤，执行到 👤 步骤时暂停，让用户完成后再继续。

1. 进入本地工程并创建配置文件：

```sh
cd VibeStick-Codex
./scripts/setup.sh
```

2. 填入人类提前准备好的配置：

```sh
open -e firmware/sticks3/include/vibe_stick_secrets.h
open -e .env
```

在 `vibe_stick_secrets.h` 里填写 Wi-Fi 名称、Wi-Fi 密码、Mac bridge host。只要文件里还保留示例占位值，`scripts/setup.sh` 会尝试把 `VIBE_STICK_BRIDGE_HOST` 自动写成检测到的 en0 局域网 IP。

在 `.env` 里填写 ASR key 和需要的 provider 设置。默认推荐 SiliconFlow：

```sh
VIBE_STICK_ASR_PROVIDER=openai-compatible
VIBE_STICK_ASR_BASE_URL=https://api.siliconflow.cn/v1
VIBE_STICK_ASR_API_KEY=your-siliconflow-key
VIBE_STICK_ASR_MODEL=FunAudioLLM/SenseVoiceSmall
```

3. 👤 用 USB-C 数据线把 StickS3 插到 Mac。

4. 👤 让 StickS3 进入下载模式：长按侧面电源键，直到蓝灯双闪、屏幕熄灭。这是 ESP32-S3 烧录必需步骤。

5. 如果本机还没有 ESP-IDF，先安装；然后把它加载到当前 shell。这是一次性工具链安装，下载较大（约 1GB），可能需要几分钟。每开一个新终端，在运行 `idf.py` 前都要先执行加载命令：

```sh
if [ ! -d "$HOME/esp/esp-idf" ]; then
  mkdir -p ~/esp && cd ~/esp
  git clone -b v5.5.1 --recursive https://github.com/espressif/esp-idf.git
  cd esp-idf && ./install.sh esp32s3
fi
. "$HOME/esp/esp-idf/export.sh"
```

也可以按 Espressif [官方指南](https://docs.espressif.com/projects/esp-idf/en/v5.5.1/esp32s3/get-started/index.html)安装。如果 `install.sh` 失败，请确认已安装 `git`、`python3`、`cmake`，或改按官方指南处理。如果 ESP-IDF 安装在其他位置，请调整路径。

6. 构建并烧录固件：

```sh
cd firmware/sticks3
idf.py -p <port> build flash
cd ../..
```

如果不知道端口，运行：

```sh
ls /dev/cu.*
```

等到终端出现 `Hash of data verified`。

7. 👤 短按电源键唤醒屏幕。蓝灯应熄灭、屏幕亮起，此时应看到 VibeStick 首页。联网前可能显示离线。

8. 安装本机 macOS bridge 和 HUD：

```sh
./scripts/install.sh
```

9. 👤 当 macOS 弹出 `python3.14` 想用辅助功能控制这台电脑时，点击“打开系统设置”并勾选允许。粘贴转写结果需要这个权限。

10. 检查安装状态：

```sh
./scripts/doctor.sh
```

尽量让必须项全部 PASS。然后看一眼 StickS3：顶部应显示 Wi-Fi、时间和电量，中间显示 Codex 状态，下面显示 `1W FUNDS / 5H FUNDS / TODAY / TOKEN`。

11. 👤 测试正面蓝键和侧键：

- 正面蓝键短按：打开 Codex 或把 Codex 窗口带到前台；等待确认时发送允许。
- 正面蓝键双击：刷新 `1W FUNDS / 5H FUNDS / TODAY / TOKEN`。
- 正面蓝键长按：录音；松开后转写并填入 Codex，等待手动发送。
- 侧键短按：跨项目批准全部等待中的 Codex 任务；没有待批准任务时发送当前输入。
- 侧键双击：清空当前输入框中的文本。
- 侧键快速三连击：如果已经安装兼容的双固件布局，切换到 `ota_0` 中的沙漏并重启。
- 侧键长按：新建 Codex 对话。

开发调试时可以用 `./scripts/dev.sh` 替代 `./scripts/install.sh`，它会在当前终端里运行 bridge。

安装或更新沙漏前，请先阅读[双固件安装与切换](docs/MULTI_FIRMWARE.zh-CN.md)。

## 常见问题排查

### `command not found: idf.py`

ESP-IDF 没有加载到当前 shell，或者还没有安装。先 source ESP-IDF 的 `export.sh`，再运行 `idf.py`：

```sh
. $HOME/esp/esp-idf/export.sh
```

如果你的 ESP-IDF 在其他位置，请调整路径。每开一个新终端，在使用 `idf.py` 前都要运行一次。

### 烧录报 "Device not configured" 或连不上串口

重新插拔 USB-C 数据线。再次进入下载模式：长按侧面电源键，直到蓝灯双闪、屏幕熄灭。运行 `ls /dev/cu.*` 找端口，然后重试 `idf.py -p <port> build flash`。

### StickS3 连不上 Wi-Fi

请使用 2.4GHz Wi-Fi。StickS3 / ESP32-S3 不支持 5GHz Wi-Fi。

### 录音能转写但没有粘贴

给执行粘贴的 Python runner 开辅助功能权限。macOS 路径：系统设置 -> 隐私与安全性 -> 辅助功能，然后允许 `python3.14` 或运行 VibeStick 的终端 / 启动器。

### "No transcription adapter configured"

在 `.env` 里配置 ASR，尤其是 `VIBE_STICK_ASR_PROVIDER`、`VIBE_STICK_ASR_BASE_URL`、`VIBE_STICK_ASR_API_KEY`，然后重新安装：

```sh
./scripts/install.sh
```

### 找不到 `.env`

`.env` 是隐藏文件。用下面命令打开：

```sh
open -e .env
```

### 录音转写失败、SSL 报错或超时

通常是当前网络访问不到所选 ASR 服务。请配置当前网络可访问的 OpenAI 兼容 ASR 服务，或配置网络代理。

## 配置说明

不要把真实 API key、本地 token、Wi-Fi 密码、本地日志、录音文件提交到 git。

`.env` 里的空值通常表示“使用内置默认值”。`scripts/dev.sh` 会读取仓库根目录的 `.env`。`scripts/install.sh` 会把 `.env` 复制到 `~/Library/Application Support/VibeStick/.env`，LaunchAgent 运行时读取安装后的文件。

### 核心设置

- `VIBE_STICK_PROJECT_ROOT`：本地 Codex session 观察路径。
- `VIBE_STICK_PROJECT_NAME`：可选显示名称。
- `VIBE_STICK_BRIDGE_TOKEN`：bridge 绑定到非 loopback 地址时必需的共享 token，例如 `0.0.0.0`。
- `VIBE_STICK_MAX_RECORDING_AUDIO_BYTES`：`/recording/audio` 最大请求体大小，默认 `2000000`。
- `VIBE_STICK_RECORDING_USE_MAC_MIC`：设为 `0` 可关闭 Mac 麦克风兜底。
- `VIBE_STICK_RETAIN_RECORDINGS`：录音默认在处理后删除；只有确实需要调试时才设为 `1`。
- `VIBE_STICK_AUTO_ENTER`：设为 `1` 会在粘贴后自动按 Return。

### ASR 方案 1：SiliconFlow（默认推荐）

```sh
VIBE_STICK_ASR_PROVIDER=openai-compatible
VIBE_STICK_ASR_BASE_URL=https://api.siliconflow.cn/v1
VIBE_STICK_ASR_API_KEY=your-siliconflow-key
VIBE_STICK_ASR_MODEL=FunAudioLLM/SenseVoiceSmall
VIBE_STICK_ASR_LANGUAGE=zh
VIBE_STICK_ASR_TIMEOUT_SECONDS=15
VIBE_STICK_ASR_ATTEMPTS=2
```

使用云端 ASR 时，音频会离开本机 Mac。

### ASR 方案 2：任意 OpenAI 兼容服务

只要服务支持 `POST {base_url}/audio/transcriptions` 即可。

```sh
VIBE_STICK_ASR_PROVIDER=openai-compatible
VIBE_STICK_ASR_BASE_URL=https://example.com/v1
VIBE_STICK_ASR_API_KEY=your-api-key
VIBE_STICK_ASR_MODEL=provider-model-name
```

Groq 也作为海外可选 preset 保留：

```sh
VIBE_STICK_ASR_PROVIDER=groq
VIBE_STICK_ASR_API_KEY=your-groq-key
```

旧别名 `VIBE_STICK_GROQ_API_KEY`、`VIBE_STICK_GROQ_MODEL`、`VIBE_STICK_GROQ_LANGUAGE` 仍然支持。

### ASR 方案 3：本地命令（离线）

```sh
VIBE_STICK_TRANSCRIBE_CMD=/path/to/transcribe-command
VIBE_STICK_TRANSCRIBE_TIMEOUT_SECONDS=120
```

这个命令会从 stdin 收到录音 session JSON，并应把最终转写文本打印到 stdout。

## 隐私

- Bridge 不包含统计分析或遥测。
- Bridge 可从局域网访问时，状态读取和控制接口都需要共享 Token。
- 本地运行文件只允许当前 macOS 用户访问。
- 完整转写正文不会持久保存，录音默认在处理结束后删除。
- StickS3 与 Mac 使用未加密的局域网 HTTP；只应使用可信私人 Wi-Fi，绝不能把 `8765` 端口暴露到互联网。
- 使用云端 ASR 时，录音会发送给所配置的服务商。

完整说明见[隐私与数据流](docs/PRIVACY.zh-CN.md)。

## 项目结构

```text
VibeStick-Codex/
  README.md
  README.zh-CN.md
  .env.example
  docs/
  firmware/sticks3/
  bridge/src/vibe_stick/
  app/macos/VibeStickHUD/
  scripts/
  tests/
```

## 检查命令

```sh
python3 -m compileall -q bridge/src tests
PYTHONPATH=bridge/src python3 -m unittest discover -s tests
bash -n scripts/setup.sh scripts/doctor.sh scripts/install.sh
```

固件构建仍需要 ESP-IDF：

```sh
cd firmware/sticks3
. $HOME/esp/esp-idf/export.sh
idf.py build
```

## 当前限制

- 这是整理后的原型，不是打包好的 Mac app 或 DMG。
- 固件只面向 M5Stack StickS3。
- 当月 Token 和美元数值来自本机可观察到的 Codex session 记录；记录不完整时统计也可能不完整，美元数值只是 API 等值估算，不代表账户实际账单。
- ASR 可靠性取决于麦克风采集、上传 PCM 质量、provider 可达性和模型配置。

## 贡献与安全

欢迎贡献,详见 [CONTRIBUTING.md](CONTRIBUTING.md)。报告安全漏洞请见
[SECURITY.md](SECURITY.md)(请私下报告)。

## 版权、素材与许可证说明

VibeStick 原始软件版权归 Gary Zhang 所有，Copyright (c) 2026 Gary Zhang；
VibeStick-Codex 的修改部分版权归 Oliver Xing 所有，Copyright (c) 2026
Oliver Xing。原始软件及本项目修改均依据仓库内的
[MIT License](LICENSE) 发布，并保留双方版权声明。

除文件另有说明外，本仓库新增的 Codex 专用 Bridge、macOS HUD、StickS3
固件修改、简洁的 provider/status 图标、截图、设备效果图和像素状态动画，均
适用本仓库的 MIT License。该说明不会改变第三方素材原有的许可证，也不授予
任何第三方名称或商标的权利。

横屏仪表盘的视觉设计和信息结构参考了
[CharlexH/CodeBuddy](https://github.com/CharlexH/CodeBuddy)，并使用 ESP-IDF
与 LVGL 独立重新实现；本仓库没有再分发 CodeBuddy 的源代码或美术素材。

第三方组件继续适用各自许可证。其中，生成的 Noto Sans SC 字形子集适用仓库
内附的
[SIL Open Font License 1.1](firmware/sticks3/third_party/noto-sans-sc/OFL.txt)；
BMI270 驱动保留其随附的上游许可证；ESP-IDF、LVGL 和托管组件分别适用其
各自许可条款。完整署名和二进制分发说明见 [NOTICE](NOTICE) 与
[第三方来源审计](docs/THIRD_PARTY_AUDIT.md)。

M5Stack、StickS3、OpenAI 和 Codex 的名称与商标归各自权利人所有，本项目仅
为说明兼容性和集成关系而使用。本项目是独立的社区项目，与 M5Stack 或 OpenAI
不存在隶属、授权或官方产品关系，也不代表获得其背书。
