import json
import os
from pathlib import Path
import tempfile
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

    def test_lan_discovery_response_is_authenticated(self) -> None:
        with mock.patch.dict(os.environ, {"VIBE_STICK_BRIDGE_TOKEN": "abc123-secret"}):
            response = app._discovery_response(b"VIBESTICK_DISCOVER_V1 12ab34cd", 8765)
        self.assertIsNotNone(response)
        payload = json.loads(response)
        self.assertEqual(payload["bridge_name"], app.BRIDGE_NAME)
        self.assertEqual(payload["port"], 8765)
        self.assertEqual(payload["nonce"], "12ab34cd")
        expected = app.hmac.new(
            b"abc123-secret",
            b"VIBESTICK_DISCOVERY_V1:12ab34cd:8765",
            app.hashlib.sha256,
        ).hexdigest()
        self.assertEqual(payload["proof"], expected)

    def test_lan_discovery_rejects_invalid_or_unauthenticated_requests(self) -> None:
        with mock.patch.dict(os.environ, {"VIBE_STICK_BRIDGE_TOKEN": ""}, clear=False):
            self.assertIsNone(app._discovery_response(b"VIBESTICK_DISCOVER_V1 12ab34cd", 8765))
        with mock.patch.dict(os.environ, {"VIBE_STICK_BRIDGE_TOKEN": "abc123-secret"}):
            self.assertIsNone(app._discovery_response(b"wrong 12ab34cd", 8765))
            self.assertIsNone(app._discovery_response(b"VIBESTICK_DISCOVER_V1 not-hex!", 8765))

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

    def test_desktop_discovery_publishes_generic_host_service_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            desktop_path = root / "vibestick" / "desktop-bridge.json"
            service_path = root / "firmware-lab" / "vibestick-bridge.json"
            with (
                mock.patch.object(app, "DESKTOP_BRIDGE_PATH", desktop_path),
                mock.patch.object(app, "HOST_SERVICE_DISCOVERY_PATH", service_path),
            ):
                app._write_desktop_discovery(43123, "instance-a")

            desktop = json.loads(desktop_path.read_text(encoding="utf-8"))
            service = json.loads(service_path.read_text(encoding="utf-8"))
            self.assertEqual(desktop["instance_id"], "instance-a")
            self.assertEqual(service["service_identity"], app.BRIDGE_NAME)
            self.assertEqual(service["base_url"], "http://127.0.0.1:43123")
            self.assertEqual(service["legacy_ports"], [8765])
            self.assertEqual(service_path.stat().st_mode & 0o777, 0o600)

    def test_discovery_cleanup_never_removes_a_newer_instance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            desktop_path = root / "desktop-bridge.json"
            service_path = root / "vibestick-bridge.json"
            desktop_path.write_text('{"instance_id":"newer"}', encoding="utf-8")
            service_path.write_text('{"instance_id":"newer"}', encoding="utf-8")
            with (
                mock.patch.object(app, "DESKTOP_BRIDGE_PATH", desktop_path),
                mock.patch.object(app, "HOST_SERVICE_DISCOVERY_PATH", service_path),
            ):
                app._remove_desktop_discovery("older")

            self.assertTrue(desktop_path.exists())
            self.assertTrue(service_path.exists())


if __name__ == "__main__":
    unittest.main()
