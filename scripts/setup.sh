#!/usr/bin/env sh
set -eu
umask 077

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
ENV_PATH="$ROOT_DIR/.env"
ENV_EXAMPLE_PATH="$ROOT_DIR/.env.example"
SECRETS_PATH="$ROOT_DIR/firmware/sticks3/include/vibe_stick_secrets.h"
SECRETS_EXAMPLE_PATH="$ROOT_DIR/firmware/sticks3/include/vibe_stick_secrets.example.h"

is_placeholder_token() {
  case "${1:-}" in
    ""|change-this-shared-token|paste-generated-token-here|changeme|change-me|your-token)
      return 0
      ;;
  esac
  return 1
}

is_placeholder_host() {
  case "${1:-}" in
    ""|127.0.0.1|0.0.0.0|192.168.1.10|192.168.0.10|10.0.0.10|YOUR_MAC_IP|your-mac-ip)
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

set_env_value() {
  key="$1"
  value="$2"
  file="$3"
  tmp="$file.tmp.$$"
  awk -v key="$key" -v value="$value" '
    BEGIN { done = 0 }
    /^[[:space:]]*#/ { print; next }
    {
      line = $0
      k = line
      sub(/=.*/, "", k)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", k)
      if (k == key) {
        print key "=" value
        done = 1
        next
      }
      print
    }
    END {
      if (!done) {
        print key "=" value
      }
    }
  ' "$file" > "$tmp"
  mv "$tmp" "$file"
}

set_secret_value() {
  key="$1"
  value="$2"
  file="$3"
  tmp="$file.tmp.$$"
  awk -v key="$key" -v value="$value" '
    BEGIN { done = 0 }
    $1 == "#define" && $2 == key {
      print "#define " key " \"" value "\""
      done = 1
      next
    }
    { print }
    END {
      if (!done) {
        print "#define " key " \"" value "\""
      }
    }
  ' "$file" > "$tmp"
  mv "$tmp" "$file"
}

if [ ! -f "$ENV_PATH" ]; then
  cp "$ENV_EXAMPLE_PATH" "$ENV_PATH"
  printf '%s\n' "Created .env from .env.example."
else
  printf '%s\n' "Kept existing .env."
fi

if [ ! -f "$SECRETS_PATH" ]; then
  cp "$SECRETS_EXAMPLE_PATH" "$SECRETS_PATH"
  printf '%s\n' "Created firmware/sticks3/include/vibe_stick_secrets.h from example."
else
  printf '%s\n' "Kept existing firmware/sticks3/include/vibe_stick_secrets.h."
fi

chmod 600 "$ENV_PATH" "$SECRETS_PATH"

env_token="$(env_value VIBE_STICK_BRIDGE_TOKEN "$ENV_PATH")"
secret_token="$(secret_value VIBE_STICK_BRIDGE_TOKEN "$SECRETS_PATH")"

if ! is_placeholder_token "$env_token" && ! is_placeholder_token "$secret_token"; then
  if [ "$env_token" = "$secret_token" ]; then
    printf '%s\n' "Bridge token is already configured in both files."
  else
    printf '%s\n' "WARN: Bridge tokens are already set but differ; existing non-empty tokens were preserved."
    printf '%s\n' "      Run scripts/doctor.sh after deciding which token should be shared."
  fi
elif ! is_placeholder_token "$env_token"; then
  set_secret_value VIBE_STICK_BRIDGE_TOKEN "$env_token" "$SECRETS_PATH"
  printf '%s\n' "Copied existing .env bridge token into firmware secrets."
elif ! is_placeholder_token "$secret_token"; then
  set_env_value VIBE_STICK_BRIDGE_TOKEN "$secret_token" "$ENV_PATH"
  printf '%s\n' "Copied existing firmware bridge token into .env."
else
  if ! command -v openssl >/dev/null 2>&1; then
    printf '%s\n' "ERROR: openssl is required to generate VIBE_STICK_BRIDGE_TOKEN." >&2
    exit 1
  fi
  token="$(openssl rand -hex 32)"
  set_env_value VIBE_STICK_BRIDGE_TOKEN "$token" "$ENV_PATH"
  set_secret_value VIBE_STICK_BRIDGE_TOKEN "$token" "$SECRETS_PATH"
  printf '%s\n' "Generated and wrote one shared bridge token to .env and firmware secrets."
fi

lan_interface="$(route -n get default 2>/dev/null | awk '/interface:/{print $2; exit}')"
lan_ip="$(ipconfig getifaddr "${lan_interface:-en0}" 2>/dev/null || true)"
if [ -n "$lan_ip" ]; then
  printf '%s\n' "Detected Mac LAN IP on en0: $lan_ip"
  bridge_host="$(secret_value VIBE_STICK_BRIDGE_HOST "$SECRETS_PATH")"
  if [ "${VIBE_STICK_SYNC_BRIDGE_HOST:-0}" = "1" ]; then
    set_secret_value VIBE_STICK_BRIDGE_HOST "$lan_ip" "$SECRETS_PATH"
    printf '%s\n' "Updated VIBE_STICK_BRIDGE_HOST to the current LAN IP."
  elif is_placeholder_host "$bridge_host"; then
    set_secret_value VIBE_STICK_BRIDGE_HOST "$lan_ip" "$SECRETS_PATH"
    printf '%s\n' "Set VIBE_STICK_BRIDGE_HOST in firmware secrets to detected Mac LAN IP."
  elif [ "$bridge_host" = "$lan_ip" ]; then
    printf '%s\n' "VIBE_STICK_BRIDGE_HOST already matches detected Mac LAN IP."
  else
    printf '%s\n' "Kept existing VIBE_STICK_BRIDGE_HOST ($bridge_host); detected en0 IP is $lan_ip."
  fi
else
  printf '%s\n' "WARN: Could not detect a LAN IP from en0; set VIBE_STICK_BRIDGE_HOST manually."
fi

printf '\n%s\n' "Next steps:"
printf '%s\n' "1. Edit firmware/sticks3/include/vibe_stick_secrets.h with Wi-Fi SSID, password, and Mac IP."
printf '%s\n' "2. Optionally edit .env with ASR settings such as VIBE_STICK_ASR_PROVIDER and VIBE_STICK_ASR_API_KEY."
printf '%s\n' "3. Run scripts/doctor.sh to check the local setup before building or flashing."
