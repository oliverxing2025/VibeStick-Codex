import unittest
from datetime import datetime, timezone

from vibe_stick.codex.local_observer import LocalCodexObservation, _quota_from_payload
from vibe_stick.codex.quota import QuotaSnapshot
from vibe_stick.protocol.state import AgentStatus
from vibe_stick.providers.codex import observation_from_local_codex


class CodexProviderTests(unittest.TestCase):
    def test_weekly_reset_timestamp_maps_to_rounded_up_days(self) -> None:
        now = datetime(2026, 7, 27, 0, 0, tzinfo=timezone.utc)
        payload = {
            "type": "token_count",
            "rate_limits": {
                "secondary": {
                    "used_percent": 17,
                    "window_minutes": 10080,
                    "resets_at": now.timestamp() + 6 * 86400 + 1,
                }
            },
        }

        quota = _quota_from_payload(payload, now, now)

        self.assertIsNotNone(quota)
        self.assertEqual(quota.quota_7d_remaining, 83)
        self.assertEqual(quota.quota_7d_reset_days, 7)

    def test_codex_local_observation_maps_to_provider_observation(self) -> None:
        timestamp = datetime(2026, 6, 28, 9, 41, tzinfo=timezone.utc)
        observation = observation_from_local_codex(
            LocalCodexObservation(
                status=AgentStatus.DONE,
                project="VibeStick",
                quota=QuotaSnapshot(
                    66,
                    96,
                    "09:40",
                    False,
                    quota_7d_reset_days=5,
                ),
                quota_found=True,
                alert_type="DONE",
                alert_message="Codex task completed",
                alert_timestamp=timestamp,
                latest_event_timestamp=timestamp,
                codex_online=True,
                funds_balance="12.50",
                today_spend="1.25",
                today_tokens=5800000,
            )
        )

        self.assertEqual(observation.provider_id, "codex")
        self.assertEqual(observation.display_name, "Codex")
        self.assertEqual(observation.status, AgentStatus.DONE)
        self.assertEqual(observation.quota_5h_remaining, 66)
        self.assertEqual(observation.quota_7d_remaining, 96)
        self.assertEqual(observation.quota_7d_reset_days, 5)
        self.assertEqual(observation.alert_type, "DONE")
        self.assertEqual(observation.alert_event_id, f"evt_{timestamp.astimezone().strftime('%Y%m%d_%H%M%S')}_done")
        self.assertEqual(observation.latest_event_timestamp, timestamp)
        self.assertEqual(observation.funds_balance, "12.50")
        self.assertEqual(observation.today_spend, "1.25")
        self.assertEqual(observation.today_tokens, 5800000)

    def test_missing_codex_quota_maps_to_unknown_bars(self) -> None:
        observation = observation_from_local_codex(
            LocalCodexObservation(
                status=AgentStatus.IDLE,
                project="VibeStick",
                quota=None,
                quota_found=False,
                codex_online=True,
            )
        )

        self.assertIsNone(observation.quota_5h_remaining)
        self.assertIsNone(observation.quota_7d_remaining)
        self.assertEqual(observation.alert_type, "NONE")


if __name__ == "__main__":
    unittest.main()
