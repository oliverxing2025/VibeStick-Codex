import unittest

from vibe_stick.protocol.state import state_from_dict


class ProtocolStateTests(unittest.TestCase):
    def test_bridge_state_never_serializes_remote_battery(self) -> None:
        state = state_from_dict(
            {
                "wifi": True,
                "battery": 82,
                "codex": {"status": "RUNNING", "project": "VibeStick"},
                "alert": {"type": "NONE"},
            }
        )

        self.assertIsNone(state.to_jsonable()["battery"])

    def test_legacy_codex_block_populates_generic_provider(self) -> None:
        state = state_from_dict(
            {
                "codex": {
                    "status": "RUNNING",
                    "project": "VibeStick",
                    "quota_5h_remaining": 66,
                    "quota_7d_remaining": 96,
                    "quota_updated_at": "09:38",
                    "funds_balance": "9.20",
                    "today_spend": None,
                    "today_tokens": 5800000,
                }
            }
        )

        payload = state.to_jsonable()
        self.assertEqual(payload["active_provider"], "codex")
        self.assertEqual(payload["provider"]["id"], "codex")
        self.assertEqual(payload["provider"]["status"], "RUNNING")
        self.assertEqual(payload["provider"]["quota_5h_remaining"], 66)
        self.assertEqual(payload["codex"]["status"], "RUNNING")
        self.assertEqual(payload["codex"]["funds_balance"], "9.20")
        self.assertIsNone(payload["codex"]["today_spend"])
        self.assertEqual(payload["provider"]["today_tokens"], 5800000)

    def test_non_codex_saved_provider_is_normalized_to_codex(self) -> None:
        state = state_from_dict(
            {
                "active_provider": "unsupported",
                "provider": {"id": "unsupported", "status": "ERROR"},
                "codex": {"status": "IDLE", "project": "VibeStick"},
            }
        )

        payload = state.to_jsonable()

        self.assertEqual(payload["active_provider"], "codex")
        self.assertEqual(payload["provider"]["id"], "codex")
        self.assertEqual(payload["provider"]["status"], "IDLE")


if __name__ == "__main__":
    unittest.main()
