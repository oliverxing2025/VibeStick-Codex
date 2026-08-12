import json
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
    _latest_quota_and_funds,
    _monthly_api_cost_usd,
    _monthly_token_total,
    observe_codex,
    _quota_period_start,
    _quota_from_payload,
    _session_is_running,
    _session_is_waiting,
    _thread_id_from_session,
    _weekly_usage_from_payload,
    _token_total_since,
    waiting_thread_ids,
)
from vibe_stick.codex.quota import QuotaSnapshot
from vibe_stick.protocol.state import AgentStatus
from vibe_stick.providers.codex import observation_from_local_codex


def _token_event(timestamp: datetime, total_tokens: int) -> dict[str, object]:
    return {
        "timestamp": timestamp.isoformat(),
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {
                "total_token_usage": {
                    "total_tokens": total_tokens,
                }
            },
        },
    }


def _priced_token_event(
    timestamp: datetime,
    input_tokens: int,
    cached_input_tokens: int,
    output_tokens: int,
) -> dict[str, object]:
    return {
        "timestamp": timestamp.isoformat(),
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {
                "total_token_usage": {
                    "input_tokens": input_tokens,
                    "cached_input_tokens": cached_input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": input_tokens + output_tokens,
                }
            },
        },
    }


def _model_event(timestamp: datetime, model: str) -> dict[str, object]:
    return {
        "timestamp": timestamp.isoformat(),
        "type": "turn_context",
        "payload": {"model": model},
    }


