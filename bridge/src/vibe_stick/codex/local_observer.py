from __future__ import annotations

import json
import math
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

from vibe_stick.codex.quota import QuotaSnapshot
from vibe_stick.protocol.state import AgentStatus
from vibe_stick.providers._jsonl import session_files, tail_json_events


CODEX_HOME = Path.home() / ".codex"
SESSIONS_DIR = CODEX_HOME / "sessions"
TAIL_BYTES = 1_500_000
MAX_SESSION_FILES = 40
RUNNING_ACTIVITY_WINDOW = timedelta(minutes=4)
RUNNING_TASK_STALE_AFTER = timedelta(hours=6)
FILE_CHANGE_APPROVAL_GRACE = timedelta(seconds=2)
ALERT_ACTIVITY_WINDOW = timedelta(minutes=5)
QUOTA_STALE_AFTER = timedelta(minutes=30)
THREAD_ID_RE = re.compile(
    r"(?<![0-9a-f])"
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
    r"(?![0-9a-f])",
    re.IGNORECASE,
)


@dataclass
class LocalCodexObservation:
    status: AgentStatus
    project: str
    quota: QuotaSnapshot | None
    quota_found: bool
    alert_type: str = ""
    alert_message: str = ""
    alert_timestamp: datetime | None = None
    latest_event_type: str = ""
    latest_event_timestamp: datetime | None = None
    latest_session_path: str = ""
    codex_online: bool = False
    funds_balance: str | None = None
    today_spend: str | None = None
    today_tokens: int | None = None
    today_used_percent: int | None = None
    running_tasks: int = 0
    waiting_tasks: int = 0


