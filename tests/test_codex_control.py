import unittest
from unittest.mock import patch

from vibe_stick.desktop.codex_control import CodexDesktopController


class CodexDesktopControllerTests(unittest.TestCase):
    @patch("vibe_stick.desktop.codex_control.platform.system", return_value="Darwin")
    @patch("vibe_stick.desktop.codex_control.subprocess.run")
    def test_next_thread_uses_verified_codex_shortcut(self, run, _system) -> None:
        run.return_value.returncode = 0
        run.return_value.stderr = ""
        run.return_value.stdout = ""

        result = CodexDesktopController().next_thread()

        self.assertTrue(result.success)
        args = run.call_args.args[0]
        self.assertEqual(args[:2], ["osascript", "-e"])
        self.assertIn('keystroke "]" using {command down, shift down}', args[2])

    @patch("vibe_stick.desktop.codex_control.platform.system", return_value="Darwin")
    @patch("vibe_stick.desktop.codex_control.subprocess.run")
    def test_send_approval_and_decline_use_enter_enter_and_escape(self, run, _system) -> None:
        run.return_value.returncode = 0
        run.return_value.stderr = ""
        run.return_value.stdout = ""
        controller = CodexDesktopController()

        controller.send()
        send_script = run.call_args.args[0][2]
        controller.approve()
        approve_script = run.call_args.args[0][2]
        controller.decline()
        decline_script = run.call_args.args[0][2]

        self.assertIn("key code 36", send_script)
        self.assertIn("key code 36", approve_script)
        self.assertIn("key code 53", decline_script)

    @patch("vibe_stick.desktop.codex_control.platform.system", return_value="Darwin")
    @patch("vibe_stick.desktop.codex_control.subprocess.run")
    def test_clear_input_selects_all_then_deletes(self, run, _system) -> None:
        run.return_value.returncode = 0
        run.return_value.stderr = ""
        run.return_value.stdout = ""

        result = CodexDesktopController().clear_input()

        self.assertTrue(result.success)
        script = run.call_args.args[0][2]
        self.assertIn('keystroke "a" using command down', script)
        self.assertIn("key code 51", script)
        self.assertLess(script.index('keystroke "a"'), script.index("key code 51"))


if __name__ == "__main__":
    unittest.main()
