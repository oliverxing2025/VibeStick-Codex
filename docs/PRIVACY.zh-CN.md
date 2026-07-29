# 隐私与数据流

VibeStick-Codex 是一个本地优先的个人项目，不包含统计分析或遥测，但会处理
Codex 本地元数据、麦克风音频和凭据，应将这些内容视为隐私数据。

## 本地读取的数据

Bridge 会读取近期 Codex 本地 session 文件，用来计算设备需要的摘要状态：
项目文件夹名称、任务状态、确认状态、额度百分比、重置时间和 Token 总量。
它不会有意把提示词、回复正文或完整 Codex session 文件发送给 StickS3。

Bridge 还会使用 macOS 辅助功能权限执行聚焦、粘贴、发送、清空、新建对话和
批准操作；辅助功能数据不会上传。

## 本地保存的数据

运行数据保存在：

```text
~/Library/Application Support/VibeStick/
```

目录权限限制为当前用户可访问（`0700`），敏感文件写入权限为 `0600`。
最新完整转写正文不会持久保存。录音默认在处理结束后删除；只有确实需要调试
录音时才设置 `VIBE_STICK_RETAIN_RECORDINGS=1`。

`scripts/uninstall.sh` 会移除 LaunchAgent，但会有意保留配置目录。确认不再需要
凭据和缓存后，应手动删除该目录。

## 局域网通信

StickS3 与 Mac 通过局域网 HTTP 通信。Bridge 只要绑定到非本机回环地址，就
必须设置 `VIBE_STICK_BRIDGE_TOKEN`；状态读取和修改接口都需要这个 Token。

HTTP 不提供传输加密。共享 Token、摘要状态和 StickS3 麦克风音频可能以明文
经过局域网。只应在可信的私人 Wi-Fi 中使用；不要把 `8765` 端口暴露到互联网，
也不要在公共或不可信 Wi-Fi 中使用。

## 语音转写

配置 OpenAI 兼容的云端 ASR 后，录音会上传到 `base_url` 指定的服务商，并受
该服务商的隐私和保留政策约束。默认示例使用 HTTPS；不要配置不可信或明文
HTTP 的 ASR 地址。

如需离线转写，可配置 `VIBE_STICK_TRANSCRIBE_CMD`。自定义录音 Hook 或转写
命令属于用户自行提供的代码，会收到录音 session 元数据，包括本地音频路径。

## 凭据

Wi-Fi 凭据和 Bridge Token 会编译进本地固件镜像；ASR 凭据和 Bridge Token
保存在本地 `.env`。虽然这些文件已被 Git 忽略，但能够访问 Mac 账户、固件
镜像或设备 Flash 的人仍可能恢复凭据。建议使用权限受限的 API Key；设备丢失
或分享过固件镜像后应轮换凭据。

不要提交 `.env`、`vibe_stick_secrets.h`、录音、日志或本地 Codex session 文件。
