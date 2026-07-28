import unittest
import threading
import json
import tempfile
from pathlib import Path
from unittest import mock

from vibe_stick.desktop.codex_control import ControlResult
from vibe_stick.protocol.state import AgentStatus
from vibe_stick.providers.base import ProviderObservation
from vibe_stick.server import app


class ServerCodexOnlyTests(unittest.TestCase):
    def test_side_short_sends_current_input(self) -> None:
        store = app.BridgeStateStore.__new__(app.BridgeStateStore)
        store._lock = threading.RLock()
        store._state = app.default_state()
        store._manual_status_until = 0.0
        store.codex_controller = mock.Mock()
        store.codex_controller.send.return_value = ControlResult(True, "Codex message sent")
        store._save_state_locked = mock.Mock()

        with mock.patch.object(app, "waiting_thread_ids", return_value=[]):
            store.update_from_event({"event": "side_short", "source": "sticks3"})

        store.codex_controller.send.assert_called_once_with()
        store.codex_controller.approve_all.assert_not_called()
        store.codex_controller.next_thread.assert_not_called()
        store.codex_controller.decline.assert_not_called()

    def test_side_short_approves_all_waiting_threads(self) -> None:
        store = app.BridgeStateStore.__new__(app.BridgeStateStore)
        store._lock = threading.RLock()
        store._state = app.default_state()
        store._manual_status_until = 0.0
        store.codex_controller = mock.Mock()
        store.codex_controller.approve_all.return_value = ControlResult(
            True,
            "Accepted 2 Codex approval requests",
        )
        store._save_state_locked = mock.Mock()
        thread_ids = [
            "019fa1bd-7d3b-7913-a86b-5220bf6aa96f",
            "019fa1bd-7d3b-7913-a86b-5220bf6aa970",
        ]

        with mock.patch.object(app, "waiting_thread_ids", return_value=thread_ids):
            store.update_from_event({"event": "side_short", "source": "sticks3"})

        store.codex_controller.approve_all.assert_called_once_with(thread_ids)
        store.codex_controller.send.assert_not_called()
        self.assertEqual(store._state.codex.status, AgentStatus.RUNNING)

    def test_side_double_clears_current_input(self) -> None:
        store = app.BridgeStateStore.__new__(app.BridgeStateStore)
        store._lock = threading.RLock()
        store._state = app.default_state()
        store._manual_status_until = 0.0
        store.codex_controller = mock.Mock()
        store.codex_controller.clear_input.return_value = ControlResult(True, "Codex input cleared")
        store._save_state_locked = mock.Mock()

        store.update_from_event({"event": "side_double", "source": "sticks3"})

        store.codex_controller.clear_input.assert_called_once_with()
        store.codex_controller.previous_thread.assert_not_called()
        store.codex_controller.decline.assert_not_called()

    def test_refresh_publishes_codex_as_the_only_active_provider(self) -> None:
        store = app.BridgeStateStore.__new__(app.BridgeStateStore)
        store._project_root = mock.Mock()
        store._manual_status_until = 0.0
        store._state = app.default_state()
        observation = ProviderObservation(
            provider_id="codex",
            display_name="Codex",
            online=True,
            status=AgentStatus.RUNNING,
            project="VibeStick",
            quota_5h_remaining=75,
            quota_7d_remaining=90,
            quota_updated_at="12:00",
            quota_stale=False,
            alert_type="NONE",
            alert_message="",
            alert_event_id="",
            today_used_percent=16,
            running_tasks=2,
            waiting_tasks=3,
        )

        with mock.patch.object(app, "observe_codex", return_value=observation):
            with mock.patch.object(store, "_apply_codex_quota"):
                store._refresh_providers_locked()

        self.assertEqual(store._state.active_provider, "codex")
        self.assertEqual(store._state.provider.id, "codex")
        self.assertEqual(store._state.provider.status, AgentStatus.RUNNING)
        self.assertEqual(store._state.provider.running_tasks, 2)
        self.assertEqual(store._state.provider.waiting_tasks, 3)
        self.assertEqual(store._state.provider.today_used_percent, 16)

    def test_finished_counter_persists_for_current_day_and_deduplicates_event_id(self) -> None:
        store = app.BridgeStateStore.__new__(app.BridgeStateStore)
        store._state = app.default_state()
        store._finished_tasks = 7
        store._last_finished_event_id = "evt_old_done"
        store._task_stats_day = "2026-07-28"

        with tempfile.TemporaryDirectory() as tmp:
            stats_path = Path(tmp) / "task-stats.json"
            with (
                mock.patch.object(app, "TASK_STATS_PATH", stats_path),
                mock.patch.object(app, "_local_date_key", return_value="2026-07-28"),
            ):
                store._record_finished_event("evt_new_done")
                store._record_finished_event("evt_new_done")

                self.assertEqual(store._finished_tasks, 8)
                self.assertEqual(store._state.codex.finished_tasks, 8)
                self.assertEqual(store._state.provider.finished_tasks, 8)
                self.assertEqual(
                    json.loads(stats_path.read_text()),
                    {
                        "local_date": "2026-07-28",
                        "finished_tasks": 8,
                        "last_finished_event_id": "evt_new_done",
                    },
                )

                restored = app.BridgeStateStore.__new__(app.BridgeStateStore)
                self.assertEqual(
                    restored._load_task_stats(),
                    (8, "evt_new_done", "2026-07-28"),
                )

    def test_finished_counter_resets_on_local_day_change(self) -> None:
        store = app.BridgeStateStore.__new__(app.BridgeStateStore)
        store._state = app.default_state()
        store._finished_tasks = 7
        store._last_finished_event_id = "evt_yesterday_done"
        store._task_stats_day = "2026-07-27"

        with tempfile.TemporaryDirectory() as tmp:
            stats_path = Path(tmp) / "task-stats.json"
            with (
                mock.patch.object(app, "TASK_STATS_PATH", stats_path),
                mock.patch.object(app, "_local_date_key", return_value="2026-07-28"),
            ):
                store._ensure_current_task_day()

                self.assertEqual(store._finished_tasks, 0)
                self.assertEqual(store._state.codex.finished_tasks, 0)
                self.assertEqual(store._state.provider.finished_tasks, 0)
                self.assertEqual(
                    json.loads(stats_path.read_text()),
                    {
                        "local_date": "2026-07-28",
                        "finished_tasks": 0,
                        "last_finished_event_id": "evt_yesterday_done",
                    },
                )

                store._record_finished_event("evt_yesterday_done")
                self.assertEqual(store._finished_tasks, 0)

                store._record_finished_event("evt_today_done")
                self.assertEqual(store._finished_tasks, 1)

    def test_legacy_finished_counter_starts_fresh_today(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stats_path = Path(tmp) / "task-stats.json"
            stats_path.write_text(
                json.dumps(
                    {
                        "finished_tasks": 41,
                        "last_finished_event_id": "evt_legacy_done",
                    }
                )
            )
            store = app.BridgeStateStore.__new__(app.BridgeStateStore)
            with mock.patch.object(app, "TASK_STATS_PATH", stats_path):
                self.assertEqual(
                    store._load_task_stats(),
                    (41, "evt_legacy_done", ""),
                )

    def test_manual_status_updates_codex_provider(self) -> None:
        store = app.BridgeStateStore.__new__(app.BridgeStateStore)
        store._state = app.default_state()

        store._set_codex_status("approval", "Needs approval")

        self.assertEqual(store._state.active_provider, "codex")
        self.assertEqual(store._state.codex.status, AgentStatus.APPROVAL)
        self.assertEqual(store._state.provider.status, AgentStatus.APPROVAL)


if __name__ == "__main__":
    unittest.main()
