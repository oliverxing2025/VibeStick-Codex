# Changelog

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
