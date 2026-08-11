import unittest
from unittest import mock

from vibe_stick.paste.input_injector import MacPasteInjector


class PasteInputTests(unittest.TestCase):
    @mock.patch("vibe_stick.paste.input_injector.time.sleep")
    @mock.patch("vibe_stick.paste.input_injector.platform.system", return_value="Windows")
    @mock.patch("vibe_stick.paste.input_injector.subprocess.run")
    def test_windows_paste_uses_clipboard_and_sendkeys(self, run, _system, _sleep) -> None:
        run.return_value.returncode = 0
        run.return_value.stdout = "previous"
        run.return_value.stderr = ""

        result = MacPasteInjector().paste("测试语音", press_enter=True)

        self.assertTrue(result.success)
        commands = [call.args[0] for call in run.call_args_list]
        self.assertTrue(all(command[0] == "powershell.exe" for command in commands))
        self.assertTrue(any("Set-Clipboard" in command[-1] for command in commands))
        self.assertTrue(any("SendKeys" in command[-1] and "{ENTER}" in command[-1]
                            for command in commands))


if __name__ == "__main__":
    unittest.main()
