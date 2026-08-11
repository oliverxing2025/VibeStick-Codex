#!/usr/bin/env sh
set -eu
umask 077

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
SETUP_PATH="$ROOT_DIR/scripts/setup.sh"
ENV_PATH="$ROOT_DIR/.env"
SECRETS_PATH="$ROOT_DIR/firmware/sticks3/include/vibe_stick_secrets.h"
CONFIG_DIR="$HOME/Library/Application Support/VibeStick"
RUNTIME_DIR="$CONFIG_DIR/runtime"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$LAUNCH_AGENTS_DIR/com.vibestick.bridge.plist"
HUD_PLIST_PATH="$LAUNCH_AGENTS_DIR/com.vibestick.hud.plist"
RUNNER_PATH="$CONFIG_DIR/run-bridge.sh"
HUD_BINARY_PATH="$CONFIG_DIR/VibeStickHUD"
HUD_SOURCE_PATH="$ROOT_DIR/app/macos/VibeStickHUD/main.swift"

is_placeholder_token() {
  case "${1:-}" in
    ""|change-this-shared-token|paste-generated-token-here|changeme|change-me|your-token)
      return 0
      ;;
  esac
  return 1
}

env_value() {
  key="$1"
  file="$2"
  [ -f "$file" ] || return 0
  awk -F= -v key="$key" '
    /^[[:space:]]*#/ { next }
    {
      k = $1
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", k)
      if (k == key) {
        sub(/^[^=]*=/, "")
        gsub(/^[[:space:]]+|[[:space:]]+$/, "")
        gsub(/^"/, "")
        gsub(/"$/, "")
        print
        exit
      }
    }
  ' "$file"
}

secret_value() {
  key="$1"
  file="$2"
  [ -f "$file" ] || return 0
  awk -v key="$key" '
    $1 == "#define" && $2 == key {
      value = $0
      sub(/^[^"]*"/, "", value)
      sub(/".*$/, "", value)
      print value
      exit
    }
  ' "$file"
}

require_bridge_token_ready() {
  env_token="$(env_value VIBE_STICK_BRIDGE_TOKEN "$ENV_PATH")"
  secret_token="$(secret_value VIBE_STICK_BRIDGE_TOKEN "$SECRETS_PATH")"

  if is_placeholder_token "$env_token"; then
    printf '%s\n' "VIBE_STICK_BRIDGE_TOKEN is required because install.sh exposes the bridge on 0.0.0.0." >&2
    printf '%s\n' "Run scripts/setup.sh to generate and sync the bridge token." >&2
    exit 1
  fi
  if is_placeholder_token "$secret_token"; then
    printf '%s\n' "Firmware VIBE_STICK_BRIDGE_TOKEN is missing or still a placeholder." >&2
    printf '%s\n' "Run scripts/setup.sh to sync the same token into firmware secrets." >&2
    exit 1
  fi
  if [ "$env_token" != "$secret_token" ]; then
    printf '%s\n' "VIBE_STICK_BRIDGE_TOKEN differs between .env and firmware secrets." >&2
    printf '%s\n' "Refusing to install because the device would receive 401 responses for protected POST requests." >&2
    exit 1
  fi
}

sh "$SETUP_PATH"
require_bridge_token_ready

if [ -f "$ENV_PATH" ]; then
  set -a
  . "$ENV_PATH"
  set +a
fi

BRIDGE_PORT="${VIBE_STICK_BRIDGE_PORT:-8765}"
BRIDGE_PYTHON="${VIBE_STICK_PYTHON:-$(command -v python3)}"
case "$BRIDGE_PORT" in
  *[!0-9]*|"")
    printf '%s\n' "VIBE_STICK_BRIDGE_PORT must be a numeric TCP port." >&2
    exit 1
    ;;
esac
if ! "$BRIDGE_PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
  printf '%s\n' "VibeStick Bridge requires Python 3.11 or newer." >&2
  exit 1
fi

mkdir -p "$CONFIG_DIR"
mkdir -p "$LAUNCH_AGENTS_DIR"
chmod 700 "$CONFIG_DIR"
rm -rf "$RUNTIME_DIR"
mkdir -p "$RUNTIME_DIR"
chmod 700 "$RUNTIME_DIR"
cp -R "$ROOT_DIR/bridge" "$RUNTIME_DIR/bridge"
if [ -f "$ENV_PATH" ]; then
  cp "$ENV_PATH" "$CONFIG_DIR/.env"
  chmod 600 "$CONFIG_DIR/.env"
fi
swiftc "$HUD_SOURCE_PATH" -o "$HUD_BINARY_PATH" -framework AppKit -framework QuartzCore
cat > "$RUNNER_PATH" <<RUNNER
#!/usr/bin/env sh
set -eu
cd "$CONFIG_DIR"
if [ -f "$CONFIG_DIR/.env" ]; then
  set -a
  . "$CONFIG_DIR/.env"
  set +a
fi
PYTHONPATH="$RUNTIME_DIR/bridge/src" exec "$BRIDGE_PYTHON" -m vibe_stick --host 0.0.0.0 --port $BRIDGE_PORT
RUNNER
chmod +x "$RUNNER_PATH"

cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.vibestick.bridge</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/sh</string>
    <string>$RUNNER_PATH</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$CONFIG_DIR</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$CONFIG_DIR/bridge.log</string>
  <key>StandardErrorPath</key>
  <string>$CONFIG_DIR/bridge.err.log</string>
</dict>
</plist>
PLIST

cat > "$HUD_PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.vibestick.hud</string>
  <key>ProgramArguments</key>
  <array>
    <string>$HUD_BINARY_PATH</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$CONFIG_DIR/hud.log</string>
  <key>StandardErrorPath</key>
  <string>$CONFIG_DIR/hud.err.log</string>
</dict>
</plist>
PLIST

chmod 700 "$RUNNER_PATH"
chmod 600 "$PLIST_PATH" "$HUD_PLIST_PATH"

launchctl bootout "gui/$(id -u)" "$PLIST_PATH" >/dev/null 2>&1 || true
launchctl bootout "gui/$(id -u)" "$HUD_PLIST_PATH" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
launchctl bootstrap "gui/$(id -u)" "$HUD_PLIST_PATH"
launchctl kickstart -k "gui/$(id -u)/com.vibestick.bridge"
launchctl kickstart -k "gui/$(id -u)/com.vibestick.hud"

printf '%s\n' "VibeStick config directory is ready:"
printf '%s\n' "$CONFIG_DIR"
printf '%s\n' "VibeStick Bridge LaunchAgent installed:"
printf '%s\n' "$PLIST_PATH"
printf '%s\n' "VibeStick Bridge HUD LaunchAgent installed:"
printf '%s\n' "$HUD_PLIST_PATH"
printf '%s\n' "Voice service settings:"
printf '%s\n' "http://127.0.0.1:$BRIDGE_PORT/setup/voice"
if command -v open >/dev/null 2>&1; then
  open "http://127.0.0.1:$BRIDGE_PORT/setup/voice" >/dev/null 2>&1 || true
fi
