import os
import unittest
from unittest import mock

from vibe_stick.audio.recorder import RecordingSession
from vibe_stick.server import app


class ServerSecurityTests(unittest.TestCase):
    def test_loopback_host_does_not_require_token(self) -> None:
        self.assertFalse(app._host_requires_token("127.0.0.1"))
        self.assertFalse(app._host_requires_token("localhost"))
        self.assertFalse(app._host_requires_token("::1"))

    def test_non_loopback_host_requires_token(self) -> None:
        self.assertTrue(app._host_requires_token("0.0.0.0"))
        self.assertTrue(app._host_requires_token(""))
        self.assertTrue(app._host_requires_token("192.168.1.10"))

    def test_placeholder_token_is_treated_as_missing(self) -> None:
        with mock.patch.dict(os.environ, {"VIBE_STICK_BRIDGE_TOKEN": "change-this-shared-token"}):
            self.assertEqual(app._bridge_token(), "")

    def test_real_token_is_used(self) -> None:
        with mock.patch.dict(os.environ, {"VIBE_STICK_BRIDGE_TOKEN": "abc123-secret"}):
            self.assertEqual(app._bridge_token(), "abc123-secret")

    def test_state_and_mutating_endpoints_require_token(self) -> None:
        protected = app._protected_paths()
        self.assertIn("/state", protected)
        self.assertIn("/event", protected)
        self.assertIn("/recording/audio", protected)
        self.assertNotIn("/health", protected)

    def test_recording_transport_omits_transcript_and_local_path(self) -> None:
        session = RecordingSession(
            session_id="session-1",
            transcript="private spoken text",
            audio_file="/Users/example/Library/Application Support/VibeStick/Recordings/private.wav",
        )

        payload = app._recording_transport_payload(session)

        self.assertEqual(payload["session_id"], "session-1")
        self.assertEqual(payload["transcript"], "")
        self.assertEqual(payload["audio_file"], "")
        self.assertEqual(session.transcript, "private spoken text")


if __name__ == "__main__":
    unittest.main()
