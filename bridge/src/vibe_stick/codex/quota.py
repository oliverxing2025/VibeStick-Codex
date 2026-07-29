from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class QuotaSnapshot:
    quota_5h_remaining: int | None = None
    quota_7d_remaining: int | None = None
    quota_updated_at: str = ""
    quota_stale: bool = False
    quota_7d_reset_days: int | None = None
    quota_7d_resets_at: float | None = None

    def to_jsonable(self) -> dict[str, Any]:
        return asdict(self)


def load_quota(path: Path) -> QuotaSnapshot:
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return QuotaSnapshot()
    return QuotaSnapshot(
        quota_5h_remaining=_percent_or_none(data.get("quota_5h_remaining")),
        quota_7d_remaining=_percent_or_none(data.get("quota_7d_remaining")),
        quota_7d_reset_days=_nonnegative_int_or_none(data.get("quota_7d_reset_days")),
        quota_7d_resets_at=_nonnegative_float_or_none(data.get("quota_7d_resets_at")),
        quota_updated_at=str(data.get("quota_updated_at") or ""),
        quota_stale=bool(data.get("quota_stale", False)),
    )


def save_quota(path: Path, snapshot: QuotaSnapshot) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot.to_jsonable(), indent=2) + "\n")


def _percent_or_none(value: object) -> int | None:
    if value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return max(0, min(100, number))


def _nonnegative_int_or_none(value: object) -> int | None:
    if value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return max(0, number)


def _nonnegative_float_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, number)
