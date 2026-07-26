# Changelog

## v0.1.4

Initial public release of VibeStick — a tiny desktop companion for coding agents on M5Stack StickS3.

- Home screen shows Wi-Fi, time, battery, Codex status, quota remaining, usage consumed, and today's token use.
- Push-to-talk voice input records on the StickS3, transcribes via any OpenAI-compatible ASR (e.g. SiliconFlow), then enters the prompt in Codex for manual submission.
- Front and side button gestures focus Codex, refresh usage, send or clear the current input, create a chat, and approve active requests.
- Alerts (done / approval / error) play from whichever provider raises them, on the StickS3 speaker.
- First-run helpers (`scripts/setup.sh`, `scripts/doctor.sh`), bridge token authentication, and a bilingual README (English + 中文) with clearly-marked physical steps.

Licensed under MIT.
