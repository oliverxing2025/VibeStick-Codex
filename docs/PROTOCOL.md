# Protocol

VibeStick v0.1.2 uses HTTP over Wi-Fi between the StickS3 firmware and the local Mac bridge.

Default bridge URL:

```text
http://<mac-ip>:8765
```

## Firmware Headers

Firmware requests include:

```text
X-Vibe-Stick-Firmware-Name: vibestick
X-Vibe-Stick-Firmware-Version: 0.1.2
X-Vibe-Stick-Firmware-Transport: HTTP
X-Vibe-Stick-Firmware-Build-Date: <compile date>
```

Audio upload requests additionally include:

```text
X-Vibe-Stick-Sample-Rate: 16000
X-Vibe-Stick-Channels: 1
X-Vibe-Stick-Bits-Per-Sample: 16
```

When `VIBE_STICK_BRIDGE_TOKEN` is configured on the bridge and firmware, protected POST requests also include:

```text
X-Vibe-Stick-Token: <shared-token>
```

Protected endpoints are `/event`, `/quota/refresh`, `/recording/start`, `/recording/audio`, and `/recording/stop`. If the bridge binds outside loopback, such as `0.0.0.0`, `VIBE_STICK_BRIDGE_TOKEN` is required and placeholder tokens are rejected. If the bridge binds to loopback only, missing tokens are allowed for local development.

## GET /state

Returns the current bridge state:

```json
{
  "time": "13:01",
  "wifi": true,
  "ble": false,
  "battery": null,
  "active_provider": "codex",
  "provider": {
    "id": "codex",
    "display_name": "Codex",
    "implemented": true,
    "status": "RUNNING",
    "project": "vibestick",
    "quota_5h_remaining": 66,
    "quota_7d_remaining": 96,
    "quota_7d_reset_days": 7,
    "running_tasks": 2,
    "waiting_tasks": 1,
    "finished_tasks": 41,
    "today_used_percent": 16,
    "quota_updated_at": "13:01",
    "quota_stale": false,
    "funds_balance": "0",
    "today_spend": null,
    "today_tokens": 5800000
  },
  "codex": {
    "status": "RUNNING",
    "project": "vibestick",
    "quota_5h_remaining": 66,
    "quota_7d_remaining": 96,
    "quota_7d_reset_days": 7,
    "running_tasks": 2,
    "waiting_tasks": 1,
    "finished_tasks": 41,
    "today_used_percent": 16,
    "quota_updated_at": "13:01",
    "quota_stale": false,
    "funds_balance": "0",
    "today_spend": null,
    "today_tokens": 5800000
  },
  "alert": {
    "event_id": "",
    "type": "NONE",
    "message": ""
  },
  "bridge_name": "vibestick-bridge",
  "bridge_version": "0.1.2"
}
```

`battery` is intentionally `null` from the bridge. The StickS3 displays its local PMIC battery reading.

`active_provider` is always `codex`. `funds_balance` and `today_tokens` come from local Codex token-count events. `today_used_percent` is the increase in the seven-day `used_percent` since the local-day baseline, rather than the cumulative seven-day usage. `finished_tasks` is a bridge-persisted cumulative count of distinct completion events, so it survives StickS3 power cycles and firmware flashes. `today_spend` is `null` unless a truthful external value is configured. The legacy `codex` block remains present for backward compatibility.

## GET /health

Returns bridge health metadata:

```json
{
  "ok": true,
  "bridge_name": "vibestick-bridge",
  "bridge_version": "0.1.2"
}
```

## POST /event

Receives generic firmware or debug events.

Examples:

```json
{"event":"button_short","source":"sticks3"}
```

```json
{"event":"test_agent_status","source":"manual_test","status":"DONE","message":"test done"}
```

Manual `DONE`, `ERROR`, and `APPROVAL` statuses produce alert fields for local testing.

## POST /quota/refresh

Refreshes Codex usage from local session events. Missing display values remain `null` and the firmware shows `--`.

```json
{
  "refreshed": true,
  "state": {
    "time": "13:01",
    "wifi": true,
    "battery": null
  }
}
```

## POST /recording/start

Starts a recording session:

```json
{
  "event": "button_long_start",
  "source": "sticks3",
  "audio_source": "sticks3_pcm",
  "session_id": "<firmware-generated-id>"
}
```

## POST /recording/audio

Uploads raw little-endian signed PCM for the active session:

```text
POST /recording/audio?session_id=<id>
Content-Type: application/octet-stream
```

The bridge writes a local WAV file under:

```text
~/Library/Application Support/VibeStick/Recordings/
```

The bridge rejects audio uploads larger than `VIBE_STICK_MAX_RECORDING_AUDIO_BYTES`. The default is `2000000` bytes.

## POST /recording/stop

Stops the session and runs transcription:

```json
{"event":"button_long_stop","source":"sticks3","paste":true}
```

When transcription succeeds, the bridge pastes the transcript into the focused macOS app. Recording status does not trigger agent alert sounds.
