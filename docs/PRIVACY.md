# Privacy and data flow

VibeStick-Codex is a local-first hobby project. It does not include analytics
or telemetry, but it handles local Codex metadata, microphone audio, and
credentials that should be treated as private.

## Data read locally

The bridge reads recent local Codex session files to derive summarized device
state: project folder name, task state, approval state, quota percentages,
reset timing, and token totals. It does not intentionally send prompts,
responses, or complete Codex session files to the StickS3.

The bridge also uses macOS Accessibility permission for focus, paste, send,
clear, new-chat, and approval actions. It does not upload Accessibility data.

## Data stored locally

Runtime files are stored under:

```text
~/Library/Application Support/VibeStick/
```

The directory is restricted to the current user (`0700`) and sensitive files
are written as `0600`. The latest complete transcript is not persisted.
Recording files are deleted after processing by default. Set
`VIBE_STICK_RETAIN_RECORDINGS=1` only when recordings are intentionally needed
for debugging.

`scripts/uninstall.sh` removes the LaunchAgents but deliberately leaves the
configuration directory in place. Delete that directory manually when the
credentials and cached state are no longer needed.

## Local network

The StickS3 and Mac communicate over HTTP on the local network. The bridge
requires `VIBE_STICK_BRIDGE_TOKEN` whenever it binds outside loopback, and the
token protects both state reads and mutating endpoints.

HTTP does not provide transport encryption. The shared token, summarized
status, and StickS3 microphone audio can cross the LAN in plaintext. Use the
device only on a trusted private Wi-Fi network; do not expose port `8765` to
the internet or use it on public/untrusted Wi-Fi.

## Speech transcription

When an OpenAI-compatible cloud ASR provider is configured, the recorded audio
is uploaded to that provider over the configured `base_url`. The provider's
privacy and retention terms apply. The default examples use HTTPS. Do not
configure an untrusted or plaintext HTTP ASR endpoint.

For offline transcription, configure `VIBE_STICK_TRANSCRIBE_CMD`. A custom
recording hook or transcription command is user-supplied code and receives
local recording-session metadata, including the local audio path.

## Credentials

Wi-Fi credentials and the bridge token are compiled into the local firmware
image. ASR credentials and the bridge token are stored in the local `.env`.
These files are ignored by Git, but anyone with access to the Mac account,
firmware image, or device flash may be able to recover them. Use scoped API
keys and rotate credentials after losing a device or sharing a firmware image.

Never commit `.env`, `vibe_stick_secrets.h`, recordings, logs, or local Codex
session files.
