from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class AgentStatus(StrEnum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    DONE = "DONE"
    APPROVAL = "APPROVAL"
    ERROR = "ERROR"
    OFFLINE = "OFFLINE"
    UNKNOWN = "UNKNOWN"


class AlertType(StrEnum):
    NONE = "NONE"
    DONE = "DONE"
    APPROVAL = "APPROVAL"
    ERROR = "ERROR"


@dataclass
class CodexState:
    status: AgentStatus = AgentStatus.IDLE
    project: str = "vibestick"
    quota_5h_remaining: int | None = None
    quota_7d_remaining: int | None = None
    quota_7d_reset_days: int | None = None
    quota_updated_at: str = ""
    quota_stale: bool = False
    funds_balance: str | None = None
    today_spend: str | None = None
    today_tokens: int | None = None
    today_used_percent: int | None = None
    running_tasks: int = 0
    waiting_tasks: int = 0
    finished_tasks: int = 0


@dataclass
class ProviderState:
    id: str = "codex"
    display_name: str = "Codex"
    implemented: bool = True
    status: AgentStatus = AgentStatus.IDLE
    project: str = "vibestick"
    quota_5h_remaining: int | None = None
    quota_7d_remaining: int | None = None
    quota_7d_reset_days: int | None = None
    quota_updated_at: str = ""
    quota_stale: bool = False
    funds_balance: str | None = None
    today_spend: str | None = None
    today_tokens: int | None = None
    today_used_percent: int | None = None
    running_tasks: int = 0
    waiting_tasks: int = 0
    finished_tasks: int = 0


@dataclass
class AlertState:
    event_id: str = ""
    type: AlertType = AlertType.NONE
    message: str = ""


@dataclass
class VibeStickState:
    time: str
    date: str
    weekday: str
    wifi: bool
    ble: bool
    battery: int | None
    active_provider: str
    provider: ProviderState
    codex: CodexState
    alert: AlertState

    def to_jsonable(self) -> dict[str, Any]:
        data = asdict(self)
        data["battery"] = None
        data["provider"]["status"] = self.provider.status.value
        data["codex"]["status"] = self.codex.status.value
        data["alert"]["type"] = self.alert.type.value
        return data


def now_time_text() -> str:
    return datetime.now().strftime("%H:%M:%S")


def now_date_text() -> str:
    now = datetime.now()
    return f"{now.strftime('%b').upper()} {now.day}"


def now_weekday_text() -> str:
    return datetime.now().strftime("%A")


def event_id(prefix: str) -> str:
    return f"evt_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{prefix}"


def state_from_dict(data: dict[str, Any]) -> VibeStickState:
    provider_data = data.get("provider", {})
    codex_data = data.get("codex", {})
    codex_data = codex_data if isinstance(codex_data, dict) else {}
    if isinstance(provider_data, dict) and provider_data.get("id") == "codex" and not codex_data:
        codex_data = provider_data
    alert_data = data.get("alert", {})
    alert_data = alert_data if isinstance(alert_data, dict) else {}
    provider_state = _provider_state_from_dict(codex_data)
    return VibeStickState(
        time=now_time_text(),
        date=now_date_text(),
        weekday=now_weekday_text(),
        wifi=bool(data.get("wifi", True)),
        ble=bool(data.get("ble", False)),
        battery=data.get("battery"),
        active_provider="codex",
        provider=provider_state,
        codex=CodexState(
            status=AgentStatus(codex_data.get("status", AgentStatus.IDLE.value)),
            project=str(codex_data.get("project") or "vibestick"),
            quota_5h_remaining=codex_data.get("quota_5h_remaining"),
            quota_7d_remaining=codex_data.get("quota_7d_remaining"),
            quota_7d_reset_days=_optional_int(codex_data.get("quota_7d_reset_days")),
            quota_updated_at=str(codex_data.get("quota_updated_at") or ""),
            quota_stale=bool(codex_data.get("quota_stale", False)),
            funds_balance=_optional_text(codex_data.get("funds_balance")),
            today_spend=_optional_text(codex_data.get("today_spend")),
            today_tokens=_optional_int(codex_data.get("today_tokens")),
            today_used_percent=_optional_percent(
                codex_data.get("today_used_percent")
            ),
            running_tasks=_optional_int(codex_data.get("running_tasks")) or 0,
            waiting_tasks=_optional_int(codex_data.get("waiting_tasks")) or 0,
            finished_tasks=_optional_int(codex_data.get("finished_tasks")) or 0,
        ),
        alert=AlertState(
            event_id=str(alert_data.get("event_id") or ""),
            type=AlertType(alert_data.get("type", AlertType.NONE.value)),
            message=str(alert_data.get("message") or ""),
        ),
    )


def _provider_state_from_dict(codex_data: dict[str, Any]) -> ProviderState:
    return ProviderState(
        id="codex",
        display_name="Codex",
        implemented=True,
        status=AgentStatus(codex_data.get("status", AgentStatus.IDLE.value)),
        project=str(codex_data.get("project") or "vibestick"),
        quota_5h_remaining=codex_data.get("quota_5h_remaining"),
        quota_7d_remaining=codex_data.get("quota_7d_remaining"),
        quota_7d_reset_days=_optional_int(codex_data.get("quota_7d_reset_days")),
        quota_updated_at=str(codex_data.get("quota_updated_at") or ""),
        quota_stale=bool(codex_data.get("quota_stale", False)),
        funds_balance=_optional_text(codex_data.get("funds_balance")),
        today_spend=_optional_text(codex_data.get("today_spend")),
        today_tokens=_optional_int(codex_data.get("today_tokens")),
        today_used_percent=_optional_percent(codex_data.get("today_used_percent")),
        running_tasks=_optional_int(codex_data.get("running_tasks")) or 0,
        waiting_tasks=_optional_int(codex_data.get("waiting_tasks")) or 0,
        finished_tasks=_optional_int(codex_data.get("finished_tasks")) or 0,
    )


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def _optional_percent(value: object) -> int | None:
    parsed = _optional_int(value)
    return min(100, parsed) if parsed is not None else None


def default_state() -> VibeStickState:
    codex = CodexState(
        status=AgentStatus.RUNNING,
        project="vibestick",
        quota_5h_remaining=None,
        quota_7d_remaining=None,
        quota_7d_reset_days=None,
        quota_updated_at="",
        quota_stale=False,
        funds_balance=None,
        today_spend=None,
        today_tokens=None,
        today_used_percent=None,
        running_tasks=0,
        waiting_tasks=0,
        finished_tasks=0,
    )
    return VibeStickState(
        time=now_time_text(),
        date=now_date_text(),
        weekday=now_weekday_text(),
        wifi=True,
        ble=False,
        battery=None,
        active_provider="codex",
        provider=ProviderState(
            id="codex",
            display_name="Codex",
            implemented=True,
            status=codex.status,
            project=codex.project,
            quota_5h_remaining=codex.quota_5h_remaining,
            quota_7d_remaining=codex.quota_7d_remaining,
            quota_7d_reset_days=codex.quota_7d_reset_days,
            quota_updated_at=codex.quota_updated_at,
            quota_stale=codex.quota_stale,
            funds_balance=codex.funds_balance,
            today_spend=codex.today_spend,
            today_tokens=codex.today_tokens,
            today_used_percent=codex.today_used_percent,
            running_tasks=codex.running_tasks,
            waiting_tasks=codex.waiting_tasks,
            finished_tasks=codex.finished_tasks,
        ),
        codex=codex,
        alert=AlertState(event_id="", type=AlertType.NONE, message=""),
    )
