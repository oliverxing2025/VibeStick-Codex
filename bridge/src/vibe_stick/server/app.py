from __future__ import annotations

import argparse
import atexit
import hashlib
import hmac
import html
import ipaddress
import json
import os
import re
import socket
import threading
import time
import uuid
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from vibe_stick import __version__ as BRIDGE_VERSION
from vibe_stick.audio.recorder import RecordingController
from vibe_stick.codex.local_observer import waiting_thread_ids
from vibe_stick.codex.quota import QuotaSnapshot, load_quota, save_quota
from vibe_stick.config.paths import (
    APP_SUPPORT_DIR,
    QUOTA_PATH,
    RECORDING_PATH,
    STATE_PATH,
    TASK_STATS_PATH,
    DESKTOP_BRIDGE_PATH,
    HOST_SERVICE_DISCOVERY_PATH,
    ensure_app_support,
    restrict_private_file,
    write_private_text,
)
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
DISCOVERY_MAGIC = "VIBESTICK_DISCOVER_V1"
DISCOVERY_PROOF_PREFIX = "VIBESTICK_DISCOVERY_V1"
DEFAULT_DISCOVERY_PORT = 8766
DEFAULT_MAX_RECORDING_AUDIO_BYTES = 2_000_000
PLACEHOLDER_BRIDGE_TOKENS = {
    "change-this-shared-token",
    "paste-generated-token-here",
    "changeme",
    "change-me",
}
VOICE_SETTINGS_KEYS = (
    "VIBE_STICK_ASR_PROVIDER",
    "VIBE_STICK_ASR_BASE_URL",
    "VIBE_STICK_ASR_API_KEY",
    "VIBE_STICK_ASR_MODEL",
    "VIBE_STICK_ASR_LANGUAGE",
)
VOICE_VALUE_PATTERN = re.compile(r"^[A-Za-z0-9._:/-]+$")
VOICE_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._-]{8,512}$")


def _local_date_key() -> str:
    return datetime.now().astimezone().date().isoformat()


def _discovery_response(request: bytes, bridge_port: int) -> bytes | None:
    token = _bridge_token()
    if not token:
        return None
    try:
        magic, nonce = request.decode("ascii").strip().split(" ", 1)
    except (UnicodeDecodeError, ValueError):
        return None
    if magic != DISCOVERY_MAGIC or not (8 <= len(nonce) <= 32):
        return None
    if any(character not in "0123456789abcdefABCDEF" for character in nonce):
        return None
    proof_payload = f"{DISCOVERY_PROOF_PREFIX}:{nonce}:{bridge_port}".encode("ascii")
    proof = hmac.new(token.encode("utf-8"), proof_payload, hashlib.sha256).hexdigest()
    return json.dumps(
        {
            "bridge_name": BRIDGE_NAME,
            "port": bridge_port,
            "nonce": nonce,
            "proof": proof,
        },
        separators=(",", ":"),
    ).encode("utf-8")


def _serve_lan_discovery(bridge_port: int, discovery_port: int) -> None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(("0.0.0.0", discovery_port))
            while True:
                request, client = server.recvfrom(256)
                response = _discovery_response(request, bridge_port)
                if response is not None:
                    server.sendto(response, client)
    except OSError as error:
        print(f"VibeStick discovery unavailable on UDP {discovery_port}: {error}", flush=True)


