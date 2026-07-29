from __future__ import annotations

import os
from pathlib import Path


APP_SUPPORT_DIR = (
    Path.home() / "Library" / "Application Support" / "VibeStick"
)
STATE_PATH = APP_SUPPORT_DIR / "state.json"
QUOTA_PATH = APP_SUPPORT_DIR / "quota.json"
TASK_STATS_PATH = APP_SUPPORT_DIR / "task-stats.json"
RECORDING_PATH = APP_SUPPORT_DIR / "recording.json"
HUD_STATE_PATH = APP_SUPPORT_DIR / "hud-state.json"
RECORDINGS_DIR = APP_SUPPORT_DIR / "Recordings"


def ensure_app_support() -> Path:
    ensure_private_directory(APP_SUPPORT_DIR)
    return APP_SUPPORT_DIR


def ensure_private_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass
    return path


def restrict_private_file(path: Path) -> None:
    try:
        path.chmod(0o600)
    except OSError:
        pass


def write_private_text(path: Path, data: str, *, encoding: str = "utf-8") -> None:
    ensure_private_directory(path.parent)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding=encoding) as handle:
        handle.write(data)
    restrict_private_file(path)
