from __future__ import annotations

import argparse
import hmac
import ipaddress
import json
import os
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from vibe_stick import __version__ as BRIDGE_VERSION
from vibe_stick.audio.recorder import RecordingController
from vibe_stick.codex.quota import QuotaSnapshot, load_quota, save_quota
from vibe_stick.config.paths import QUOTA_PATH, RECORDING_PATH, STATE_PATH, ensure_app_support
from vibe_stick.desktop.hud import hide_hud
from vibe_stick.desktop.codex_control import CodexDesktopController
from vibe_stick.protocol.state import (
    AlertState,
    AlertType,
    VibeStickState,
    AgentStatus,
    CodexState,
    ProviderState,
    default_state,
    event_id,
    now_time_text,
    now_date_text,
    now_weekday_text,
    state_from_dict,
)
from vibe_stick.providers.base import ProviderObservation
from vibe_stick.providers.codex import observe_codex

MANUAL_STATUS_SECONDS = 60
BRIDGE_NAME = "vibestick-bridge"
DEFAULT_MAX_RECORDING_AUDIO_BYTES = 2_000_000
PLACEHOLDER_BRIDGE_TOKENS = {
    "change-this-shared-token",
    "paste-generated-token-here",
    "changeme",
    "change-me",
}


class BridgeStateStore:
    def __init__(self) -> None:
        ensure_app_support()
        self._lock = threading.RLock()
        self._project_root = _resolve_project_root()
        self._manual_status_until = 0.0
        self._state = self._load_state()
        self._state.active_provider = "codex"
        quota = load_quota(QUOTA_PATH)
        self._state.codex.quota_5h_remaining = quota.quota_5h_remaining
        self._state.codex.quota_7d_remaining = quota.quota_7d_remaining
        self._state.codex.quota_7d_reset_days = quota.quota_7d_reset_days
        self._state.codex.quota_updated_at = quota.quota_updated_at
        self._state.codex.quota_stale = quota.quota_stale
        self.recording = RecordingController(RECORDING_PATH)
        self.codex_controller = CodexDesktopController()
        hide_hud()

    def get_state(self) -> VibeStickState:
        with self._lock:
            self._refresh_providers_locked()
            self._state.time = now_time_text()
            self._state.date = now_date_text()
            self._state.weekday = now_weekday_text()
            self._save_state_locked()
            return self._state

    def update_from_event(self, event: dict[str, Any]) -> VibeStickState:
        with self._lock:
            event_name = str(event.get("event") or "")
            requested_status = event.get("codex_status") or event.get("status")
            if requested_status:
                self._set_codex_status(str(requested_status), str(event.get("message") or ""))
                self._manual_status_until = time.monotonic() + MANUAL_STATUS_SECONDS
            elif event_name in {"button_double", "front_double"}:
                self.refresh_quota_locked()
            elif event_name in {"button_short", "front_short"}:
                self._refresh_providers_locked()
                if self._state.codex.status == AgentStatus.APPROVAL:
                    result = self.codex_controller.approve()
                    self._set_codex_status(
                        AgentStatus.RUNNING.value if result.success else AgentStatus.ERROR.value,
                        result.message,
                    )
                    self._manual_status_until = time.monotonic() + 8
                else:
                    self.codex_controller.open_or_focus()
            elif event_name == "side_short":
                result = self.codex_controller.send()
                if not result.success:
                    self._set_codex_status(AgentStatus.ERROR.value, result.message)
                    self._manual_status_until = time.monotonic() + 8
            elif event_name == "side_double":
                result = self.codex_controller.clear_input()
                if not result.success:
                    self._set_codex_status(AgentStatus.ERROR.value, result.message)
                    self._manual_status_until = time.monotonic() + 8
            elif event_name == "side_long":
                self.codex_controller.new_thread()
            self._save_state_locked()
            return self._state

    def refresh_quota(self) -> VibeStickState:
        with self._lock:
            self.refresh_quota_locked()
            self._save_state_locked()
            return self._state

    def refresh_quota_locked(self) -> None:
        codex_observation = observe_codex(self._project_root)
        self._apply_codex_quota(codex_observation, force_stale=True)
        self._state.codex = _codex_state_from_observation(codex_observation)
        self._state.active_provider = "codex"
        self._state.provider = _provider_state_from_observation(codex_observation)

    def start_recording(self, request: dict[str, Any] | None = None) -> dict[str, Any]:
        session = self.recording.start(request)
        with self._lock:
            self._state.alert = AlertState(
                event_id="",
                type=AlertType.NONE,
                message="",
            )
            self._save_state_locked()
        return {"recording": session.to_jsonable(), "state": self.get_state().to_jsonable()}

    def stop_recording(self, request: dict[str, Any] | None = None) -> dict[str, Any]:
        session = self.recording.stop(request)
        return {"recording": session.to_jsonable(), "state": self.get_state().to_jsonable()}

    def upload_recording_audio(
        self,
        pcm: bytes,
        *,
        session_id: str = "",
        sample_rate: int = 16000,
        channels: int = 1,
        bits_per_sample: int = 16,
    ) -> dict[str, Any]:
        session = self.recording.attach_pcm(
            pcm,
            session_id=session_id,
            sample_rate=sample_rate,
            channels=channels,
            bits_per_sample=bits_per_sample,
        )
        return {"recording": session.to_jsonable(), "state": self.get_state().to_jsonable()}

    def _refresh_providers_locked(self) -> None:
        codex_observation = observe_codex(self._project_root)
        self._apply_codex_quota(codex_observation)

        if time.monotonic() < self._manual_status_until:
            _apply_manual_codex_state(codex_observation, self._state)

        self._state.active_provider = "codex"
        self._state.codex = _codex_state_from_observation(codex_observation)
        self._state.provider = _provider_state_from_observation(codex_observation)
        self._apply_alert_from_observation(codex_observation)

    def _apply_alert_from_observation(self, observation: ProviderObservation) -> None:
        try:
            alert_type = AlertType(observation.alert_type)
        except ValueError:
            alert_type = AlertType.NONE
        if alert_type in {AlertType.DONE, AlertType.APPROVAL, AlertType.ERROR} and observation.alert_event_id:
            self._state.alert = AlertState(
                event_id=observation.alert_event_id,
                type=alert_type,
                message=observation.alert_message,
            )
        else:
            self._state.alert = AlertState(event_id="", type=AlertType.NONE, message="")

    def _apply_codex_quota(self, observation: ProviderObservation, *, force_stale: bool = False) -> None:
        if observation.quota_5h_remaining is not None or observation.quota_7d_remaining is not None:
            refreshed = QuotaSnapshot(
                quota_5h_remaining=observation.quota_5h_remaining,
                quota_7d_remaining=observation.quota_7d_remaining,
                quota_7d_reset_days=observation.quota_7d_reset_days,
                quota_updated_at=observation.quota_updated_at,
                quota_stale=observation.quota_stale,
            )
            save_quota(QUOTA_PATH, refreshed)
        else:
            existing = QuotaSnapshot(
                quota_5h_remaining=self._state.codex.quota_5h_remaining,
                quota_7d_remaining=self._state.codex.quota_7d_remaining,
                quota_7d_reset_days=self._state.codex.quota_7d_reset_days,
                quota_updated_at=self._state.codex.quota_updated_at,
                quota_stale=self._state.codex.quota_stale,
            )
            if existing.quota_5h_remaining is None and existing.quota_7d_remaining is None:
                refreshed = existing
            else:
                refreshed = _stale_quota(existing)
            if force_stale:
                save_quota(QUOTA_PATH, refreshed)

        observation.quota_5h_remaining = refreshed.quota_5h_remaining
        observation.quota_7d_remaining = refreshed.quota_7d_remaining
        observation.quota_7d_reset_days = refreshed.quota_7d_reset_days
        observation.quota_updated_at = refreshed.quota_updated_at
        observation.quota_stale = refreshed.quota_stale

    def _set_codex_status(self, raw_status: str, message: str) -> None:
        try:
            status = AgentStatus(raw_status.upper())
        except ValueError:
            status = AgentStatus.UNKNOWN
        self._state.codex.status = status
        self._state.active_provider = "codex"
        self._state.provider.status = status
        if status == AgentStatus.DONE:
            self._state.alert = AlertState(event_id("done"), AlertType.DONE, message or "Codex task completed")
        elif status == AgentStatus.APPROVAL:
            self._state.alert = AlertState(
                event_id("approval"),
                AlertType.APPROVAL,
                message or "Codex is waiting for approval",
            )
        elif status == AgentStatus.ERROR:
            self._state.alert = AlertState(event_id("error"), AlertType.ERROR, message or "Codex needs attention")
        else:
            self._state.alert = AlertState(event_id="", type=AlertType.NONE, message="")

    def _load_state(self) -> VibeStickState:
        try:
            return state_from_dict(json.loads(STATE_PATH.read_text()))
        except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
            return default_state()

    def _save_state_locked(self) -> None:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(self._state.to_jsonable(), indent=2) + "\n")


