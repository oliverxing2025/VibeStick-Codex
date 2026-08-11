#!/bin/sh
set -eu

if ! /usr/bin/osascript -e 'display dialog "卸载 VibeStick Bridge 的开机启动项和应用？\n\n私有配置和 API Key 会保留，除非你之后手动删除。" buttons {"取消", "卸载"} default button "卸载" cancel button "取消" with title "VibeStick Bridge"' >/dev/null; then
  exit 0
fi

domain="gui/$(id -u)"
bridge_plist="$HOME/Library/LaunchAgents/com.vibestick.bridge.plist"
hud_plist="$HOME/Library/LaunchAgents/com.vibestick.hud.plist"
/bin/launchctl bootout "$domain" "$bridge_plist" >/dev/null 2>&1 || true
/bin/launchctl bootout "$domain" "$hud_plist" >/dev/null 2>&1 || true
/bin/rm -f "$bridge_plist" "$hud_plist"

for app_path in "$HOME/Applications/VibeStick Bridge.app" "/Applications/VibeStick Bridge.app"; do
  if [ -d "$app_path" ]; then
    /usr/bin/osascript - "$app_path" <<'APPLESCRIPT' >/dev/null 2>&1 || true
on run argv
  tell application "Finder" to delete POSIX file (item 1 of argv)
end run
APPLESCRIPT
  fi
done

/usr/bin/osascript -e 'display alert "VibeStick Bridge 已卸载" message "开机启动项和应用已移到废纸篓。私有配置仍保留在 ~/Library/Application Support/VibeStick。"' >/dev/null 2>&1 || true
