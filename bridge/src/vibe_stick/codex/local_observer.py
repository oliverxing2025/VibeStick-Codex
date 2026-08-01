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
ARCHIVED_SESSIONS_DIR = CODEX_HOME / "archived_sessions"
TAIL_BYTES = 1_500_000
MAX_SESSION_FILES = 40
MAX_ARCHIVED_QUOTA_FILES = 12
RUNNING_ACTIVITY_WINDOW = timedelta(minutes=4)
RUNNING_TASK_STALE_AFTER = timedelta(hours=6)
FILE_CHANGE_APPROVAL_GRACE = timedelta(seconds=2)
ALERT_ACTIVITY_WINDOW = timedelta(minutes=5)
QUOTA_STALE_AFTER = timedelta(minutes=30)
DAILY_BASELINE_MAX_AGE = timedelta(hours=6)
THREAD_ID_RE = re.compile(
    r"(?<![0-9a-f])"
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
    r"(?![0-9a-f])",
    re.IGNORECASE,
)
_DAILY_USAGE_CACHE_DAY_START: datetime | None = None
_DAILY_USAGE_FILE_CACHE: dict[
    Path,
    tuple[int, list[tuple[datetime, float, float | None]]],
] = {}
_TOKEN_CACHE_PERIOD_START: datetime | None = None
_TOKEN_FILE_CACHE: dict[
    Path,
    tuple[
        int,
        tuple[datetime, int] | None,
        tuple[datetime, int] | None,
    ],
] = {}
_MONTHLY_COST_PERIOD_START: datetime | None = None
_ARCHIVED_QUOTA_CACHE_SIGNATURE: tuple[tuple[str, int, int], ...] | None = None
_ARCHIVED_QUOTA_CACHE: tuple[
    tuple[datetime, QuotaSnapshot] | None,
    tuple[datetime, str] | None,
] = (None, None)

MODEL_USD_PER_MILLION_TOKENS: dict[str, tuple[float, float, float]] = {
    "gpt-5.6-sol": (5.0, 0.5, 30.0),
    "gpt-5.6": (5.0, 0.5, 30.0),
    "gpt-5.6-terra": (2.5, 0.25, 15.0),
    "gpt-5.6-luna": (1.0, 0.1, 6.0),
    "gpt-5.5": (5.0, 0.5, 30.0),
    "gpt-5.4": (2.5, 0.25, 15.0),
    "gpt-5.4-mini": (0.75, 0.075, 4.52),
    "gpt-5.3-codex": (1.75, 0.175, 14.0),
    "gpt-5.2": (1.75, 0.175, 14.0),
    "gpt-5.2-codex": (1.75, 0.175, 14.0),
    "codex-auto-review": (1.75, 0.175, 14.0),
}


@dataclass(frozen=True)
class _TokenUsage:
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int


@dataclass
class _MonthlyCostFileState:
    offset: int = 0
    model: str = ""
    usage: _TokenUsage | None = None
    cost_usd: float = 0.0
    priced_any: bool = False
    month_tokens: int = 0
    tokens_any: bool = False


