#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PYTHON_BIN=${PYTHON_BIN:-python3}
VERSION=$(
  PYTHONPATH="$ROOT_DIR/bridge/src" "$PYTHON_BIN" -c \
    'from vibe_stick import __version__; print(__version__)'
)
ARCH=$(uname -m)
case "$ARCH" in
  arm64) ARCH_LABEL="Apple-Silicon" ;;
  x86_64) ARCH_LABEL="Intel" ;;
  *) echo "Unsupported macOS architecture: $ARCH" >&2; exit 1 ;;
esac

if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "Python 3.11 or newer is required to build the Bridge." >&2
  exit 1
fi
if ! "$PYTHON_BIN" -m PyInstaller --version >/dev/null 2>&1; then
  echo "PyInstaller is required. Install it into the selected Python environment." >&2
  exit 1
fi

WORK_DIR=$(mktemp -d "${TMPDIR:-/tmp}/vibestick-macos.XXXXXX")
trap 'rm -rf "$WORK_DIR"' EXIT HUP INT TERM
export PYINSTALLER_CONFIG_DIR="$WORK_DIR/pyinstaller-cache"
APP_DIR="$WORK_DIR/VibeStick Bridge.app"
CONTENTS_DIR="$APP_DIR/Contents"
MACOS_DIR="$CONTENTS_DIR/MacOS"
RESOURCES_DIR="$CONTENTS_DIR/Resources"
PYINSTALLER_DIST="$WORK_DIR/pyinstaller-dist"
OUTPUT_DIR="$ROOT_DIR/dist"
DMG_NAME="VibeStick-Bridge-macOS-$ARCH_LABEL-v$VERSION.dmg"

mkdir -p "$MACOS_DIR" "$RESOURCES_DIR/bridge" "$PYINSTALLER_DIST" "$OUTPUT_DIR"

"$PYTHON_BIN" -m PyInstaller --noconfirm --clean --onedir \
  --name VibeStickBridgeCore \
  --paths "$ROOT_DIR/bridge/src" \
  --distpath "$PYINSTALLER_DIST" \
  --workpath "$WORK_DIR/pyinstaller-work" \
  --specpath "$WORK_DIR" \
  "$ROOT_DIR/bridge/src/vibe_stick/__main__.py"

/usr/bin/ditto "$PYINSTALLER_DIST/VibeStickBridgeCore" "$RESOURCES_DIR/bridge"
/usr/bin/swiftc "$ROOT_DIR/app/macos/VibeStickHUD/main.swift" \
  -o "$RESOURCES_DIR/VibeStickHUD" -framework AppKit -framework QuartzCore
/usr/bin/sed \
  -e "s/__VIBE_STICK_VERSION__/$VERSION/g" \
  -e "s/__VIBE_STICK_BUILD__/$(printf '%s' "$VERSION" | tr -cd '0-9')/g" \
  "$ROOT_DIR/packaging/macos/Info.plist" > "$CONTENTS_DIR/Info.plist"
/bin/cp "$ROOT_DIR/packaging/macos/VibeStickBridge.sh" "$MACOS_DIR/VibeStickBridge"
/bin/chmod 755 "$MACOS_DIR/VibeStickBridge" "$RESOURCES_DIR/VibeStickHUD" \
  "$RESOURCES_DIR/bridge/VibeStickBridgeCore"

/usr/bin/plutil -lint "$CONTENTS_DIR/Info.plist"
/usr/bin/codesign --force --deep --sign - "$APP_DIR"
/usr/bin/codesign --verify --deep --strict "$APP_DIR"

DMG_ROOT="$WORK_DIR/dmg"
mkdir -p "$DMG_ROOT"
/usr/bin/ditto "$APP_DIR" "$DMG_ROOT/VibeStick Bridge.app"
/bin/cp "$ROOT_DIR/packaging/macos/Uninstall VibeStick Bridge.command" \
  "$DMG_ROOT/Uninstall VibeStick Bridge.command"
/bin/chmod 755 "$DMG_ROOT/Uninstall VibeStick Bridge.command"
/bin/ln -s /Applications "$DMG_ROOT/Applications"
/bin/rm -f "$OUTPUT_DIR/$DMG_NAME" "$OUTPUT_DIR/$DMG_NAME.sha256"
/usr/bin/hdiutil create -quiet -volname "VibeStick Bridge $VERSION" \
  -srcfolder "$DMG_ROOT" -ov -format UDZO "$OUTPUT_DIR/$DMG_NAME"
(cd "$OUTPUT_DIR" && /usr/bin/shasum -a 256 "$DMG_NAME" > "$DMG_NAME.sha256")

echo "$OUTPUT_DIR/$DMG_NAME"
echo "$OUTPUT_DIR/$DMG_NAME.sha256"
