import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from vibe_stick.audio import recorder
from vibe_stick.audio.recorder import RecordingController, RecordingSession


class RecordingPrivacyTests(unittest.TestCase):
    def test_default_cleanup_removes_audio_and_redacts_persisted_transcript(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            recordings_dir = root / "Recordings"
            recordings_dir.mkdir()
            audio_path = recordings_dir / "session.wav"
            audio_path.write_bytes(b"private audio")
            state_path = root / "recording.json"
            controller = RecordingController(state_path)
            controller.session = RecordingSession(
                session_id="session",
                status="pasted",
                transcript="private spoken text",
                audio_file=str(audio_path),
                command={"action": "add", "symbol": "hk00700"},
            )

            with (
                mock.patch.object(recorder, "RECORDINGS_DIR", recordings_dir),
                mock.patch.dict(os.environ, {}, clear=True),
            ):
                controller._save_stop_result()

            persisted = json.loads(state_path.read_text())
            self.assertFalse(audio_path.exists())
            self.assertEqual(controller.session.audio_file, "")
            self.assertEqual(persisted["transcript"], "")
            self.assertIsNone(persisted["command"])
            if os.name == "posix":
                self.assertEqual(state_path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(root.stat().st_mode & 0o777, 0o700)

    def test_explicit_retention_keeps_audio_private(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            recordings_dir = root / "Recordings"
            recordings_dir.mkdir()
            audio_path = recordings_dir / "session.wav"
            audio_path.write_bytes(b"private audio")
            audio_path.chmod(0o644)
            controller = RecordingController(root / "recording.json")
            controller.session = RecordingSession(
                session_id="session",
                status="transcribed",
                transcript="private spoken text",
                audio_file=str(audio_path),
            )

            with (
                mock.patch.object(recorder, "RECORDINGS_DIR", recordings_dir),
                mock.patch.dict(
                    os.environ,
                    {"VIBE_STICK_RETAIN_RECORDINGS": "1"},
                    clear=True,
                ),
            ):
                controller._save_stop_result()

            self.assertTrue(audio_path.exists())
            if os.name == "posix":
                self.assertEqual(audio_path.stat().st_mode & 0o777, 0o600)
            persisted = json.loads((root / "recording.json").read_text())
            self.assertEqual(persisted["transcript"], "")


if __name__ == "__main__":
    unittest.main()
