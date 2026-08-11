from __future__ import annotations

import platform
import subprocess
import time
from dataclasses import dataclass


@dataclass
class PasteResult:
    success: bool
    message: str


class MacPasteInjector:
    def paste(self, text: str, press_enter: bool = False) -> PasteResult:
        text = text.strip()
        if not text:
            return PasteResult(False, "No text to paste")
        if platform.system() not in {"Darwin", "Windows"}:
            return PasteResult(False, "Automatic paste is unavailable on this platform")

        previous_text = self._read_clipboard()
        set_result = self._set_clipboard(text)
        if not set_result.success:
            return set_result

        if platform.system() == "Windows":
            keys = "^v{ENTER}" if press_enter else "^v"
            script = (
                "Add-Type -AssemblyName System.Windows.Forms; "
                f"[System.Windows.Forms.SendKeys]::SendWait('{keys}')"
            )
            args = ["powershell.exe", "-NoProfile", "-NonInteractive",
                    "-Command", script]
        else:
            script_lines = [
                'tell application "System Events" to keystroke "v" using command down',
            ]
            if press_enter:
                script_lines.extend([
                    "delay 0.12",
                    'tell application "System Events" to key code 36',
                ])
            args = ["osascript"]
            for line in script_lines:
                args.extend(["-e", line])
        try:
            result = subprocess.run(args, check=False, capture_output=True,
                                    text=True, timeout=5)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return PasteResult(False, f"Paste failed: {exc}")
        time.sleep(0.2)
        if previous_text is not None:
            self._set_clipboard(previous_text)

        if result.returncode != 0:
            message = (result.stderr or result.stdout or "macOS paste failed").strip()
            return PasteResult(False, message)
        return PasteResult(True, "Pasted into the focused app")

    def _read_clipboard(self) -> str | None:
        command = (
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
             "Get-Clipboard -Raw"]
            if platform.system() == "Windows" else ["pbpaste"]
        )
        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=2,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return None
        return result.stdout

    def _set_clipboard(self, text: str) -> PasteResult:
        command = (
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
             "$input | Set-Clipboard"]
            if platform.system() == "Windows" else ["pbcopy"]
        )
        try:
            result = subprocess.run(
                command,
                input=text,
                check=False,
                capture_output=True,
                text=True,
                timeout=2,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return PasteResult(False, f"Clipboard write failed: {exc}")
        if result.returncode != 0:
            message = (result.stderr or "Clipboard write failed").strip()
            return PasteResult(False, message)
        return PasteResult(True, "Clipboard updated")
