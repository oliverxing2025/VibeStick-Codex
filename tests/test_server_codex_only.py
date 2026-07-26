import unittest
import threading
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

        store.update_from_event({"event": "side_short", "source": "sticks3"})

        store.codex_controller.send.assert_called_once_with()
        store.codex_controller.next_thread.assert_not_called()
        store.codex_controller.decline.assert_not_called()

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
        )

        with mock.patch.object(app, "observe_codex", return_value=observation):
            with mock.patch.object(store, "_apply_codex_quota"):
                store._refresh_providers_locked()

        self.assertEqual(store._state.active_provider, "codex")
        self.assertEqual(store._state.provider.id, "codex")
        self.assertEqual(store._state.provider.status, AgentStatus.RUNNING)

    def test_manual_status_updates_codex_provider(self) -> None:
        store = app.BridgeStateStore.__new__(app.BridgeStateStore)
        store._state = app.default_state()

        store._set_codex_status("approval", "Needs approval")

        self.assertEqual(store._state.active_provider, "codex")
        self.assertEqual(store._state.codex.status, AgentStatus.APPROVAL)
        self.assertEqual(store._state.provider.status, AgentStatus.APPROVAL)


if __name__ == "__main__":
    unittest.main()