def observe_codex(project_root: Path) -> LocalCodexObservation:
    now = datetime.now(timezone.utc)
    codex_online = _codex_process_running()
    project = _project_name_from_env_or_root(project_root)
    latest_cwd: Path | None = None
    latest_cwd_timestamp: datetime | None = None
    latest_event: tuple[datetime, str, str] | None = None
    latest_alert: tuple[datetime, AgentStatus, str, str] | None = None
    latest_quota: tuple[datetime, QuotaSnapshot] | None = None
    latest_funds: tuple[datetime, str] | None = None
    today_tokens = 0
    today_token_data_found = False
    previous_weekly_used: tuple[datetime, float] | None = None
    first_today_weekly_used: tuple[datetime, float] | None = None
    latest_today_weekly_used: tuple[datetime, float] | None = None
    running_tasks = 0
    waiting_tasks = 0
    local_now = datetime.now().astimezone()
    local_today = local_now.date()
    local_day_start = datetime.combine(
        local_today,
        time.min,
        tzinfo=local_now.tzinfo,
    ).astimezone(timezone.utc)
    latest_session_path = ""

    for session_path in _session_files():
        session_tokens: tuple[datetime, int] | None = None
        latest_session_path = latest_session_path or str(session_path)
        session_events = _tail_json_events(session_path)
        if _session_is_waiting(session_events, now):
            waiting_tasks += 1
        elif _session_is_running(session_events, now):
            running_tasks += 1
        for event in session_events:
            timestamp = _parse_timestamp(event.get("timestamp"))
            if timestamp is None:
                continue

            top_type = str(event.get("type") or "")
            payload = event.get("payload")
            payload = payload if isinstance(payload, dict) else {}
            payload_type = str(payload.get("type") or top_type)
            candidate_type = payload_type or top_type

            if top_type == "turn_context":
                cwd = payload.get("cwd")
                if isinstance(cwd, str) and cwd:
                    if latest_cwd is None or _is_newer(timestamp, latest_cwd_timestamp):
                        latest_cwd = Path(cwd)
                        latest_cwd_timestamp = timestamp

            if candidate_type:
                if latest_event is None or timestamp > latest_event[0]:
                    latest_event = (timestamp, candidate_type, str(payload.get("message") or ""))

            quota = _quota_from_payload(payload, timestamp, now)
            if quota is not None and (latest_quota is None or timestamp > latest_quota[0]):
                latest_quota = (timestamp, quota)
            weekly_used = _weekly_used_percent_from_payload(payload)
            if weekly_used is not None:
                if timestamp < local_day_start:
                    if (
                        previous_weekly_used is None
                        or timestamp > previous_weekly_used[0]
                    ):
                        previous_weekly_used = (timestamp, weekly_used)
                else:
                    if (
                        first_today_weekly_used is None
                        or timestamp < first_today_weekly_used[0]
                    ):
                        first_today_weekly_used = (timestamp, weekly_used)
                    if (
                        latest_today_weekly_used is None
                        or timestamp > latest_today_weekly_used[0]
                    ):
                        latest_today_weekly_used = (timestamp, weekly_used)

            funds = _funds_from_payload(payload)
            if funds is not None and (latest_funds is None or timestamp > latest_funds[0]):
                latest_funds = (timestamp, funds)

            tokens = _total_tokens_from_payload(payload)
            if (
                tokens is not None
                and timestamp.astimezone().date() == local_today
                and (session_tokens is None or timestamp > session_tokens[0])
            ):
                session_tokens = (timestamp, tokens)

            alert = _alert_from_payload(candidate_type, payload)
            if alert is not None:
                alert_status, alert_kind, message = alert
                if latest_alert is None or timestamp > latest_alert[0]:
                    latest_alert = (timestamp, alert_status, alert_kind, message)
        if session_tokens is not None:
            today_tokens += session_tokens[1]
            today_token_data_found = True

    if latest_cwd is not None:
        project = _project_name_from_path(latest_cwd)

    quota_snapshot = latest_quota[1] if latest_quota else None
    if not codex_online:
        status = AgentStatus.OFFLINE
    elif (
        latest_alert
        and now - latest_alert[0] <= ALERT_ACTIVITY_WINDOW
        and (latest_event is None or latest_alert[0] >= latest_event[0])
    ):
        status = latest_alert[1]
    elif latest_event and now - latest_event[0] <= RUNNING_ACTIVITY_WINDOW:
        status = AgentStatus.RUNNING
    else:
        status = AgentStatus.IDLE

    observation = LocalCodexObservation(
        status=status,
        project=project,
        quota=quota_snapshot,
        quota_found=quota_snapshot is not None,
        latest_session_path=latest_session_path,
        codex_online=codex_online,
        funds_balance=latest_funds[1] if latest_funds else None,
        today_spend=_configured_today_spend(),
        today_tokens=today_tokens if today_token_data_found else None,
        today_used_percent=_daily_used_percent(
            previous_weekly_used[1] if previous_weekly_used else None,
            first_today_weekly_used[1] if first_today_weekly_used else None,
            latest_today_weekly_used[1] if latest_today_weekly_used else None,
        ),
        running_tasks=running_tasks,
        waiting_tasks=waiting_tasks,
    )
    if latest_alert and status == latest_alert[1]:
        observation.alert_timestamp = latest_alert[0]
        observation.alert_type = latest_alert[2]
        observation.alert_message = latest_alert[3]
    if latest_event:
        observation.latest_event_timestamp = latest_event[0]
        observation.latest_event_type = latest_event[1]
    return observation


def _session_files() -> list[Path]:
    return session_files(SESSIONS_DIR, max_files=MAX_SESSION_FILES)


def _tail_json_events(path: Path) -> list[dict[str, Any]]:
    return list(tail_json_events(path, tail_bytes=TAIL_BYTES))


def waiting_thread_ids() -> list[str]:
    """Return all recent Codex thread ids that are still waiting for approval."""
    now = datetime.now(timezone.utc)
    thread_ids: list[str] = []
    seen: set[str] = set()
    for session_path in _session_files():
        events = _tail_json_events(session_path)
        if not _session_is_waiting(events, now):
            continue
        thread_id = _thread_id_from_session(session_path, events)
        if thread_id and thread_id not in seen:
            seen.add(thread_id)
            thread_ids.append(thread_id)
    return thread_ids


def _thread_id_from_session(path: Path, events: list[dict[str, Any]]) -> str:
    for event in events:
        if event.get("type") != "session_meta":
            continue
        payload = event.get("payload")
        payload = payload if isinstance(payload, dict) else {}
        candidate = str(payload.get("id") or "")
        if THREAD_ID_RE.fullmatch(candidate):
            return candidate.lower()
    match = THREAD_ID_RE.search(path.name)
    return match.group(1).lower() if match else ""