class BridgeStateStore:
    def __init__(self) -> None:
        ensure_app_support()
        self._lock = threading.RLock()
        self.settings_csrf_token = uuid.uuid4().hex
        self._project_root = _resolve_project_root()
        self._manual_status_until = 0.0
        self._state = self._load_state()
        (
            saved_finished_tasks,
            self._last_finished_event_id,
            saved_task_stats_day,
        ) = self._load_task_stats()
        self._task_stats_day = _local_date_key()
        self._finished_tasks = (
            saved_finished_tasks
            if saved_task_stats_day == self._task_stats_day
            else 0
        )
        self._state.codex.finished_tasks = self._finished_tasks
        self._state.provider.finished_tasks = self._finished_tasks
        if saved_task_stats_day != self._task_stats_day:
            self._save_task_stats()
        self._state.active_provider = "codex"
        quota = load_quota(QUOTA_PATH)
        self._state.codex.quota_5h_remaining = quota.quota_5h_remaining
        self._state.codex.quota_5h_reset_minutes = quota.quota_5h_reset_minutes
        self._state.codex.quota_7d_remaining = quota.quota_7d_remaining
        self._state.codex.quota_7d_reset_days = quota.quota_7d_reset_days
        self._state.codex.quota_7d_reset_minutes = quota.quota_7d_reset_minutes
        self._state.codex.quota_updated_at = quota.quota_updated_at
        self._state.codex.quota_stale = quota.quota_stale
        self.recording = RecordingController(RECORDING_PATH)
        self.codex_controller = CodexDesktopController()
        hide_hud()

    def get_state(self) -> VibeStickState:
        with self._lock:
            self._ensure_current_task_day()
            self._refresh_providers_locked()
            self._state.time = now_time_text()
            self._state.date = now_date_text()
            self._state.weekday = now_weekday_text()
            self._save_state_locked()
            return self._state

    def update_from_event(self, event: dict[str, Any]) -> VibeStickState:
        with self._lock:
            self._ensure_current_task_day()
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
                approval_thread_ids = waiting_thread_ids()
                if approval_thread_ids:
                    result = self.codex_controller.approve_all(approval_thread_ids)
                    self._set_codex_status(
                        AgentStatus.RUNNING.value if result.success else AgentStatus.ERROR.value,
                        result.message,
                    )
                    self._manual_status_until = time.monotonic() + 8
                else:
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
        self._apply_finished_task_counter(codex_observation)
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
        return {
            "recording": _recording_transport_payload(session),
            "state": self.get_state().to_jsonable(),
        }

    def stop_recording(self, request: dict[str, Any] | None = None) -> dict[str, Any]:
        session = self.recording.stop(request)
        return {
            "recording": _recording_transport_payload(session),
            "state": self.get_state().to_jsonable(),
        }

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
        return {
            "recording": _recording_transport_payload(session),
            "state": self.get_state().to_jsonable(),
        }

    def _refresh_providers_locked(self) -> None:
        codex_observation = observe_codex(self._project_root)
        self._apply_codex_quota(codex_observation)

        if time.monotonic() < self._manual_status_until:
            _apply_manual_codex_state(codex_observation, self._state)

        self._apply_finished_task_counter(codex_observation)
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
                quota_5h_reset_minutes=observation.quota_5h_reset_minutes,
                quota_7d_remaining=observation.quota_7d_remaining,
                quota_7d_reset_days=observation.quota_7d_reset_days,
                quota_7d_reset_minutes=observation.quota_7d_reset_minutes,
                quota_updated_at=observation.quota_updated_at,
                quota_stale=observation.quota_stale,
            )
            save_quota(QUOTA_PATH, refreshed)
        else:
            existing = QuotaSnapshot(
                quota_5h_remaining=self._state.codex.quota_5h_remaining,
                quota_5h_reset_minutes=self._state.codex.quota_5h_reset_minutes,
                quota_7d_remaining=self._state.codex.quota_7d_remaining,
                quota_7d_reset_days=self._state.codex.quota_7d_reset_days,
                quota_7d_reset_minutes=self._state.codex.quota_7d_reset_minutes,
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
        observation.quota_5h_reset_minutes = refreshed.quota_5h_reset_minutes
        observation.quota_7d_remaining = refreshed.quota_7d_remaining
        observation.quota_7d_reset_days = refreshed.quota_7d_reset_days
        observation.quota_7d_reset_minutes = refreshed.quota_7d_reset_minutes
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
            self._record_finished_event(self._state.alert.event_id)
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

    def _apply_finished_task_counter(self, observation: ProviderObservation) -> None:
        if not hasattr(self, "_finished_tasks"):
            self._finished_tasks = self._state.codex.finished_tasks
            self._last_finished_event_id = ""
            self._task_stats_day = _local_date_key()
        self._ensure_current_task_day()
        if observation.alert_type in {"DONE", "COMPLETED", "SUCCESS"}:
            self._record_finished_event(observation.alert_event_id)
        observation.finished_tasks = self._finished_tasks

    def _record_finished_event(self, finished_event_id: str) -> None:
        if not hasattr(self, "_finished_tasks"):
            self._finished_tasks = self._state.codex.finished_tasks
            self._last_finished_event_id = ""
            self._task_stats_day = _local_date_key()
        self._ensure_current_task_day()
        if not finished_event_id or finished_event_id == self._last_finished_event_id:
            return
        self._finished_tasks += 1
        self._last_finished_event_id = finished_event_id
        self._state.codex.finished_tasks = self._finished_tasks
        self._state.provider.finished_tasks = self._finished_tasks
        self._save_task_stats()

    def _ensure_current_task_day(self) -> None:
        today = _local_date_key()
        if getattr(self, "_task_stats_day", today) == today:
            return
        self._task_stats_day = today
        self._finished_tasks = 0
        self._state.codex.finished_tasks = 0
        self._state.provider.finished_tasks = 0
        self._save_task_stats()

    def _load_task_stats(self) -> tuple[int, str, str]:
        try:
            data = json.loads(TASK_STATS_PATH.read_text())
            finished_tasks = max(0, int(data.get("finished_tasks", 0)))
            last_event_id = str(data.get("last_finished_event_id") or "")
            local_date = str(data.get("local_date") or "")
            return finished_tasks, last_event_id, local_date
        except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError, ValueError):
            return 0, "", ""

    def _save_task_stats(self) -> None:
        payload = {
            "local_date": self._task_stats_day,
            "finished_tasks": self._finished_tasks,
            "last_finished_event_id": self._last_finished_event_id,
        }
        write_private_text(TASK_STATS_PATH, json.dumps(payload, indent=2) + "\n")

    def _load_state(self) -> VibeStickState:
        try:
            return state_from_dict(json.loads(STATE_PATH.read_text()))
        except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
            return default_state()

    def _save_state_locked(self) -> None:
        write_private_text(
            STATE_PATH,
            json.dumps(self._state.to_jsonable(), indent=2) + "\n",
        )


