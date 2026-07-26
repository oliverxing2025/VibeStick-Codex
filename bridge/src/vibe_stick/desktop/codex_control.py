from __future__ import annotations

import platform
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class ControlResult:
    success: bool
    message: str


class CodexDesktopController:
    """Small, explicit control surface for the Codex desktop app on macOS."""

    bundle_id = "com.openai.codex"

    def open_or_focus(self) -> ControlResult:
        if platform.system() != "Darwin":
            return ControlResult(False, "Codex desktop control is only available on macOS")
        return self._run(["open", "-b", self.bundle_id], "Codex opened")

    def new_thread(self) -> ControlResult:
        return self._shortcut('keystroke "n" using command down', "New Codex chat requested")

    def next_thread(self) -> ControlResult:
        return self._shortcut(
            'keystroke "]" using {command down, shift down}',
            "Next Codex chat requested",
        )

    def previous_thread(self) -> ControlResult:
        return self._shortcut(
            'keystroke "[" using {command down, shift down}',
            "Previous Codex chat requested",
        )

    def send(self) -> ControlResult:
        return self._shortcut("key code 36", "Codex message sent")

    def clear_input(self) -> ControlResult:
        return self._shortcut(
            'keystroke "a" using command down\n'
            "delay 0.05\n"
            "key code 51",
            "Codex input cleared",
        )

    def approve(self) -> ControlResult:
        return self._shortcut("key code 36", "Codex approval accepted")

    def decline(self) -> ControlResult:
        return self._shortcut("key code 53", "Codex approval declined")

    def _shortcut(self, key_action: str, success_message: str) -> ControlResult:
        if platform.system() != "Darwin":
            return ControlResult(False, "Codex desktop control is only available on macOS")
        system_events_actions = "\n".join(f"    {line}" for line in key_action.splitlines())
        script = (
            f'tell application id "{self.bundle_id}" to activate\n'
            "delay 0.18\n"
            'tell application "System Events"\n'
            f"{system_events_actions}\n"
            "end tell"
        )
        return self._run(["osascript", "-e", script], success_message)

    @staticmethod
    def _run(args: list[str], success_message: str) -> ControlResult:
        try:
            result = subprocess.run(
                args,
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return ControlResult(False, f"Codex desktop control failed: {exc}")
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "Codex desktop control failed").strip()
            return ControlResult(False, message)
        return ControlResult(True, success_message)
