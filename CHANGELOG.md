# Changelog

## v0.3.0 — 2026-08-12

- Added first-boot and in-app two-button Wi-Fi provisioning through a
  password-protected temporary access point and local setup page. The temporary
  password is eight numeric digits, and nearby Wi-Fi networks are selectable.
- Stored Wi-Fi credentials in device-local NVS, retained the previous network
  during a change, and automatically restored it after repeated failures.
- Increased the firmware HTTP transmit buffer so authenticated StickS3 PCM
  uploads retain all audio metadata headers on every supported Bridge platform.
- Added a loopback-only voice-service settings page to the existing Bridge;
  API keys stay on the computer and are never echoed by the page.
- Added Windows preview implementations for Bridge packaging and autostart,
  Codex desktop shortcuts, automatic paste, configuration paths, and HUD, plus
  a Windows CI build. Real Windows-device acceptance is still pending.
- Added a self-contained Apple Silicon macOS DMG with an ad-hoc-signed Bridge
  app, HUD, per-user LaunchAgents, local pairing-token generation, and SHA-256.
- Replaced the Windows ZIP/PowerShell distribution with a single per-user
  Inno Setup EXE and matching SHA-256 artifact; it remains unsigned preview
  software until real Windows acceptance and signing are completed.

## v0.2.1

- Added authenticated LAN discovery so the StickS3 automatically follows Mac
  DHCP address changes at startup and reconnects after a bridge address change.
- Retained the configured bridge host only as a fallback when discovery is
  temporarily unavailable.

## v0.2.0

- Added animated pixel characters to the landscape dashboard for running, waiting for approval, and completed states.
- Made pending human approval take priority over ordinary recent Codex activity, so the dashboard reliably enters `WAITING` when action is required.
- Refined the landscape clock, battery, monthly-token label, quota matrix, and task-count layout for the compact StickS3 display.
- Added the reviewed animation source sheets, device previews, and firmware-ready sprite sheets under `assets/animations/`.
- Added regression coverage for pending approval detection and documented that the monthly Token value includes cached context within input tokens.

## v0.1.5

- Added calendar-month token totals and an API-equivalent USD estimate to the landscape dashboard.
- Added real battery level, five-hour and weekly reset countdowns, and local-day completion counts.
- Refined the landscape battery, countdown, divider, quota matrix, and TV icon alignment.
- Added hardware-MAC device profiles so separate StickS3 units cannot be mistaken for one another during flashing.
- Expanded bridge and protocol coverage for the new quota and monthly-usage fields.
- Replaced the landscape product image and documented every landscape and portrait metric.
- Prepared privacy-safe firmware artifacts with no embedded Wi-Fi, bridge, API, device, or local-path data.

## v0.1.4

Initial public release of VibeStick — a tiny desktop companion for coding agents on M5Stack StickS3.

- Home screen shows Wi-Fi, time, battery, Codex status, quota remaining, usage consumed, and today's token use.
- Push-to-talk voice input records on the StickS3, transcribes via any OpenAI-compatible ASR (e.g. SiliconFlow), then enters the prompt in Codex for manual submission.
- Front and side button gestures focus Codex, refresh usage, send or clear the current input, create a chat, and approve active requests.
- Alerts (done / approval / error) play from whichever provider raises them, on the StickS3 speaker.
- First-run helpers (`scripts/setup.sh`, `scripts/doctor.sh`), bridge token authentication, and a bilingual README (English + 中文) with clearly-marked physical steps.

Licensed under MIT.