def _quota_event(
    timestamp: datetime,
    used_percent: int,
    limit_id: str,
) -> dict[str, object]:
    return {
        "timestamp": timestamp.isoformat(),
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "rate_limits": {
                "limit_id": limit_id,
                "primary": {
                    "used_percent": used_percent,
                    "window_minutes": 10080,
                    "resets_at": timestamp.timestamp() + 7 * 86400,
                },
            },
        },
    }


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

    def test_period_tokens_subtract_session_baseline(self) -> None:
        period_start = datetime(2026, 7, 29, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sessions = root / "sessions"
            archived = root / "archived_sessions"
            sessions.mkdir()
            archived.mkdir()
            cross_midnight = sessions / "cross-midnight.jsonl"
            today_only = archived / "today-only.jsonl"
            cross_midnight.write_text(
                "\n".join(
                    json.dumps(event)
                    for event in (
                        _token_event(period_start - timedelta(minutes=1), 1000),
                        _token_event(period_start + timedelta(hours=1), 1250),
                        _token_event(period_start + timedelta(hours=2), 1600),
                    )
                )
                + "\n"
            )
            today_only.write_text(
                json.dumps(
                    _token_event(period_start + timedelta(hours=3), 75)
                )
                + "\n"
            )
            fresh_timestamp = (period_start + timedelta(hours=4)).timestamp()
            os.utime(cross_midnight, (fresh_timestamp, fresh_timestamp))
            os.utime(today_only, (fresh_timestamp, fresh_timestamp))

            with (
                mock.patch(
                    "vibe_stick.codex.local_observer.SESSIONS_DIR",
                    sessions,
                ),
                mock.patch(
                    "vibe_stick.codex.local_observer.ARCHIVED_SESSIONS_DIR",
                    archived,
                ),
                mock.patch(
                    "vibe_stick.codex.local_observer._TOKEN_CACHE_PERIOD_START",
                    None,
                ),
                mock.patch(
                    "vibe_stick.codex.local_observer._TOKEN_FILE_CACHE",
                    {},
                ),
            ):
                self.assertEqual(_token_total_since(period_start), 675)

    def test_period_tokens_restart_at_new_quota_cycle(self) -> None:
        old_start = datetime(2026, 7, 22, tzinfo=timezone.utc)
        new_start = datetime(2026, 7, 29, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sessions = root / "sessions"
            archived = root / "archived_sessions"
            sessions.mkdir()
            archived.mkdir()
            path = sessions / "cycle.jsonl"
            path.write_text(
                "\n".join(
                    json.dumps(event)
                    for event in (
                        _token_event(old_start + timedelta(hours=1), 1000),
                        _token_event(new_start - timedelta(minutes=1), 1800),
                        _token_event(new_start + timedelta(hours=1), 1950),
                    )
                )
                + "\n"
            )
            fresh_timestamp = (new_start + timedelta(hours=2)).timestamp()
            os.utime(path, (fresh_timestamp, fresh_timestamp))

            with (
                mock.patch(
                    "vibe_stick.codex.local_observer.SESSIONS_DIR",
                    sessions,
                ),
                mock.patch(
                    "vibe_stick.codex.local_observer.ARCHIVED_SESSIONS_DIR",
                    archived,
                ),
                mock.patch(
                    "vibe_stick.codex.local_observer._TOKEN_CACHE_PERIOD_START",
                    None,
                ),
                mock.patch(
                    "vibe_stick.codex.local_observer._TOKEN_FILE_CACHE",
                    {},
                ),
            ):
                self.assertEqual(_token_total_since(old_start), 1950)
                self.assertEqual(_token_total_since(new_start), 150)

    def test_monthly_api_cost_uses_model_and_token_type_prices(self) -> None:
        month_start = datetime(2026, 7, 1, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sessions = root / "sessions"
            archived = root / "archived_sessions"
            sessions.mkdir()
            archived.mkdir()
            path = sessions / "cost.jsonl"
            initial_events = (
                _model_event(month_start - timedelta(minutes=2), "gpt-5.6-sol"),
                _priced_token_event(
                    month_start - timedelta(minutes=1),
                    1000,
                    400,
                    100,
                ),
                _priced_token_event(
                    month_start + timedelta(hours=1),
                    2_001_000,
                    1_000_400,
                    100_100,
                ),
            )
            path.write_text(
                "\n".join(json.dumps(event) for event in initial_events) + "\n"
            )
            fresh_timestamp = (month_start + timedelta(hours=2)).timestamp()
            os.utime(path, (fresh_timestamp, fresh_timestamp))

            with (
                mock.patch(
                    "vibe_stick.codex.local_observer.SESSIONS_DIR",
                    sessions,
                ),
                mock.patch(
                    "vibe_stick.codex.local_observer.ARCHIVED_SESSIONS_DIR",
                    archived,
                ),
                mock.patch(
                    "vibe_stick.codex.local_observer._MONTHLY_COST_PERIOD_START",
                    None,
                ),
                mock.patch(
                    "vibe_stick.codex.local_observer._MONTHLY_COST_FILE_CACHE",
                    {},
                ),
            ):
                self.assertEqual(_monthly_api_cost_usd(month_start), 8.5)
                self.assertEqual(_monthly_token_total(month_start), 2_100_000)
                with path.open("a") as handle:
                    for event in (
                        _model_event(
                            month_start + timedelta(hours=2),
                            "gpt-5.3-codex",
                        ),
                        _priced_token_event(
                            month_start + timedelta(hours=3),
                            3_001_000,
                            1_000_400,
                            100_100,
                        ),
                    ):
                        handle.write(json.dumps(event) + "\n")
                self.assertEqual(_monthly_api_cost_usd(month_start), 10.25)
                self.assertEqual(_monthly_token_total(month_start), 3_100_000)

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

    def test_unanswered_nested_js_escalation_counts_as_waiting(self) -> None:
        now = datetime(2026, 8, 12, 1, 0, tzinfo=timezone.utc)
        events = [
            {
                "timestamp": (now - timedelta(seconds=3)).isoformat(),
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call",
                    "call_id": "call_nested_pending",
                    "name": "functions.exec",
                    "input": (
                        'const result = await tools.exec_command({'
                        'cmd: "open app", sandbox_permissions: '
                        '"require_escalated", justification: "Allow?"});'
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

    def test_pending_human_approval_becomes_primary_waiting_status(self) -> None:
        now = datetime.now(timezone.utc)
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

        with (
            mock.patch(
                "vibe_stick.codex.local_observer._session_files",
                return_value=[Path("/tmp/pending-approval.jsonl")],
            ),
            mock.patch(
                "vibe_stick.codex.local_observer._tail_json_events",
                return_value=events,
            ),
            mock.patch(
                "vibe_stick.codex.local_observer._codex_process_running",
                return_value=True,
            ),
            mock.patch(
                "vibe_stick.codex.local_observer._latest_archived_quota_and_funds",
                return_value=(None, None),
            ),
            mock.patch(
                "vibe_stick.codex.local_observer._daily_weekly_usage_samples",
                return_value=[],
            ),
            mock.patch(
                "vibe_stick.codex.local_observer._monthly_api_cost_usd",
                return_value=None,
            ),
            mock.patch(
                "vibe_stick.codex.local_observer._monthly_token_total",
                return_value=None,
            ),
        ):
            observation = observe_codex(Path("/tmp/project"))

        self.assertEqual(observation.waiting_tasks, 1)
        self.assertEqual(observation.running_tasks, 0)
        self.assertEqual(observation.status, AgentStatus.APPROVAL)

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
        self.assertEqual(quota.quota_7d_reset_minutes, 8641)
        self.assertEqual(
            _quota_period_start(quota),
            now + timedelta(seconds=1) - timedelta(days=1),
        )

    def test_five_hour_reset_timestamp_maps_to_rounded_up_minutes(self) -> None:
        now = datetime(2026, 7, 30, 1, 0, tzinfo=timezone.utc)
        payload = {
            "type": "token_count",
            "rate_limits": {
                "primary": {
                    "used_percent": 46,
                    "window_minutes": 300,
                    "resets_at": now.timestamp() + 3 * 3600 + 23 * 60 + 1,
                }
            },
        }

        quota = _quota_from_payload(payload, now, now)

        self.assertIsNotNone(quota)
        self.assertEqual(quota.quota_5h_remaining, 54)
        self.assertEqual(quota.quota_5h_reset_minutes, 204)

    def test_special_model_quota_does_not_replace_main_codex_quota(self) -> None:
        now = datetime(2026, 7, 29, tzinfo=timezone.utc)
        payload = {
            "type": "token_count",
            "rate_limits": {
                "limit_id": "codex_bengalfox",
                "limit_name": "GPT-5.3-Codex-Spark",
                "primary": {
                    "used_percent": 0,
                    "window_minutes": 10080,
                    "resets_at": now.timestamp() + 7 * 86400,
                },
            },
        }

        self.assertIsNone(_quota_from_payload(payload, now, now))
        self.assertIsNone(_weekly_usage_from_payload(payload))

    def test_main_codex_quota_accepts_explicit_or_legacy_limit_id(self) -> None:
        now = datetime(2026, 7, 29, tzinfo=timezone.utc)
        for limit_id in ("codex", None):
            rate_limits = {
                "primary": {
                    "used_percent": 36,
                    "window_minutes": 10080,
                    "resets_at": now.timestamp() + 7 * 86400,
                },
            }
            if limit_id is not None:
                rate_limits["limit_id"] = limit_id
            payload = {"type": "token_count", "rate_limits": rate_limits}

            quota = _quota_from_payload(payload, now, now)

            self.assertIsNotNone(quota)
            self.assertEqual(quota.quota_7d_remaining, 64)

    def test_latest_quota_can_come_from_recent_archived_session(self) -> None:
        now = datetime(2026, 7, 29, 10, 0, tzinfo=timezone.utc)
        active_path = Path("/tmp/active.jsonl")
        archived_path = Path("/tmp/archived.jsonl")
        events = {
            active_path: [
                _quota_event(
                    now - timedelta(days=1),
                    12,
                    "codex",
                )
            ],
            archived_path: [
                _quota_event(
                    now - timedelta(minutes=5),
                    37,
                    "codex",
                ),
                _quota_event(
                    now - timedelta(minutes=1),
                    0,
                    "codex_bengalfox",
                ),
            ],
        }

        with mock.patch(
            "vibe_stick.codex.local_observer._tail_json_events",
            side_effect=lambda path: events[path],
        ):
            active_quota, _ = _latest_quota_and_funds([active_path], now)
            archived_quota, _ = _latest_quota_and_funds([archived_path], now)

        self.assertIsNotNone(active_quota)
        self.assertIsNotNone(archived_quota)
        self.assertGreater(archived_quota[0], active_quota[0])
        self.assertEqual(archived_quota[1].quota_7d_remaining, 63)

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
                    quota_5h_reset_minutes=204,
                    quota_7d_reset_minutes=7250,
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
                month_cost_usd=12.75,
                month_tokens=123_456_789,
                today_used_percent=16,
                running_tasks=2,
                waiting_tasks=3,
            )
        )

        self.assertEqual(observation.provider_id, "codex")
        self.assertEqual(observation.display_name, "Codex")
        self.assertEqual(observation.status, AgentStatus.DONE)
        self.assertEqual(observation.quota_5h_remaining, 66)
        self.assertEqual(observation.quota_5h_reset_minutes, 204)
        self.assertEqual(observation.quota_7d_remaining, 96)
        self.assertEqual(observation.quota_7d_reset_days, 5)
        self.assertEqual(observation.quota_7d_reset_minutes, 7250)
        self.assertEqual(observation.alert_type, "DONE")
        self.assertEqual(observation.alert_event_id, f"evt_{timestamp.astimezone().strftime('%Y%m%d_%H%M%S')}_done")
        self.assertEqual(observation.latest_event_timestamp, timestamp)
        self.assertEqual(observation.funds_balance, "12.50")
        self.assertEqual(observation.today_spend, "1.25")
        self.assertEqual(observation.today_tokens, 5800000)
        self.assertEqual(observation.month_cost_usd, 12.75)
        self.assertEqual(observation.month_tokens, 123_456_789)
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