def make_handler(store: BridgeStateStore) -> type[BaseHTTPRequestHandler]:
    class VibeStickHandler(BaseHTTPRequestHandler):
        server_version = "VibeStick/0.1"

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/setup/voice":
                if not self._is_loopback_client():
                    self._send_error(HTTPStatus.FORBIDDEN,
                                     "Voice settings are available only on this computer")
                    return
                saved = _first(parse_qs(parsed.query), "saved") == "1"
                self._send_html(_voice_settings_html(
                    store.settings_csrf_token,
                    message="设置已保存并立即生效。" if saved else "",
                ))
                return
            if parsed.path in _protected_paths() and not self._is_authorized():
                self._send_error(HTTPStatus.UNAUTHORIZED, "Unauthorized")
                return

            if parsed.path == "/state":
                self._send_json(_with_bridge_metadata(store.get_state().to_jsonable()))
            elif parsed.path == "/health":
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
            if parsed.path == "/setup/voice":
                if not self._is_loopback_client():
                    self._send_error(HTTPStatus.FORBIDDEN,
                                     "Voice settings are available only on this computer")
                    return
                if self._content_length() > 8192:
                    self._send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                                     "Voice settings request is too large")
                    return
                body = self._read_raw_body(self._content_length()).decode(
                    "utf-8", errors="strict"
                )
                form = parse_qs(body, keep_blank_values=True)
                if not hmac.compare_digest(
                    _first(form, "csrf"), store.settings_csrf_token
                ):
                    self._send_error(HTTPStatus.FORBIDDEN, "Invalid setup request")
                    return
                try:
                    _save_voice_settings(form)
                except ValueError as error:
                    self._send_html(
                        _voice_settings_html(store.settings_csrf_token,
                                             message=str(error), error=True),
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return
                self.send_response(HTTPStatus.SEE_OTHER)
                self.send_header("Location", "/setup/voice?saved=1")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
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

        def _is_loopback_client(self) -> bool:
            try:
                return ipaddress.ip_address(self.client_address[0]).is_loopback
            except ValueError:
                return False

        def _send_html(self, page: str,
                       status: HTTPStatus = HTTPStatus.OK) -> None:
            data = page.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy",
                             "default-src 'none'; style-src 'unsafe-inline'; "
                             "form-action 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(data)

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


def _write_desktop_discovery(port: int, instance_id: str) -> None:
    payload = {
        "schema_version": 1,
        "bridge_name": BRIDGE_NAME,
        "bridge_version": BRIDGE_VERSION,
        "instance_id": instance_id,
        "pid": os.getpid(),
        "state_url": f"http://127.0.0.1:{port}/state",
        "health_url": f"http://127.0.0.1:{port}/health",
        "created_at": datetime.now().astimezone().isoformat(),
    }
    temporary = DESKTOP_BRIDGE_PATH.with_suffix(f".{instance_id}.tmp")
    write_private_text(temporary, json.dumps(payload, indent=2) + "\n")
    os.replace(temporary, DESKTOP_BRIDGE_PATH)
    restrict_private_file(DESKTOP_BRIDGE_PATH)
    service_payload = {
        "schema_version": 1,
        "service_identity": BRIDGE_NAME,
        "protocol_version": BRIDGE_VERSION,
        "instance_id": instance_id,
        "pid": os.getpid(),
        "base_url": f"http://127.0.0.1:{port}",
        "health_url": f"http://127.0.0.1:{port}/health",
        "legacy_ports": [8765],
        "created_at": datetime.now().astimezone().isoformat(),
    }
    write_private_text(
        HOST_SERVICE_DISCOVERY_PATH,
        json.dumps(service_payload, indent=2) + "\n",
    )


def _remove_desktop_discovery(instance_id: str) -> None:
    try:
        payload = json.loads(DESKTOP_BRIDGE_PATH.read_text(encoding="utf-8"))
        if payload.get("instance_id") == instance_id:
            DESKTOP_BRIDGE_PATH.unlink(missing_ok=True)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    try:
        payload = json.loads(HOST_SERVICE_DISCOVERY_PATH.read_text(encoding="utf-8"))
        if payload.get("instance_id") == instance_id:
            HOST_SERVICE_DISCOVERY_PATH.unlink(missing_ok=True)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass


def run_server(host: str, port: int) -> None:
    _enforce_bind_security(host)
    store = BridgeStateStore()
    handler = make_handler(store)
    # Desktop clients never depend on the LAN/device port. The OS chooses a
    # private loopback port, and a mode-0600 discovery record advertises it.
    desktop_server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    desktop_port = int(desktop_server.server_address[1])
    instance_id = uuid.uuid4().hex
    _write_desktop_discovery(desktop_port, instance_id)
    atexit.register(_remove_desktop_discovery, instance_id)
    desktop_thread = threading.Thread(
        target=desktop_server.serve_forever,
        name="vibestick-desktop-bridge",
        daemon=True,
    )
    desktop_thread.start()
    try:
        server = ThreadingHTTPServer((host, port), handler)
    except BaseException:
        desktop_server.shutdown()
        desktop_server.server_close()
        _remove_desktop_discovery(instance_id)
        raise
    discovery_port = int(os.environ.get("VIBE_STICK_DISCOVERY_PORT", DEFAULT_DISCOVERY_PORT))
    if _host_requires_token(host):
        threading.Thread(
            target=_serve_lan_discovery,
            args=(port, discovery_port),
            name="vibestick-lan-discovery",
            daemon=True,
        ).start()
    if not _bridge_token():
        print(
            "WARNING: VIBE_STICK_BRIDGE_TOKEN is not set; POST endpoints are unauthenticated on loopback only.",
            flush=True,
        )
    print(f"VibeStick Bridge listening on http://{host}:{port}", flush=True)
    if _host_requires_token(host):
        print(f"VibeStick discovery listening on udp://0.0.0.0:{discovery_port}", flush=True)
    print(f"VibeStick desktop endpoint: http://127.0.0.1:{desktop_port}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        desktop_server.shutdown()
        desktop_server.server_close()
        _remove_desktop_discovery(instance_id)


def _protected_paths() -> set[str]:
    return {
        "/state",
        "/event",
        "/quota/refresh",
        "/recording/start",
        "/recording/audio",
        "/recording/stop",
    }


def _recording_transport_payload(session: Any) -> dict[str, Any]:
    payload = session.to_jsonable()
    payload["transcript"] = ""
    payload["audio_file"] = ""
    return payload


def _bridge_token() -> str:
    token = os.environ.get("VIBE_STICK_BRIDGE_TOKEN", "").strip()
    if token.lower() in PLACEHOLDER_BRIDGE_TOKENS:
        return ""
    return token


def _voice_settings_path() -> Path:
    configured = os.environ.get("VIBE_STICK_CONFIG_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    installed = APP_SUPPORT_DIR / ".env"
    if installed.exists() or Path.cwd() == APP_SUPPORT_DIR:
        return installed
    return Path.cwd() / ".env"


def _read_env_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return values
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _write_env_values(path: Path, updates: dict[str, str]) -> None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        lines = []
    replaced: set[str] = set()
    output: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key in updates and not line.lstrip().startswith("#"):
            output.append(f"{key}={updates[key]}")
            replaced.add(key)
        else:
            output.append(line)
    for key in VOICE_SETTINGS_KEYS:
        if key not in replaced:
            output.append(f"{key}={updates[key]}")
    temporary = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
    write_private_text(temporary, "\n".join(output).rstrip() + "\n")
    os.replace(temporary, path)
    restrict_private_file(path)


def _save_voice_settings(form: dict[str, list[str]]) -> None:
    profile = _first(form, "profile").strip()
    base_url = _first(form, "base_url").strip().rstrip("/")
    model = _first(form, "model").strip()
    language = _first(form, "language").strip() or "zh"
    api_key = _first(form, "api_key").strip()
    if profile == "siliconflow":
        provider = "openai-compatible"
        base_url = base_url or "https://api.siliconflow.cn/v1"
        model = model or "FunAudioLLM/SenseVoiceSmall"
    elif profile == "groq":
        provider = "groq"
        base_url = base_url or "https://api.groq.com/openai/v1"
        model = model or "whisper-large-v3-turbo"
    elif profile == "custom":
        provider = "openai-compatible"
    else:
        raise ValueError("请选择语音服务商。")
    if not base_url.startswith("https://") or not VOICE_VALUE_PATTERN.fullmatch(base_url):
        raise ValueError("API 地址必须是有效的 HTTPS 地址。")
    if not model or not VOICE_VALUE_PATTERN.fullmatch(model):
        raise ValueError("请填写有效的语音识别模型名称。")
    if not VOICE_VALUE_PATTERN.fullmatch(language):
        raise ValueError("语言代码无效。")
    path = _voice_settings_path()
    existing = _read_env_values(path)
    if not api_key:
        api_key = existing.get("VIBE_STICK_ASR_API_KEY", "")
    if not VOICE_KEY_PATTERN.fullmatch(api_key):
        raise ValueError("请填写有效的 API Key（至少 8 个字符）。")
    updates = {
        "VIBE_STICK_ASR_PROVIDER": provider,
        "VIBE_STICK_ASR_BASE_URL": base_url,
        "VIBE_STICK_ASR_API_KEY": api_key,
        "VIBE_STICK_ASR_MODEL": model,
        "VIBE_STICK_ASR_LANGUAGE": language,
    }
    _write_env_values(path, updates)
    os.environ.update(updates)


def _voice_settings_html(csrf_token: str, *, message: str = "",
                         error: bool = False) -> str:
    values = _read_env_values(_voice_settings_path())
    base_url = values.get("VIBE_STICK_ASR_BASE_URL", "https://api.siliconflow.cn/v1")
    model = values.get("VIBE_STICK_ASR_MODEL", "FunAudioLLM/SenseVoiceSmall")
    language = values.get("VIBE_STICK_ASR_LANGUAGE", "zh") or "zh"
    provider = values.get("VIBE_STICK_ASR_PROVIDER", "openai-compatible")
    if provider == "groq":
        profile = "groq"
    elif "siliconflow.cn" in base_url:
        profile = "siliconflow"
    else:
        profile = "custom"
    key_configured = bool(values.get("VIBE_STICK_ASR_API_KEY", "").strip())
    pairing_token = _bridge_token()
    options = "".join(
        f"<option value='{name}'{' selected' if profile == name else ''}>{label}</option>"
        for name, label in (
            ("siliconflow", "SiliconFlow（国内推荐）"),
            ("groq", "Groq"),
            ("custom", "其他 OpenAI 兼容服务"),
        )
    )
    notice = ""
    if message:
        notice = f"<div class='notice {'error' if error else 'ok'}'>{html.escape(message)}</div>"
    key_hint = "已配置；留空可保留原 Key" if key_configured else "将仅保存在这台电脑"
    return f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'><title>VibeStick 语音服务设置</title>
<style>body{{font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#0b0d10;color:#f4f5f7;margin:0;padding:28px}}.card{{max-width:620px;margin:auto;background:#171a20;border:1px solid #2d333d;border-radius:20px;padding:26px}}h1{{font-size:25px;margin:0 0 8px}}p{{color:#aab0bb;line-height:1.55}}label{{display:block;margin-top:18px;font-weight:600}}input,select,button{{box-sizing:border-box;width:100%;margin-top:7px;padding:12px;border-radius:10px;border:1px solid #444b56;background:#0f1217;color:#fff;font:inherit}}button{{background:#f5c84c;color:#111;border:0;font-weight:750;cursor:pointer}}small{{display:block;color:#8e95a1;margin-top:6px}}.notice{{padding:11px;border-radius:10px;margin:16px 0}}.ok{{background:#143a2a;color:#9ee6bd}}.error{{background:#4a2020;color:#ffb3b3}}</style></head>
<body><main class='card'><h1>VibeStick 语音服务</h1><p>这个页面只能在当前电脑打开。API Key 不会进入 S3 固件，也不会通过局域网传输。</p>{notice}
<label>StickS3 Bridge 配对码</label><input value='{html.escape(pairing_token)}' readonly><small>首次配网时把这个配对码填入 StickS3 网页；它不是语音 API Key。</small>
<form method='post' action='/setup/voice'><input type='hidden' name='csrf' value='{html.escape(csrf_token)}'>
<label>语音服务商</label><select name='profile'>{options}</select>
<label>API 地址</label><input name='base_url' value='{html.escape(base_url)}' required>
<label>识别模型</label><input name='model' value='{html.escape(model)}' required>
<label>语言</label><input name='language' value='{html.escape(language)}' required>
<label>API Key</label><input name='api_key' type='password' autocomplete='new-password' placeholder='{key_hint}'><small>{key_hint}</small>
<button type='submit'>保存并立即启用</button></form></main></body></html>"""


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
        quota_5h_reset_minutes=existing.quota_5h_reset_minutes,
        quota_7d_remaining=existing.quota_7d_remaining,
        quota_7d_reset_days=existing.quota_7d_reset_days,
        quota_7d_reset_minutes=existing.quota_7d_reset_minutes,
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
        quota_5h_reset_minutes=observation.quota_5h_reset_minutes,
        quota_7d_remaining=observation.quota_7d_remaining,
        quota_7d_reset_days=observation.quota_7d_reset_days,
        quota_7d_reset_minutes=observation.quota_7d_reset_minutes,
        quota_updated_at=observation.quota_updated_at,
        quota_stale=observation.quota_stale,
        funds_balance=observation.funds_balance,
        today_spend=observation.today_spend,
        today_tokens=observation.today_tokens,
        month_cost_usd=observation.month_cost_usd,
        month_tokens=observation.month_tokens,
        today_used_percent=observation.today_used_percent,
        running_tasks=observation.running_tasks,
        waiting_tasks=observation.waiting_tasks,
        finished_tasks=observation.finished_tasks,
    )


def _provider_state_from_observation(observation: ProviderObservation) -> ProviderState:
    return ProviderState(
        id=observation.provider_id,
        display_name=observation.display_name,
        implemented=True,
        status=observation.status,
        project=observation.project,
        quota_5h_remaining=observation.quota_5h_remaining,
        quota_5h_reset_minutes=observation.quota_5h_reset_minutes,
        quota_7d_remaining=observation.quota_7d_remaining,
        quota_7d_reset_days=observation.quota_7d_reset_days,
        quota_7d_reset_minutes=observation.quota_7d_reset_minutes,
        quota_updated_at=observation.quota_updated_at,
        quota_stale=observation.quota_stale,
        funds_balance=observation.funds_balance,
        today_spend=observation.today_spend,
        today_tokens=observation.today_tokens,
        month_cost_usd=observation.month_cost_usd,
        month_tokens=observation.month_tokens,
        today_used_percent=observation.today_used_percent,
        running_tasks=observation.running_tasks,
        waiting_tasks=observation.waiting_tasks,
        finished_tasks=observation.finished_tasks,
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


def _load_local_environment() -> None:
    path = APP_SUPPORT_DIR / ".env"
    for key, value in _read_env_values(path).items():
        os.environ.setdefault(key, value)


def main(argv: list[str] | None = None) -> None:
    _load_local_environment()
    args = build_parser().parse_args(argv)
    run_server(args.host, args.port)