def make_handler(store: BridgeStateStore) -> type[BaseHTTPRequestHandler]:
    class VibeStickHandler(BaseHTTPRequestHandler):
        server_version = "VibeStick/0.1"

        def do_GET(self) -> None:
            if self.path == "/state":
                self._send_json(_with_bridge_metadata(store.get_state().to_jsonable()))
            elif self.path == "/health":
                self._send_json(
                    {
                        "ok": True,
                        "bridge_name": BRIDGE_NAME,
                        "bridge_version": BRIDGE_VERSION,
                    }
                )
            else:
                self._send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path in _protected_paths() and not self._is_authorized():
                self._send_error(HTTPStatus.UNAUTHORIZED, "Unauthorized")
                return

            if parsed.path == "/event":
                body = self._read_json_body()
                self._send_json(store.update_from_event(body).to_jsonable())
            elif parsed.path == "/quota/refresh":
                state = store.refresh_quota()
                self._send_json({"refreshed": True, "state": state.to_jsonable()})
            elif parsed.path == "/recording/start":
                body = self._read_json_body()
                self._send_json(store.start_recording(body))
            elif parsed.path == "/recording/audio":
                query = parse_qs(parsed.query)
                content_length = self._content_length()
                max_audio_bytes = _max_recording_audio_bytes()
                if content_length > max_audio_bytes:
                    self._send_error(
                        HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                        f"Recording audio exceeds {max_audio_bytes} bytes",
                    )
                    return
                pcm = self._read_raw_body(content_length)
                self._send_json(
                    store.upload_recording_audio(
                        pcm,
                        session_id=_first(query, "session_id"),
                        sample_rate=_int_header(self.headers.get("X-Vibe-Stick-Sample-Rate"), 16000),
                        channels=_int_header(self.headers.get("X-Vibe-Stick-Channels"), 1),
                        bits_per_sample=_int_header(self.headers.get("X-Vibe-Stick-Bits-Per-Sample"), 16),
                    )
                )
            elif parsed.path == "/recording/stop":
                body = self._read_json_body()
                self._send_json(store.stop_recording(body))
            else:
                self._send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")

        def log_message(self, fmt: str, *args: object) -> None:
            firmware_name = self.headers.get("X-Vibe-Stick-Firmware-Name", "-")
            firmware_version = self.headers.get("X-Vibe-Stick-Firmware-Version", "-")
            firmware_transport = self.headers.get("X-Vibe-Stick-Firmware-Transport", "-")
            print(
                f"{self.address_string()} - {fmt % args} "
                f"firmware={firmware_name}/{firmware_version} transport={firmware_transport}",
                flush=True,
            )

        def _read_json_body(self) -> dict[str, Any]:
            length = self._content_length()
            if length == 0:
                return {}
            raw = self.rfile.read(length)
            try:
                data = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                return {}
            return data if isinstance(data, dict) else {}

        def _read_raw_body(self, length: int) -> bytes:
            if length <= 0:
                return b""
            return self.rfile.read(length)

        def _content_length(self) -> int:
            try:
                length = int(self.headers.get("Content-Length", "0") or "0")
            except ValueError:
                return 0
            return max(0, length)

        def _is_authorized(self) -> bool:
            expected = _bridge_token()
            if not expected:
                return True
            supplied = self.headers.get("X-Vibe-Stick-Token", "")
            return hmac.compare_digest(supplied, expected)

        def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1")
            self.end_headers()
            self.wfile.write(data)

        def _send_error(self, status: HTTPStatus, message: str) -> None:
            self._send_json({"error": message}, status=status)

    return VibeStickHandler


