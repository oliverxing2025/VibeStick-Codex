import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from vibe_stick.server import app


class VoiceSettingsTests(unittest.TestCase):
    def test_saves_private_settings_and_applies_them_immediately(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text("VIBE_STICK_BRIDGE_TOKEN=unchanged\n", encoding="utf-8")
            form = {
                "profile": ["siliconflow"],
                "base_url": [""],
                "model": [""],
                "language": ["zh"],
                "api_key": ["test-key-123456"],
            }
            with mock.patch.dict(
                os.environ,
                {"VIBE_STICK_CONFIG_PATH": str(env_path)},
                clear=False,
            ):
                app._save_voice_settings(form)
                self.assertEqual(os.environ["VIBE_STICK_ASR_API_KEY"],
                                 "test-key-123456")

            saved = env_path.read_text(encoding="utf-8")
            self.assertIn("VIBE_STICK_BRIDGE_TOKEN=unchanged", saved)
            self.assertIn("VIBE_STICK_ASR_PROVIDER=openai-compatible", saved)
            self.assertIn("VIBE_STICK_ASR_BASE_URL=https://api.siliconflow.cn/v1", saved)
            self.assertIn("VIBE_STICK_ASR_API_KEY=test-key-123456", saved)
            self.assertEqual(env_path.stat().st_mode & 0o777, 0o600)

    def test_blank_key_preserves_existing_key_and_page_never_echoes_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text(
                "VIBE_STICK_ASR_PROVIDER=groq\n"
                "VIBE_STICK_ASR_BASE_URL=https://api.groq.com/openai/v1\n"
                "VIBE_STICK_ASR_API_KEY=existing-secret-key\n"
                "VIBE_STICK_ASR_MODEL=whisper-large-v3-turbo\n"
                "VIBE_STICK_ASR_LANGUAGE=zh\n",
                encoding="utf-8",
            )
            form = {
                "profile": ["groq"],
                "base_url": ["https://api.groq.com/openai/v1"],
                "model": ["whisper-large-v3-turbo"],
                "language": ["zh"],
                "api_key": [""],
            }
            with mock.patch.dict(
                os.environ,
                {
                    "VIBE_STICK_CONFIG_PATH": str(env_path),
                    "VIBE_STICK_BRIDGE_TOKEN": "device-pairing-token-1234",
                },
                clear=False,
            ):
                app._save_voice_settings(form)
                page = app._voice_settings_html("csrf-token")

            self.assertIn("VIBE_STICK_ASR_API_KEY=existing-secret-key",
                          env_path.read_text(encoding="utf-8"))
            self.assertNotIn("existing-secret-key", page)
            self.assertIn("device-pairing-token-1234", page)
            self.assertIn("已配置", page)

    def test_rejects_plain_http_or_unsafe_api_key(self) -> None:
        form = {
            "profile": ["custom"],
            "base_url": ["http://example.com/v1"],
            "model": ["model-name"],
            "language": ["zh"],
            "api_key": ["valid-key-123"],
        }
        with self.assertRaises(ValueError):
            app._save_voice_settings(form)
        form["base_url"] = ["https://example.com/v1"]
        form["api_key"] = ["bad key; command"]
        with self.assertRaises(ValueError):
            app._save_voice_settings(form)


if __name__ == "__main__":
    unittest.main()
