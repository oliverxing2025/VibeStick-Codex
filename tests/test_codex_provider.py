import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from vibe_stick.codex.local_observer import (
    LocalCodexObservation,
    _daily_usage_session_files,
    _daily_used_percent,
    _daily_used_percent_from_samples,
    _quota_from_payload,
    _session_is_running,
    _session_is_waiting,
    _thread_id_from_session,
    waiting_thread_ids,
)
from vibe_stick.codex.quota import QuotaSnapshot
from vibe_stick.protocol.state import AgentStatus
from vibe_stick.providers.codex import observation_from_local_codex


class CodexProviderTests(unittest.TestCase):
    def test_thread_id_comes_from_session_metadata_or_rollout_filename(self) -> None:
        metadata_id = "019fa1bd-7d3b-7913-a86b-5220bf6aa96f"
        events = [
            {
                "type": "session_meta",
                "payload": {"id": metadata_id},
            }
        ]

        self.assertEqual(
            _thread_id_from_session(Path("/tmp/rollout.jsonl"), events),
            metadata_id,
        )
        self.assertEqual(
            _thread_id_from_session(
                Path(f"/tmp/rollout-2026-07-27T00-00-00-{metadata_id}.jsonl"),
                [],
            ),
            metadata_id,
        )

    def test_waiting_thread_ids_returns_each_pending_thread_once(self) -> None:
        first_id = "019fa1bd-7d3b-7913-a86b-5220bf6aa96f"
        second_id = "019fa1bd-7d3b-7913-a86b-5220bf6aa970"
        paths = [
            Path(f"/tmp/rollout-{first_id}.jsonl"),
            Path(f"/tmp/rollout-{first_id}.jsonl"),
            Path(f"/tmp/rollout-{second_id}.jsonl"),
        ]
        waiting_event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": "event_msg",
            "payload": {"type": "waiting_approval"},
        }

        with mock.patch(
            "vibe_stick.codex.local_observer._session_files",
            return_value=paths,
        ), mock.patch(
            "vibe_stick.codex.local_observer._tail_json_events",
            return_value=[waiting_event],
        ):
            self.assertEqual(waiting_thread_ids(), [first_id, second_id])

    def test_daily_used_percent_is_delta_from_local_day_baseline(self) -> None:
        self.assertEqual(_daily_used_percent(26.0, 27.0, 42.0), 16)
        self.assertEqual(_daily_used_percent(None, 26.0, 42.0), 16)
        self.assertEqual(_daily_used_percent(42.0, 42.0, 40.0), 0)

    def test_daily_used_percent_accumulates_across_quota_reset(self) -> None:
        base = datetime(2026, 7, 28, tzinfo=timezone.utc)
        samples = [
            (base + timedelta(hours=1), 70.0, 1_785_654_184.0),
            (base + timedelta(hours=2), 73.0, 1_785_654_184.0),
            (base + timedelta(hours=3), 0.0, 1_785_813_841.0),
            (base + timedelta(hours=4), 2.0, 1_785_813_841.0),
        ]

        self.assertEqual(
            _daily_used_percent_from_samples(
                (70.0, 1_785_654_184.0),
                samples,
            ),
            5,
        )

    def test_daily_used_percent_ignores_old_parallel_snapshot_after_reset(self) -> None:
        base = datetime(2026, 7, 28, tzinfo=timezone.utc)
        old_reset = 1_785_654_184.0
        new_reset = 1_785_813_841.0
        samples = [
            (base + timedelta(hours=1), 73.0, old_reset),
            (base + timedelta(hours=2), 0.0, new_reset),
            (base + timedelta(hours=3), 73.0, old_reset),
            (base + timedelta(hours=4), 2.0, new_reset),
        ]

        self.assertEqual(
            _daily_used_percent_from_samples((70.0, old_reset), samples),
            5,
        )

    def test_daily_usage_files_include_live_and_archived_sessions(self) -> None:
        sample_start = datetime(2026, 7, 27, 18, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sessions = root / "sessions"
            archived = root / "archived_sessions"
            sessions.mkdir()
            archived.mkdir()
            live_path = sessions / "live.jsonl"
            archived_path = archived / "archived.jsonl"
            stale_path = archived / "stale.jsonl"
            for path in (live_path, archived_path, stale_path):
                path.write_text("{}\n")
            fresh_timestamp = sample_start.timestamp() + 60
            stale_timestamp = sample_start.timestamp() - 60
            os.utime(live_path, (fresh_timestamp, fresh_timestamp))
            os.utime(archived_path, (fresh_timestamp, fresh_timestamp))
            os.utime(stale_path, (stale_timestamp, stale_timestamp))

            with (
                mock.patch(
                    "vibe_stick.codex.local_observer.SESSIONS_DIR",
                    sessions,
                ),
                mock.patch(
                    "vibe_stick.codex.local_observer.ARCHIVED_SESSIONS_DIR",
                    archived,
                ),
            ):
                self.assertCountEqual(
                    _daily_usage_session_files(sample_start),
                    [live_path, archived_path],
                )

    def test_session_running_count_uses_task_lifecycle(self) -> None:
        now = datetime(2026, 7, 27, 1, 0, tzinfo=timezone.utc)
        started = {
            "timestamp": (now - timedelta(seconds=20)).isoformat(),
            "type": "event_msg",
            "payload": {"type": "task_started"},
        }
        tool_activity = {
            "timestamp": (now - timedelta(seconds=2)).isoformat(),
            "type": "response_item",
            "payload": {"type": "custom_tool_call"},
        }
        completed = {
            "timestamp": (now - timedelta(seconds=1)).isoformat(),
            "type": "event_msg",
            "payload": {"type": "task_complete"},
        }

        self.assertTrue(_session_is_running([started, tool_activity], now))
        self.assertFalse(
            _session_is_running([started, tool_activity, completed], now)
        )

    def test_started_long_running_session_survives_short_activity_window(self) -> None:
        now = datetime(2026, 7, 27, 1, 0, tzinfo=timezone.utc)
        events = [
            {
                "timestamp": (now - timedelta(minutes=10)).isoformat(),
                "type": "event_msg",
                "payload": {"type": "task_started"},
            }
        ]

        self.assertTrue(_session_is_running(events, now))

    def test_recent_session_without_lifecycle_in_tail_counts_as_running(self) -> None:
        now = datetime(2026, 7, 27, 1, 0, tzinfo=timezone.utc)
        events = [
            {
                "timestamp": (now - timedelta(seconds=3)).isoformat(),
                "type": "response_item",
                "payload": {"type": "custom_tool_call_output"},
            }
        ]

        self.assertTrue(_session_is_running(events, now))

    def test_latest_approval_event_counts_as_waiting(self) -> None:
        now = datetime(2026, 7, 27, 1, 0, tzinfo=timezone.utc)
        events = [
            {
                "timestamp": (now - timedelta(seconds=20)).isoformat(),
                "type": "event_msg",
                "payload": {"type": "task_started"},
            },
            {
                "timestamp": (now - timedelta(seconds=2)).isoformat(),
                "type": "event_msg",
                "payload": {"type": "waiting_approval"},
            },
        ]

        self.assertTrue(_session_is_waiting(events, now))

    def test_activity_after_approval_clears_waiting(self) -> None:
        now = datetime(2026, 7, 27, 1, 0, tzinfo=timezone.utc)
        events = [
            {
                "timestamp": (now - timedelta(seconds=3)).isoformat(),
                "type": "event_msg",
                "payload": {"type": "waiting_approval"},
            },
            {
                "timestamp": (now - timedelta(seconds=1)).isoformat(),
                "type": "response_item",
                "payload": {"type": "custom_tool_call_output"},
            },
        ]

        self.assertFalse(_session_is_waiting(events, now))

    def test_unanswered_escalated_tool_call_counts_as_waiting(self) -> None:
        now = datetime(2026, 7, 27, 1, 0, tzinfo=timezone.utc)
        events = [
            {
                "timestamp": (now - timedelta(seconds=3)).isoformat(),
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "call_id": "call_pending",
                    "name": "exec_command",
                    "arguments": (
                        '{"cmd":"open app","sandbox_permissions":'
                        '"require_escalated","justification":"Allow?"}'
                    ),
                },
            },
            {
                "timestamp": (now - timedelta(seconds=2)).isoformat(),
                "type": "event_msg",
                "payload": {"type": "token_count"},
            },
        ]

        self.assertTrue(_session_is_waiting(events, now))

    def test_tool_output_clears_escalated_waiting_count(self) -> None:
        now = datetime(2026, 7, 27, 1, 0, tzinfo=timezone.utc)
        events = [
            {
                "timestamp": (now - timedelta(seconds=3)).isoformat(),
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call",
                    "call_id": "call_approved",
                    "name": "exec",
                    "input": (
                        'await tools.exec_command({"cmd":"open app",'
                        '"sandbox_permissions":"require_escalated"})'
                    ),
                },
            },
            {
                "timestamp": (now - timedelta(seconds=1)).isoformat(),
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call_output",
                    "call_id": "call_approved",
                    "output": "completed",
                },
            },
        ]

        self.assertFalse(_session_is_waiting(events, now))

    def test_stalled_apply_patch_counts_as_waiting_for_file_approval(self) -> None:
        now = datetime(2026, 7, 27, 1, 0, tzinfo=timezone.utc)
        patch_call = {
            "timestamp": (now - timedelta(seconds=3)).isoformat(),
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call",
                "call_id": "call_patch",
                "name": "apply_patch",
                "input": "*** Begin Patch",
            },
        }

        self.assertTrue(_session_is_waiting([patch_call], now))

    def test_fast_or_completed_apply_patch_does_not_count_as_waiting(self) -> None:
        now = datetime(2026, 7, 27, 1, 0, tzinfo=timezone.utc)
        patch_call = {
            "timestamp": (now - timedelta(seconds=1)).isoformat(),
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call",
                "call_id": "call_patch",
                "name": "apply_patch",
            },
        }
        patch_end = {
            "timestamp": now.isoformat(),
            "type": "event_msg",
            "payload": {
                "type": "patch_apply_end",
                "call_id": "call_patch",
                "status": "completed",
            },
        }

        self.assertFalse(_session_is_waiting([patch_call], now))
        self.assertFalse(_session_is_waiting([patch_call, patch_end], now))

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
                today_used_percent=16,
                running_tasks=2,
                waiting_tasks=3,
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
        self.assertEqual(observation.today_used_percent, 16)
        self.assertEqual(observation.running_tasks, 2)
        self.assertEqual(observation.waiting_tasks, 3)

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