def run_server(host: str, port: int) -> None:
    _enforce_bind_security(host)
    store = BridgeStateStore()
    server = ThreadingHTTPServer((host, port), make_handler(store))
    if not _bridge_token():
        print(
            "WARNING: VIBE_STICK_BRIDGE_TOKEN is not set; POST endpoints are unauthenticated on loopback only.",
            flush=True,
        )
    print(f"VibeStick Bridge listening on http://{host}:{port}", flush=True)
    server.serve_forever()


def _protected_paths() -> set[str]:
    return {
        "/event",
        "/quota/refresh",
        "/recording/start",
        "/recording/audio",
        "/recording/stop",
    }


def _bridge_token() -> str:
    token = os.environ.get("VIBE_STICK_BRIDGE_TOKEN", "").strip()
    if token.lower() in PLACEHOLDER_BRIDGE_TOKENS:
        return ""
    return token


def _enforce_bind_security(host: str) -> None:
    if _host_requires_token(host) and not _bridge_token():
        raise SystemExit(
            "Refusing to bind VibeStick Bridge outside loopback without "
            "VIBE_STICK_BRIDGE_TOKEN. Set a strong shared token or use --host 127.0.0.1."
        )


def _host_requires_token(host: str) -> bool:
    normalized = host.strip().strip("[]").lower()
    if normalized == "localhost":
        return False
    if not normalized:
        return True
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return True
    return not address.is_loopback


