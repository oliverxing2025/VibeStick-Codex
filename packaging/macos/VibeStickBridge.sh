#!/bin/sh
set -eu
umask 077

APP_NAME="VibeStick Bridge.app"
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
APP_BUNDLE=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
TARGET_APP="$HOME/Applications/$APP_NAME"
CONFIG_DIR="$HOME/Library/Application Support/VibeStick"
ENV_PATH="$CONFIG_DIR/.env"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
BRIDGE_PLIST="$LAUNCH_AGENTS_DIR/com.vibestick.bridge.plist"
HUD_PLIST="$LAUNCH_AGENTS_DIR/com.vibestick.hud.plist"
SETTINGS_URL="http://127.0.0.1:8765/setup/voice"

bridge_core="$APP_BUNDLE/Contents/Resources/bridge/VibeStickBridgeCore"
hud_binary="$APP_BUNDLE/Contents/Resources/VibeStickHUD"

if [ "${1:-}" = "--bridge" ]; then
  cd "$CONFIG_DIR"
  exec "$bridge_core" --host 0.0.0.0 --port 8765
fi

if [ "${1:-}" = "--hud" ]; then
  exec "$hud_binary"
fi

install_app_copy() {
  if [ "$APP_BUNDLE" = "$TARGET_APP" ] ||
     [ "$APP_BUNDLE" = "/Applications/$APP_NAME" ]; then
    return
  fi
  mkdir -p "$HOME/Applications"
  staging="$HOME/Applications/.VibeStick Bridge.$$.app"
  rm -rf "$staging"
  /usr/bin/ditto "$APP_BUNDLE" "$staging"
  rm -rf "$TARGET_APP"
  mv "$staging" "$TARGET_APP"
  /usr/bin/open "$TARGET_APP"
  exit 0
}

xml_escape() {
  printf '%s' "$1" | /usr/bin/sed \
    -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g' \
    -e 's/"/\&quot;/g' -e "s/'/\&apos;/g"
}

create_private_config() {
  mkdir -p "$CONFIG_DIR"
  chmod 700 "$CONFIG_DIR"
  if [ -f "$ENV_PATH" ]; then
    chmod 600 "$ENV_PATH"
    return
  fi
  token=$(/usr/bin/openssl rand -hex 32)
  cat > "$ENV_PATH" <<EOF
VIBE_STICK_BRIDGE_TOKEN=$token
VIBE_STICK_ASR_PROVIDER=openai-compatible
VIBE_STICK_ASR_BASE_URL=https://api.siliconflow.cn/v1
VIBE_STICK_ASR_API_KEY=
VIBE_STICK_ASR_MODEL=FunAudioLLM/SenseVoiceSmall
VIBE_STICK_ASR_LANGUAGE=zh
VIBE_STICK_RETAIN_RECORDINGS=0
VIBE_STICK_RECORDING_USE_MAC_MIC=0
VIBE_STICK_AUTO_ENTER=0
EOF
  chmod 600 "$ENV_PATH"
  token=""
}

write_launch_agents() {
  mkdir -p "$LAUNCH_AGENTS_DIR"
  launcher_path=$(xml_escape "$APP_BUNDLE/Contents/MacOS/VibeStickBridge")
  cat > "$BRIDGE_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "https://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.vibestick.bridge</string>
<key>ProgramArguments</key><array>
<string>$launcher_path</string><string>--bridge</string>
</array>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><true/>
<key>ProcessType</key><string>Interactive</string>
</dict></plist>
PLIST
  cat > "$HUD_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "https://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.vibestick.hud</string>
<key>ProgramArguments</key><array>
<string>$launcher_path</string><string>--hud</string>
</array>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><true/>
<key>ProcessType</key><string>Interactive</string>
</dict></plist>
PLIST
  chmod 600 "$BRIDGE_PLIST" "$HUD_PLIST"
  /usr/bin/plutil -lint "$BRIDGE_PLIST" >/dev/null
  /usr/bin/plutil -lint "$HUD_PLIST" >/dev/null
}

start_services() {
  domain="gui/$(id -u)"
  /bin/launchctl bootout "$domain" "$BRIDGE_PLIST" >/dev/null 2>&1 || true
  /bin/launchctl bootout "$domain" "$HUD_PLIST" >/dev/null 2>&1 || true
  /bin/launchctl bootstrap "$domain" "$BRIDGE_PLIST"
  /bin/launchctl bootstrap "$domain" "$HUD_PLIST"
  /bin/launchctl kickstart -k "$domain/com.vibestick.bridge"
  /bin/launchctl kickstart -k "$domain/com.vibestick.hud"
}

open_pairing_page() {
  attempts=0
  while [ "$attempts" -lt 30 ]; do
    if /usr/bin/curl --fail --silent --max-time 1 http://127.0.0.1:8765/health >/dev/null 2>&1; then
      /usr/bin/open "$SETTINGS_URL"
      /usr/bin/osascript -e 'display notification "Bridge 已启动，配对码页面已打开" with title "VibeStick Bridge"' >/dev/null 2>&1 || true
      return
    fi
    attempts=$((attempts + 1))
    sleep 0.2
  done
  /usr/bin/osascript -e 'display alert "VibeStick Bridge 启动失败" message "请重新打开应用；如果端口 8765 被占用，请先关闭占用该端口的程序。" as critical' >/dev/null 2>&1 || true
  exit 1
}

install_app_copy
create_private_config
write_launch_agents
start_services
open_pairing_page