def _session_is_running(events: list[dict[str, Any]], now: datetime) -> bool:
    latest_timestamp: datetime | None = None
    latest_lifecycle: tuple[datetime, str] | None = None
    for event in events:
        timestamp = _parse_timestamp(event.get("timestamp"))
        if timestamp is None:
            continue
        if latest_timestamp is None or timestamp > latest_timestamp:
            latest_timestamp = timestamp
        top_type = str(event.get("type") or "")
        payload = event.get("payload")
        payload = payload if isinstance(payload, dict) else {}
        event_type = str(payload.get("type") or top_type)
        if event_type in {"task_started", "task_complete"}:
            if latest_lifecycle is None or timestamp > latest_lifecycle[0]:
                latest_lifecycle = (timestamp, event_type)

    if latest_timestamp is None:
        return False
    if latest_lifecycle is not None:
        return (
            latest_lifecycle[1] == "task_started"
            and now - latest_timestamp <= RUNNING_TASK_STALE_AFTER
        )
    return now - latest_timestamp <= RUNNING_ACTIVITY_WINDOW


def _session_is_waiting(events: list[dict[str, Any]], now: datetime) -> bool:
    pending_approval_calls: dict[str, datetime] = {}
    pending_file_change_calls: dict[str, datetime] = {}
    latest_event: tuple[datetime, str, dict[str, Any]] | None = None
    for event in events:
        timestamp = _parse_timestamp(event.get("timestamp"))
        if timestamp is None:
            continue
        top_type = str(event.get("type") or "")
        payload = event.get("payload")
        payload = payload if isinstance(payload, dict) else {}
        event_type = str(payload.get("type") or top_type)
        call_id = payload.get("call_id")
        if (
            event_type in {"function_call", "custom_tool_call"}
            and isinstance(call_id, str)
            and call_id
        ):
            if _tool_call_requires_approval(payload):
                pending_approval_calls[call_id] = timestamp
            if payload.get("name") == "apply_patch":
                pending_file_change_calls[call_id] = timestamp
        elif (
            event_type
            in {
                "function_call_output",
                "custom_tool_call_output",
                "patch_apply_end",
            }
            and isinstance(call_id, str)
            and call_id
        ):
            pending_approval_calls.pop(call_id, None)
            pending_file_change_calls.pop(call_id, None)
        if latest_event is None or timestamp > latest_event[0]:
            latest_event = (timestamp, event_type, payload)

    if any(
        now - timestamp <= RUNNING_TASK_STALE_AFTER
        for timestamp in pending_approval_calls.values()
    ):
        return True
    if any(
        FILE_CHANGE_APPROVAL_GRACE <= now - timestamp <= RUNNING_TASK_STALE_AFTER
        for timestamp in pending_file_change_calls.values()
    ):
        return True
    if latest_event is None or now - latest_event[0] > RUNNING_TASK_STALE_AFTER:
        return False
    alert = _alert_from_payload(latest_event[1], latest_event[2])
    return alert is not None and alert[0] == AgentStatus.APPROVAL


def _tool_call_requires_approval(payload: dict[str, Any]) -> bool:
    for field in ("arguments", "input"):
        value = payload.get(field)
        if isinstance(value, dict):
            if _contains_required_escalation(value):
                return True
        elif isinstance(value, str):
            try:
                decoded = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                decoded = None
            if _contains_required_escalation(decoded):
                return True
            if re.search(
                r"""["']sandbox_permissions["']\s*:\s*["']require_escalated["']""",
                value,
            ):
                return True
    return False


