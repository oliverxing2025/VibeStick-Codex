from __future__ import annotations

import os
import platform
from pathlib import Path


def _default_app_support_dir() -> Path:
    system = platform.system()
    if system == "Windows":
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        return (Path(local_app_data) if local_app_data else
                Path.home() / "AppData" / "Local") / "VibeStick"
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "VibeStick"
    xdg_data_home = os.environ.get("XDG_DATA_HOME", "").strip()
    return (Path(xdg_data_home) if xdg_data_home else
            Path.home() / ".local" / "share") / "VibeStick"


APP_SUPPORT_DIR = _default_app_support_dir()
STATE_PATH = APP_SUPPORT_DIR / "state.json"
QUOTA_PATH = APP_SUPPORT_DIR / "quota.json"
TASK_STATS_PATH = APP_SUPPORT_DIR / "task-stats.json"
RECORDING_PATH = APP_SUPPORT_DIR / "recording.json"
HUD_STATE_PATH = APP_SUPPORT_DIR / "hud-state.json"
DESKTOP_BRIDGE_PATH = APP_SUPPORT_DIR / "desktop-bridge.json"
HOST_SERVICE_DISCOVERY_DIR = (
    Path.home() / "Library" / "Application Support" / "StickS3 Firmware Lab" / "Host Services"
    if platform.system() == "Darwin"
    else APP_SUPPORT_DIR / "Host Services"
)
HOST_SERVICE_DISCOVERY_PATH = HOST_SERVICE_DISCOVERY_DIR / "vibestick-bridge.json"
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
