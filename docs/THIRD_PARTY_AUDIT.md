# Third-Party Audit

This audit documents the v0.1.5 repository and public firmware package.

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
| `firmware/sticks3/generated/vibe_stick_cn_16.c` | Generated from Noto Sans SC Regular | LVGL Chinese glyph subset for StickS3 UI | Source font is SIL Open Font License 1.1; complete text bundled at `firmware/sticks3/third_party/noto-sans-sc/OFL.txt` | Low | Keep the NOTICE attribution and bundled OFL text. Do not use the reserved font name as a VibeStick brand. |
| `firmware/sticks3/third_party/bmi270/` | Bosch Sensortec BMI270 Sensor API | Vendored IMU driver source | BSD-3-Clause-style license retained with the source | Low | Keep the source headers and bundled license intact. |
| `espressif/button` 4.2.0, `espressif/cmake_utilities` 1.1.1, and `espressif/esp_codec_dev` 1.5.10 | ESP Component Registry | Build-time firmware dependencies included in the linked image | Apache License 2.0; license texts verified in the resolved component sources | Low | Keep the dependency manifest/lock file and include Apache-2.0 in binary distributions. |
| `lvgl/lvgl` 9.2.0 | ESP Component Registry | UI library included in the linked image | MIT; `LICENCE.txt` verified in the resolved component source | Low | Include the LVGL MIT license in binary distributions. |
| ESP-IDF framework 5.5.3 | Espressif | Firmware framework included in the linked image | Apache License 2.0; framework license verified locally | Low | Keep as build prerequisite and include Apache-2.0 in binary distributions. |
| Groq ASR API | Optional external service | Optional speech-to-text when configured | Service API, no source vendored | Medium | Document that audio leaves the Mac when Groq is configured. Do not commit API keys. |
| Local Codex session files | User-local Codex data | Quota/status observation from `~/.codex/sessions/**/*.jsonl` | User-local data, not vendored | Medium | Keep local-only. Do not upload or commit session data. |
| Historical VoiceStick / StickS3VoiceKit / VoiceStickTrial directories outside this repository | Local historical reference directories in the parent workspace | Not part of VibeStick repository | Source/license uncertain from local copy | High | Do not copy into VibeStick. Do not publish as part of this repository. |
| Old provider logo-like assets removed during cleanup | Earlier local prototype assets | No longer used | Source unclear / brand risk | High | Replaced with simple project-generated temporary icons. |
| `firmware/sticks3/managed_components/`, `firmware/sticks3/build/`, Python `__pycache__/` | Generated local build/cache output | Not part of source | N/A | Low | Ignored by git. Do not commit. |
| `firmware/sticks3/include/vibe_stick_secrets.h`, `.env`, logs, recordings | Local user secrets/output | Runtime configuration and generated data | Private user data | High | Ignored by git. Never publish. |

## Summary

This repository is derived from Gary Zhang's MIT-licensed VibeStick project. The original copyright and MIT permission notice are retained in `LICENSE` and the relationship is documented in `NOTICE`. The landscape dashboard acknowledges CodeBuddy as a visual and information-architecture reference; its implementation is project-authored ESP-IDF/LVGL code, and no CodeBuddy source code or artwork is redistributed here. Vendored third-party materials are limited to the Bosch BMI270 driver and the generated Chinese LVGL glyph subset derived from Noto Sans SC; their license notices remain with the repository. Other build-time firmware dependencies are resolved through the ESP-IDF component manager.

The v0.1.5 public firmware package includes the project MIT license, Apache-2.0, LVGL MIT, Bosch BMI270, and Noto Sans SC OFL texts together with `NOTICE`. Re-run this check whenever the ESP-IDF or component lock versions change.