def _max_recording_audio_bytes() -> int:
    raw = os.environ.get("VIBE_STICK_MAX_RECORDING_AUDIO_BYTES", "").strip()
    if not raw:
        return DEFAULT_MAX_RECORDING_AUDIO_BYTES
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_RECORDING_AUDIO_BYTES
    return max(256_000, min(8_000_000, value))


def _resolve_project_root() -> Path:
    configured = os.environ.get("VIBE_STICK_PROJECT_ROOT", "").strip()
    root = Path(configured).expanduser() if configured else Path.cwd()
    if root.name in {"bridge", "firmware", "app", "scripts"} and (root.parent / "README.md").exists():
        root = root.parent
    return root.resolve()


def _stale_quota(existing: QuotaSnapshot) -> QuotaSnapshot:
    return QuotaSnapshot(
        quota_5h_remaining=existing.quota_5h_remaining,
        quota_7d_remaining=existing.quota_7d_remaining,
        quota_7d_reset_days=existing.quota_7d_reset_days,
        quota_updated_at=existing.quota_updated_at,
        quota_stale=True,
    )


def _first(query: dict[str, list[str]], key: str) -> str:
    values = query.get(key) or []
    return values[0] if values else ""


def _with_bridge_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    payload["bridge_name"] = BRIDGE_NAME
    payload["bridge_version"] = BRIDGE_VERSION
    return payload


def _codex_state_from_observation(observation: ProviderObservation) -> CodexState:
    return CodexState(
        status=observation.status,
        project=observation.project,
        quota_5h_remaining=observation.quota_5h_remaining,
        quota_7d_remaining=observation.quota_7d_remaining,
        quota_7d_reset_days=observation.quota_7d_reset_days,
        quota_updated_at=observation.quota_updated_at,
        quota_stale=observation.quota_stale,
        funds_balance=observation.funds_balance,
        today_spend=observation.today_spend,
        today_tokens=observation.today_tokens,
    )


def _provider_state_from_observation(observation: ProviderObservation) -> ProviderState:
    return ProviderState(
        id=observation.provider_id,
        display_name=observation.display_name,
        implemented=True,
        status=observation.status,
        project=observation.project,
        quota_5h_remaining=observation.quota_5h_remaining,
        quota_7d_remaining=observation.quota_7d_remaining,
        quota_7d_reset_days=observation.quota_7d_reset_days,
        quota_updated_at=observation.quota_updated_at,
        quota_stale=observation.quota_stale,
        funds_balance=observation.funds_balance,
        today_spend=observation.today_spend,
        today_tokens=observation.today_tokens,
    )


def _apply_manual_codex_state(observation: ProviderObservation, state: VibeStickState) -> None:
    observation.status = state.codex.status
    observation.alert_type = state.alert.type.value
    observation.alert_message = state.alert.message
    observation.alert_event_id = state.alert.event_id


def _int_header(raw: str | None, default: int) -> int:
    try:
        value = int(raw or "")
    except ValueError:
        return default
    return value if value > 0 else default


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run VibeStick Bridge.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    run_server(args.host, args.port)