_MONTHLY_COST_FILE_CACHE: dict[Path, _MonthlyCostFileState] = {}


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
    month_cost_usd: float | None = None
    month_tokens: int | None = None
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
    running_tasks = 0
    waiting_tasks = 0
    local_now = datetime.now().astimezone()
    local_today = local_now.date()
    local_day_start = datetime.combine(
        local_today,
        time.min,
        tzinfo=local_now.tzinfo,
    ).astimezone(timezone.utc)
    local_month_start = datetime.combine(
        local_today.replace(day=1),
        time.min,
        tzinfo=local_now.tzinfo,
    ).astimezone(timezone.utc)
    latest_session_path = ""

    for session_path in _session_files():
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
            funds = _funds_from_payload(payload)
            if funds is not None and (latest_funds is None or timestamp > latest_funds[0]):
                latest_funds = (timestamp, funds)

            alert = _alert_from_payload(candidate_type, payload)
            if alert is not None:
                alert_status, alert_kind, message = alert
                if latest_alert is None or timestamp > latest_alert[0]:
                    latest_alert = (timestamp, alert_status, alert_kind, message)

    archived_quota, archived_funds = _latest_archived_quota_and_funds(now)
    if archived_quota is not None and (
        latest_quota is None or archived_quota[0] > latest_quota[0]
    ):
        latest_quota = archived_quota
    if archived_funds is not None and (
        latest_funds is None or archived_funds[0] > latest_funds[0]
    ):
        latest_funds = archived_funds

    if latest_cwd is not None:
        project = _project_name_from_path(latest_cwd)

    daily_usage_samples = _daily_weekly_usage_samples(local_day_start)
    previous_weekly_used = max(
        (
            sample
            for sample in daily_usage_samples
            if sample[0] < local_day_start
        ),
        default=None,
        key=lambda sample: sample[0],
    )
    today_weekly_used_samples = [
        sample
        for sample in daily_usage_samples
        if sample[0] >= local_day_start
    ]
    quota_snapshot = latest_quota[1] if latest_quota else None
    period_start = _quota_period_start(quota_snapshot)
    period_tokens = (
        _token_total_since(period_start)
        if period_start is not None
        else None
    )
    daily_baseline: tuple[float, float | None] | None = None
    if (
        previous_weekly_used is not None
        and timedelta(0) <= local_day_start - previous_weekly_used[0]
        <= DAILY_BASELINE_MAX_AGE
    ):
        daily_baseline = (
            previous_weekly_used[1],
            previous_weekly_used[2],
        )
    if not codex_online:
        status = AgentStatus.OFFLINE
    elif waiting_tasks > 0:
        status = AgentStatus.APPROVAL
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

    month_cost_usd = _monthly_api_cost_usd(local_month_start)
    observation = LocalCodexObservation(
        status=status,
        project=project,
        quota=quota_snapshot,
        quota_found=quota_snapshot is not None,
        latest_session_path=latest_session_path,
        codex_online=codex_online,
        funds_balance=latest_funds[1] if latest_funds else None,
        today_spend=_configured_today_spend(),
        today_tokens=period_tokens,
        month_cost_usd=month_cost_usd,
        month_tokens=_monthly_token_total(local_month_start),
        today_used_percent=_daily_used_percent_from_samples(
            daily_baseline,
            today_weekly_used_samples,
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


def _latest_quota_and_funds(
    paths: list[Path],
    now: datetime,
) -> tuple[
    tuple[datetime, QuotaSnapshot] | None,
    tuple[datetime, str] | None,
]:
    latest_quota: tuple[datetime, QuotaSnapshot] | None = None
    latest_funds: tuple[datetime, str] | None = None
    for path in paths:
        for event in _tail_json_events(path):
            timestamp = _parse_timestamp(event.get("timestamp"))
            if timestamp is None:
                continue
            payload = event.get("payload")
            payload = payload if isinstance(payload, dict) else {}
            quota = _quota_from_payload(payload, timestamp, now)
            if quota is not None and (
                latest_quota is None or timestamp > latest_quota[0]
            ):
                latest_quota = (timestamp, quota)
            funds = _funds_from_payload(payload)
            if funds is not None and (
                latest_funds is None or timestamp > latest_funds[0]
            ):
                latest_funds = (timestamp, funds)
    return latest_quota, latest_funds


def _latest_archived_quota_and_funds(
    now: datetime,
) -> tuple[
    tuple[datetime, QuotaSnapshot] | None,
    tuple[datetime, str] | None,
]:
    global _ARCHIVED_QUOTA_CACHE_SIGNATURE
    global _ARCHIVED_QUOTA_CACHE

    paths = session_files(
        ARCHIVED_SESSIONS_DIR,
        max_files=MAX_ARCHIVED_QUOTA_FILES,
    )
    signature: list[tuple[str, int, int]] = []
    for path in paths:
        try:
            stat = path.stat()
        except OSError:
            continue
        signature.append((str(path), stat.st_mtime_ns, stat.st_size))
    current_signature = tuple(signature)
    if current_signature != _ARCHIVED_QUOTA_CACHE_SIGNATURE:
        _ARCHIVED_QUOTA_CACHE = _latest_quota_and_funds(paths, now)
        _ARCHIVED_QUOTA_CACHE_SIGNATURE = current_signature

    quota, funds = _ARCHIVED_QUOTA_CACHE
    if quota is not None:
        timestamp, snapshot = quota
        snapshot.quota_stale = now - timestamp > QUOTA_STALE_AFTER
    return quota, funds


def _daily_weekly_usage_samples(
    local_day_start: datetime,
) -> list[tuple[datetime, float, float | None]]:
    global _DAILY_USAGE_CACHE_DAY_START

    sample_start = local_day_start - DAILY_BASELINE_MAX_AGE
    if _DAILY_USAGE_CACHE_DAY_START != local_day_start:
        _DAILY_USAGE_CACHE_DAY_START = local_day_start
        _DAILY_USAGE_FILE_CACHE.clear()

    active_paths: set[Path] = set()
    for path in _daily_usage_session_files(sample_start):
        try:
            stat = path.stat()
        except OSError:
            continue
        active_paths.add(path)
        offset, samples = _DAILY_USAGE_FILE_CACHE.get(path, (0, []))
        if stat.st_size < offset:
            offset, samples = 0, []
        if stat.st_size == offset:
            continue
        try:
            with path.open("rb") as handle:
                handle.seek(offset)
                while True:
                    line_start = handle.tell()
                    raw_line = handle.readline()
                    if not raw_line:
                        offset = handle.tell()
                        break
                    if not raw_line.endswith(b"\n"):
                        offset = line_start
                        break
                    offset = handle.tell()
                    try:
                        event = json.loads(raw_line.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        continue
                    if not isinstance(event, dict):
                        continue
                    timestamp = _parse_timestamp(event.get("timestamp"))
                    if timestamp is None or timestamp < sample_start:
                        continue
                    payload = event.get("payload")
                    payload = payload if isinstance(payload, dict) else {}
                    weekly_usage = _weekly_usage_from_payload(payload)
                    if weekly_usage is None:
                        continue
                    samples.append(
                        (timestamp, weekly_usage[0], weekly_usage[1])
                    )
        except OSError:
            continue
        _DAILY_USAGE_FILE_CACHE[path] = (offset, samples)

    for cached_path in set(_DAILY_USAGE_FILE_CACHE) - active_paths:
        _DAILY_USAGE_FILE_CACHE.pop(cached_path, None)

    return [
        sample
        for _, samples in _DAILY_USAGE_FILE_CACHE.values()
        for sample in samples
    ]


def _daily_usage_session_files(sample_start: datetime) -> list[Path]:
    minimum_mtime = sample_start.timestamp()
    paths: list[Path] = []
    for root in (SESSIONS_DIR, ARCHIVED_SESSIONS_DIR):
        if not root.exists():
            continue
        for path in root.rglob("*.jsonl"):
            try:
                if path.is_file() and path.stat().st_mtime >= minimum_mtime:
                    paths.append(path)
            except OSError:
                continue
    return paths


def _token_total_since(period_start: datetime) -> int:
    global _TOKEN_CACHE_PERIOD_START

    if _TOKEN_CACHE_PERIOD_START != period_start:
        _TOKEN_CACHE_PERIOD_START = period_start
        _TOKEN_FILE_CACHE.clear()

    active_paths: set[Path] = set()
    for path in _daily_usage_session_files(period_start):
        try:
            stat = path.stat()
        except OSError:
            continue
        active_paths.add(path)
        offset, before_period, in_period = _TOKEN_FILE_CACHE.get(
            path,
            (0, None, None),
        )
        if stat.st_size < offset:
            offset, before_period, in_period = 0, None, None
        if stat.st_size != offset:
            try:
                with path.open("rb") as handle:
                    handle.seek(offset)
                    while True:
                        line_start = handle.tell()
                        raw_line = handle.readline()
                        if not raw_line:
                            offset = handle.tell()
                            break
                        if not raw_line.endswith(b"\n"):
                            offset = line_start
                            break
                        offset = handle.tell()
                        try:
                            event = json.loads(raw_line.decode("utf-8"))
                        except (UnicodeDecodeError, json.JSONDecodeError):
                            continue
                        if not isinstance(event, dict):
                            continue
                        timestamp = _parse_timestamp(event.get("timestamp"))
                        if timestamp is None:
                            continue
                        payload = event.get("payload")
                        payload = payload if isinstance(payload, dict) else {}
                        tokens = _total_tokens_from_payload(payload)
                        if tokens is None:
                            continue
                        sample = (timestamp, tokens)
                        if timestamp < period_start:
                            if (
                                before_period is None
                                or timestamp > before_period[0]
                            ):
                                before_period = sample
                        elif in_period is None or timestamp > in_period[0]:
                            in_period = sample
            except OSError:
                continue
        _TOKEN_FILE_CACHE[path] = (offset, before_period, in_period)

    for cached_path in set(_TOKEN_FILE_CACHE) - active_paths:
        _TOKEN_FILE_CACHE.pop(cached_path, None)

    total = 0
    for _, before_period, in_period in _TOKEN_FILE_CACHE.values():
        if in_period is None:
            continue
        baseline = before_period[1] if before_period is not None else 0
        total += max(0, in_period[1] - baseline)
    return total


def _monthly_api_cost_usd(period_start: datetime) -> float | None:
    global _MONTHLY_COST_PERIOD_START

    if _MONTHLY_COST_PERIOD_START != period_start:
        _MONTHLY_COST_PERIOD_START = period_start
        _MONTHLY_COST_FILE_CACHE.clear()

    active_paths: set[Path] = set()
    for path in _daily_usage_session_files(period_start):
        try:
            stat = path.stat()
        except OSError:
            continue
        active_paths.add(path)
        state = _MONTHLY_COST_FILE_CACHE.get(path, _MonthlyCostFileState())
        if stat.st_size < state.offset:
            state = _MonthlyCostFileState()
        if stat.st_size != state.offset:
            try:
                with path.open("rb") as handle:
                    handle.seek(state.offset)
                    while True:
                        line_start = handle.tell()
                        raw_line = handle.readline()
                        if not raw_line:
                            state.offset = handle.tell()
                            break
                        if not raw_line.endswith(b"\n"):
                            state.offset = line_start
                            break
                        state.offset = handle.tell()
                        try:
                            event = json.loads(raw_line.decode("utf-8"))
                        except (UnicodeDecodeError, json.JSONDecodeError):
                            continue
                        if not isinstance(event, dict):
                            continue
                        payload = event.get("payload")
                        payload = payload if isinstance(payload, dict) else {}
                        if event.get("type") == "turn_context":
                            model = payload.get("model")
                            if isinstance(model, str) and model.strip():
                                state.model = model.strip().lower()
                            continue
                        usage = _priced_token_usage_from_payload(payload)
                        if usage is None:
                            continue
                        timestamp = _parse_timestamp(event.get("timestamp"))
                        if timestamp is not None and timestamp >= period_start:
                            delta = _token_usage_delta(state.usage, usage)
                            state.month_tokens += (
                                delta.input_tokens + delta.output_tokens
                            )
                            state.tokens_any = True
                            cost = _token_usage_cost_usd(delta, state.model)
                            if cost is not None:
                                state.cost_usd += cost
                                state.priced_any = True
                        state.usage = usage
            except OSError:
                continue
        _MONTHLY_COST_FILE_CACHE[path] = state

    for cached_path in set(_MONTHLY_COST_FILE_CACHE) - active_paths:
        _MONTHLY_COST_FILE_CACHE.pop(cached_path, None)

    priced_states = [
        state for state in _MONTHLY_COST_FILE_CACHE.values() if state.priced_any
    ]
    if not priced_states:
        return None
    return round(sum(state.cost_usd for state in priced_states), 2)


def _monthly_token_total(period_start: datetime) -> int | None:
    _monthly_api_cost_usd(period_start)
    token_states = [
        state for state in _MONTHLY_COST_FILE_CACHE.values() if state.tokens_any
    ]
    if not token_states:
        return None
    return sum(state.month_tokens for state in token_states)


def _priced_token_usage_from_payload(payload: dict[str, Any]) -> _TokenUsage | None:
    if payload.get("type") != "token_count":
        return None
    info = payload.get("info")
    usage = info.get("total_token_usage") if isinstance(info, dict) else None
    if not isinstance(usage, dict):
        return None

    def token_value(key: str) -> int:
        value = usage.get(key)
        if isinstance(value, bool):
            return 0
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0

    return _TokenUsage(
        input_tokens=token_value("input_tokens"),
        cached_input_tokens=token_value("cached_input_tokens"),
        output_tokens=token_value("output_tokens"),
    )


def _token_usage_delta(
    previous: _TokenUsage | None,
    current: _TokenUsage,
) -> _TokenUsage:
    if previous is None:
        return current

    def delta(current_value: int, previous_value: int) -> int:
        return (
            current_value - previous_value
            if current_value >= previous_value
            else current_value
        )

    return _TokenUsage(
        input_tokens=delta(current.input_tokens, previous.input_tokens),
        cached_input_tokens=delta(
            current.cached_input_tokens,
            previous.cached_input_tokens,
        ),
        output_tokens=delta(current.output_tokens, previous.output_tokens),
    )


def _token_usage_cost_usd(usage: _TokenUsage, model: str) -> float | None:
    pricing_model = model.strip().lower()
    override = os.environ.get("VIBE_STICK_CODEX_PRICING_MODEL", "").strip().lower()
    prices = MODEL_USD_PER_MILLION_TOKENS.get(pricing_model)
    if prices is None and override:
        prices = MODEL_USD_PER_MILLION_TOKENS.get(override)
    if prices is None:
        return None
    input_price, cached_input_price, output_price = prices
    cached_tokens = min(usage.cached_input_tokens, usage.input_tokens)
    uncached_tokens = max(0, usage.input_tokens - cached_tokens)
    return (
        uncached_tokens * input_price
        + cached_tokens * cached_input_price
        + usage.output_tokens * output_price
    ) / 1_000_000.0


def _quota_period_start(snapshot: QuotaSnapshot | None) -> datetime | None:
    if snapshot is None or snapshot.quota_7d_resets_at is None:
        return None
    try:
        reset_at = datetime.fromtimestamp(
            snapshot.quota_7d_resets_at,
            tz=timezone.utc,
        )
    except (OverflowError, OSError, ValueError):
        return None
    return reset_at - timedelta(minutes=10080)


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
    if not isinstance(rate_limits, dict) or not _is_main_codex_rate_limit(
        rate_limits
    ):
        return None

    five_hour = None
    five_hour_reset_minutes = None
    seven_day = None
    seven_day_reset_days = None
    seven_day_reset_minutes = None
    seven_day_resets_at = None
    for window in ("primary", "secondary"):
        data = rate_limits.get(window)
        if not isinstance(data, dict):
            continue
        remaining = _remaining_percent(data.get("used_percent"))
        minutes = data.get("window_minutes")
        if minutes == 300:
            five_hour = remaining
            five_hour_reset_minutes = _minutes_until_reset(
                data.get("resets_at"), now
            )
        elif minutes == 10080:
            seven_day = remaining
            seven_day_reset_days = _days_until_reset(data.get("resets_at"), now)
            seven_day_reset_minutes = _minutes_until_reset(
                data.get("resets_at"), now
            )
            try:
                seven_day_resets_at = float(data.get("resets_at"))
            except (TypeError, ValueError):
                seven_day_resets_at = None
            if (
                seven_day_resets_at is not None
                and not math.isfinite(seven_day_resets_at)
            ):
                seven_day_resets_at = None

    if five_hour is None and seven_day is None:
        return None

    return QuotaSnapshot(
        quota_5h_remaining=five_hour,
        quota_5h_reset_minutes=five_hour_reset_minutes,
        quota_7d_remaining=seven_day,
        quota_7d_reset_days=seven_day_reset_days,
        quota_7d_reset_minutes=seven_day_reset_minutes,
        quota_updated_at=timestamp.astimezone().strftime("%H:%M"),
        quota_stale=now - timestamp > QUOTA_STALE_AFTER,
        quota_7d_resets_at=seven_day_resets_at,
    )


def _weekly_usage_from_payload(
    payload: dict[str, Any],
) -> tuple[float, float | None] | None:
    if payload.get("type") != "token_count":
        return None
    rate_limits = payload.get("rate_limits")
    if not isinstance(rate_limits, dict) or not _is_main_codex_rate_limit(
        rate_limits
    ):
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
        try:
            resets_at = float(data.get("resets_at"))
        except (TypeError, ValueError):
            resets_at = None
        if resets_at is not None and not math.isfinite(resets_at):
            resets_at = None
        return max(0.0, min(100.0, used)), resets_at
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


def _daily_used_percent_from_samples(
    previous_sample: tuple[float, float | None] | None,
    today_samples: list[tuple[datetime, float, float | None]],
) -> int | None:
    if not today_samples:
        return None

    ordered_samples = sorted(today_samples, key=lambda sample: sample[0])
    if previous_sample is None:
        previous_value = ordered_samples[0][1]
        current_resets_at = ordered_samples[0][2]
        ordered_samples = ordered_samples[1:]
    else:
        previous_value, current_resets_at = previous_sample

    total_used = 0.0
    for _, current_value, resets_at in ordered_samples:
        if (
            current_resets_at is not None
            and resets_at is not None
            and resets_at < current_resets_at - 300
        ):
            # A parallel task can emit an older quota snapshot after a reset.
            # Ignore that superseded window instead of counting another reset.
            continue
        if (
            current_resets_at is not None
            and resets_at is not None
            and resets_at > current_resets_at + 300
        ):
            total_used += current_value
            previous_value = current_value
            current_resets_at = resets_at
        elif current_value >= previous_value:
            total_used += current_value - previous_value
            previous_value = current_value
        else:
            # Without a reliable cycle id, a decrease is the best available
            # reset signal. With a cycle id, it is a stale in-cycle snapshot.
            if current_resets_at is None or resets_at is None:
                total_used += current_value
                previous_value = current_value
        if current_resets_at is None and resets_at is not None:
            current_resets_at = resets_at

    return max(0, min(100, int(round(total_used))))


def _remaining_percent(used_percent: object) -> int | None:
    try:
        used = float(used_percent)
    except (TypeError, ValueError):
        return None
    return max(0, min(100, int(round(100.0 - used))))


def _minutes_until_reset(resets_at: object, now: datetime) -> int | None:
    try:
        reset_timestamp = float(resets_at)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(reset_timestamp):
        return None
    seconds_left = max(0.0, reset_timestamp - now.timestamp())
    return int(math.ceil(seconds_left / 60.0))


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
    if not isinstance(rate_limits, dict) or not _is_main_codex_rate_limit(
        rate_limits
    ):
        return None
    credits = rate_limits.get("credits")
    if not isinstance(credits, dict):
        return None
    balance = credits.get("balance")
    if balance is None:
        return None
    text = str(balance).strip()
    return text or None


def _is_main_codex_rate_limit(rate_limits: dict[str, Any]) -> bool:
    limit_id = str(rate_limits.get("limit_id") or "").strip().lower()
    return not limit_id or limit_id == "codex"


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
