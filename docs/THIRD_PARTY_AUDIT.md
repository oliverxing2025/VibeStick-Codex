# Third-Party Audit

This audit documents the v0.1.1 repository state after cleanup.

| Project / file / dependency | Source | Current use | License status | Risk | Recommendation |
| --- | --- | --- | --- | --- | --- |
| VibeStick base project | [GaryGaryyy/VibeStick](https://github.com/GaryGaryyy/VibeStick) | Original application, bridge, firmware, documentation, and project structure subsequently modified for VibeStick-Codex | MIT; original copyright and license retained in `LICENSE` and `NOTICE` | Low | Keep attribution and the complete MIT license with redistributed copies or substantial portions. |
| Landscape dashboard reference | [CharlexH/CodeBuddy](https://github.com/CharlexH/CodeBuddy) | Visual design and information-architecture reference for the landscape status dashboard, including compact task counters and activity matrix; independently reimplemented with ESP-IDF and LVGL | CodeBuddy StickS3 firmware is MIT-licensed; no CodeBuddy source code or artwork is redistributed here | Low | Keep the reference attribution in `NOTICE`. If CodeBuddy code or assets are introduced later, retain the applicable copyright and license text and update this audit. |
| `bridge/src/vibe_stick/` | Project-authored Python | Local Mac bridge, state API, quota observation, recording flow, ASR adapter, paste injection | MIT under this repository | Low | Keep. |
| `app/macos/VibeStickHUD/main.swift` | Project-authored Swift | Minimal recording status HUD | MIT under this repository | Low | Keep. |
| `firmware/sticks3/src/` and `firmware/sticks3/include/` | Project-authored C using ESP-IDF APIs | StickS3 UI, HTTP, buttons, audio, battery, speaker alerts | MIT under this repository | Low | Keep. |
| `assets/brand/vibestick-icon.svg` | Project-generated simple geometry | Temporary VibeStick brand icon | MIT under this repository | Low | Keep until polished branding exists. |
| `assets/providers/**` and `firmware/sticks3/assets/providers/**` | Project-generated simple geometry | Temporary provider/status icons | MIT under this repository | Low | Keep. Avoid replacing with third-party brand marks unless license/brand usage is reviewed. |
| `firmware/sticks3/generated/vibe_stick_ui_assets.c/.h` | Generated from project-owned PNG icons | LVGL image descriptors for provider icons | MIT under this repository | Low | Keep. |
| `firmware/sticks3/generated/vibe_stick_cn_16.c` | Generated from Noto Sans SC Regular | LVGL Chinese glyph subset for StickS3 UI | Source font is SIL Open Font License 1.1 | Medium | Keep with NOTICE attribution. Do not use the reserved font name as a VibeStick brand. |
| `firmware/sticks3/third_party/bmi270/` | Bosch Sensortec BMI270 Sensor API | Vendored IMU driver source | BSD-3-Clause-style license retained with the source | Low | Keep the source headers and bundled license intact. |
| `firmware/sticks3/src/idf_component.yml` dependencies: `espressif/button`, `espressif/esp_codec_dev`, `lvgl/lvgl` | ESP Component Registry | Build-time firmware dependencies | External open-source components, not vendored after cleanup | Low | Keep dependency manifest and lock file. Review component licenses before binary release. |
| ESP-IDF framework | Espressif | Firmware framework | External SDK, not vendored | Low | Keep as build prerequisite. |
| Groq ASR API | Optional external service | Optional speech-to-text when configured | Service API, no source vendored | Medium | Document that audio leaves the Mac when Groq is configured. Do not commit API keys. |
| Local Codex session files | User-local Codex data | Quota/status observation from `~/.codex/sessions/**/*.jsonl` | User-local data, not vendored | Medium | Keep local-only. Do not upload or commit session data. |
| Historical VoiceStick / StickS3VoiceKit / VoiceStickTrial directories outside this repository | Local historical reference directories in the parent workspace | Not part of VibeStick repository | Source/license uncertain from local copy | High | Do not copy into VibeStick. Do not publish as part of this repository. |
| Old provider logo-like assets removed during cleanup | Earlier local prototype assets | No longer used | Source unclear / brand risk | High | Replaced with simple project-generated temporary icons. |
| `firmware/sticks3/managed_components/`, `firmware/sticks3/build/`, Python `__pycache__/` | Generated local build/cache output | Not part of source | N/A | Low | Ignored by git. Do not commit. |
| `firmware/sticks3/include/vibe_stick_secrets.h`, `.env`, logs, recordings | Local user secrets/output | Runtime configuration and generated data | Private user data | High | Ignored by git. Never publish. |

## Summary

This repository is derived from Gary Zhang's MIT-licensed VibeStick project. The original copyright and MIT permission notice are retained in `LICENSE` and the relationship is documented in `NOTICE`. The landscape dashboard acknowledges CodeBuddy as a visual and information-architecture reference; its implementation is project-authored ESP-IDF/LVGL code, and no CodeBuddy source code or artwork is redistributed here. Vendored third-party materials are limited to the Bosch BMI270 driver and the generated Chinese LVGL glyph subset derived from Noto Sans SC; their license notices remain with the repository. Other build-time firmware dependencies are resolved through the ESP-IDF component manager.

Before a public binary release, review the exact ESP-IDF/component licenses included in the firmware image and ensure the Noto Sans SC attribution remains in NOTICE.
