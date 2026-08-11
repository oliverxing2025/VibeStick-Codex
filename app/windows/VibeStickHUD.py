from __future__ import annotations

import json
import os
from pathlib import Path
import time
import tkinter as tk


def state_path() -> Path:
    root = os.environ.get("LOCALAPPDATA", "").strip()
    base = Path(root) if root else Path.home() / "AppData" / "Local"
    return base / "VibeStick" / "hud-state.json"


class VibeStickHUD:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg="#111318")
        self.root.wm_attributes("-alpha", 0.94)
        self.canvas = tk.Canvas(
            self.root, width=290, height=72, bg="#111318",
            highlightthickness=1, highlightbackground="#343943",
        )
        self.canvas.pack()
        self.bars = [
            self.canvas.create_rectangle(0, 0, 0, 0, fill="#f4f5f7", outline="")
            for _ in range(5)
        ]
        self.text = self.canvas.create_text(
            188, 36, text="", fill="#ffffff", font=("Segoe UI", 15, "normal"),
        )
        self.frame = 0
        self.visible_signature = ""
        self.root.after(120, self.poll)

    def poll(self) -> None:
        payload = self.read_state()
        active = bool(payload and payload.get("active"))
        expires = payload.get("expires_at_epoch") if payload else None
        if expires is not None and time.time() >= float(expires):
            active = False
        label = str(payload.get("text") or "").strip() if payload else ""
        if active and label:
            self.show(label, str(payload.get("status") or ""))
        else:
            self.hide()
        self.root.after(120, self.poll)

    def read_state(self) -> dict[str, object] | None:
        try:
            data = json.loads(state_path().read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def show(self, label: str, status: str) -> None:
        signature = f"{status}:{label}"
        if signature != self.visible_signature:
            self.visible_signature = signature
            self.canvas.itemconfigure(self.text, text=label)
        self.frame += 1
        base_heights = (14, 25, 36, 25, 14)
        for index, item in enumerate(self.bars):
            phase = (self.frame + index * 2) % 12
            scale = 0.55 + (phase if phase <= 6 else 12 - phase) / 12
            height = base_heights[index] * scale
            x = 34 + index * 13
            self.canvas.coords(item, x, 36 - height / 2, x + 6, 36 + height / 2)
        width = 290
        height = 72
        x = max(0, (self.root.winfo_screenwidth() - width) // 2)
        y = max(0, self.root.winfo_screenheight() - height - 72)
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.deiconify()

    def hide(self) -> None:
        self.visible_signature = ""
        self.root.withdraw()

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    VibeStickHUD().run()