def _contains_required_escalation(value: Any) -> bool:
    if isinstance(value, dict):
        if value.get("sandbox_permissions") == "require_escalated":
            return True
        return any(_contains_required_escalation(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_required_escalation(item) for item in value)
    return False


def _quota_from_payload(
    payload: dict[str, Any],
    timestamp: datetime,
    now: datetime,
) -> QuotaSnapshot | None:
    if payload.get("type") != "token_count":
        return None
    rate_limits = payload.get("rate_limits")
    if not isinstance(rate_limits, dict):
        return None

    five_hour = None
    seven_day = None
    seven_day_reset_days = None
    for window in ("primary", "secondary"):
        data = rate_limits.get(window)
        if not isinstance(data, dict):
            continue
        remaining = _remaining_percent(data.get("used_percent"))
        minutes = data.get("window_minutes")
        if minutes == 300:
            five_hour = remaining
        elif minutes == 10080:
            seven_day = remaining
            seven_day_reset_days = _days_until_reset(data.get("resets_at"), now)

    if five_hour is None and seven_day is None:
        return None

    return QuotaSnapshot(
        quota_5h_remaining=five_hour,
        quota_7d_remaining=seven_day,
        quota_7d_reset_days=seven_day_reset_days,
        quota_updated_at=timestamp.astimezone().strftime("%H:%M"),
        quota_stale=now - timestamp > QUOTA_STALE_AFTER,
    )


def _weekly_used_percent_from_payload(payload: dict[str, Any]) -> float | None:
    if payload.get("type") != "token_count":
        return None
    rate_limits = payload.get("rate_limits")
    if not isinstance(rate_limits, dict):
        return None
    for window in ("primary", "secondary"):
        data = rate_limits.get(window)
        if not isinstance(data, dict) or data.get("window_minutes") != 10080:
            continue
        try:
            used = float(data.get("used_percent"))
        except (TypeError, ValueError):
            return None
        if not math.isfinite(used):
            return None
        return max(0.0, min(100.0, used))
    return None


def _daily_used_percent(
    previous_used: float | None,
    first_today_used: float | None,
    latest_today_used: float | None,
) -> int | None:
    if latest_today_used is None:
        return None
    baseline = previous_used if previous_used is not None else first_today_used
    if baseline is None:
        return None
    return max(0, min(100, int(round(latest_today_used - baseline))))


def _remaining_percent(used_percent: object) -> int | None:
    try:
        used = float(used_percent)
    except (TypeError, ValueError):
        return None
    return max(0, min(100, int(round(100.0 - used))))


def _days_until_reset(resets_at: object, now: datetime) -> int | None:
    try:
        reset_timestamp = float(resets_at)
    except (TypeError, ValueError):
        return None
    seconds_left = reset_timestamp - now.timestamp()
    return max(0, int(math.ceil(seconds_left / 86400.0)))


def _funds_from_payload(payload: dict[str, Any]) -> str | None:
    if payload.get("type") != "token_count":
        return None
    rate_limits = payload.get("rate_limits")
    credits = rate_limits.get("credits") if isinstance(rate_limits, dict) else None
    if not isinstance(credits, dict):
        return None
    balance = credits.get("balance")
    if balance is None:
        return None
    text = str(balance).strip()
    return text or None


def _total_tokens_from_payload(payload: dict[str, Any]) -> int | None:
    if payload.get("type") != "token_count":
        return None
    info = payload.get("info")
    usage = info.get("total_token_usage") if isinstance(info, dict) else None
    value = usage.get("total_tokens") if isinstance(usage, dict) else None
    if isinstance(value, bool):
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def _configured_today_spend() -> str | None:
    value = os.environ.get("VIBE_STICK_TODAY_SPEND", "").strip()
    return value or None


def _alert_from_payload(
    payload_type: str,
    payload: dict[str, Any],
) -> tuple[AgentStatus, str, str] | None:
    normalized = payload_type.lower()
    if normalized == "task_complete":
        return (AgentStatus.DONE, "DONE", "Codex task completed")
    if "approval" in normalized or "permission" in normalized:
        return (AgentStatus.APPROVAL, "APPROVAL", "Codex is waiting for approval")
    if normalized in {"error", "agent_error"} or normalized.endswith("_error"):
        message = str(payload.get("message") or payload.get("error") or "Codex task failed or needs attention")
        return (AgentStatus.ERROR, "ERROR", message)
    rate_limit_reached = payload.get("rate_limit_reached_type")
    if rate_limit_reached:
        return (AgentStatus.ERROR, "ERROR", "Codex quota limit reached")
    return None


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_newer(value: datetime, other: datetime | None) -> bool:
    return other is None or value > other


def _codex_process_running() -> bool:
    try:
        result = subprocess.run(
            ["ps", "-axo", "command="],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if result.returncode != 0:
        return False

    for line in result.stdout.splitlines():
        lower = line.lower()
        if "/applications/codex.app/" in lower:
            return True
        if "/applications/chatgpt.app/" in lower:
            return True
        if "codex app-server" in lower:
            return True
    return False


def _project_name_from_env_or_root(project_root: Path) -> str:
    configured = os.environ.get("VIBE_STICK_PROJECT_NAME", "").strip()
    if configured:
        return configured
    return _project_name_from_path(project_root)


def _project_name_from_path(path: Path) -> str:
    root = path.expanduser().resolve()
    if root.name in {"bridge", "firmware", "app", "scripts"} and (root.parent / "README.md").exists():
        root = root.parent
    return root.name or "vibestick"
