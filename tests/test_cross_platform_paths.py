import os
from pathlib import Path
import unittest
from unittest import mock

from vibe_stick.config import paths


class CrossPlatformPathTests(unittest.TestCase):
    def test_windows_uses_local_app_data(self) -> None:
        with (
            mock.patch.object(paths.platform, "system", return_value="Windows"),
            mock.patch.dict(os.environ, {"LOCALAPPDATA": "C:/Users/Test/AppData/Local"}),
        ):
            result = paths._default_app_support_dir()
        self.assertEqual(result, Path("C:/Users/Test/AppData/Local/VibeStick"))

    def test_macos_keeps_application_support_location(self) -> None:
        with (
            mock.patch.object(paths.platform, "system", return_value="Darwin"),
            mock.patch.object(paths.Path, "home", return_value=Path("/Users/test")),
        ):
            result = paths._default_app_support_dir()
        self.assertEqual(result, Path("/Users/test/Library/Application Support/VibeStick"))


if __name__ == "__main__":
    unittest.main()
