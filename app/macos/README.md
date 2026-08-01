# VibeStick macOS App Helpers

This directory contains macOS helper code for the VibeStick prototype.

## Current v0.2.0 Scope

- `VibeStickHUD/main.swift` is a small AppKit HUD process.
- It reads `~/Library/Application Support/VibeStick/hud-state.json`.
- It shows only recording flow state such as listening, sending, transcribing, failed, and unclear.
- It is launched by `scripts/install.sh` as `com.vibestick.hud`.

v0.2.0 does not build a packaged Mac App, DMG, Sparkle feed, or notarized installer. That work is planned for a later release.
