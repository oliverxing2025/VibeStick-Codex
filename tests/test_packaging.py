from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    def test_macos_installer_generates_private_token_at_first_run(self) -> None:
        launcher = (ROOT / "packaging/macos/VibeStickBridge.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("openssl rand -hex 32", launcher)
        self.assertIn("VIBE_STICK_ASR_API_KEY=", launcher)
        self.assertNotIn("VIBE_STICK_ASR_API_KEY=sk-", launcher)
        self.assertIn("chmod 600", launcher)
        self.assertIn("http://127.0.0.1:8765/setup/voice", launcher)

    def test_windows_installer_generates_private_token_at_first_run(self) -> None:
        installer = (ROOT / "scripts/install-windows.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("RandomNumberGenerator", installer)
        self.assertIn("VIBE_STICK_ASR_API_KEY=", installer)
        self.assertNotIn("VIBE_STICK_ASR_API_KEY=sk-", installer)
        self.assertIn("icacls.exe", installer)
        self.assertIn("http://127.0.0.1:8765/setup/voice", installer)

    def test_ci_publishes_installers_with_checksums(self) -> None:
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("VibeStick-Bridge-Windows-*-Setup.exe.sha256", workflow)
        self.assertIn("VibeStick-Bridge-macOS-*.dmg.sha256", workflow)
        self.assertNotIn("VibeStick-Codex-Windows-preview.zip", workflow)

    def test_macos_uninstaller_preserves_private_configuration(self) -> None:
        uninstaller = (
            ROOT / "packaging/macos/Uninstall VibeStick Bridge.command"
        ).read_text(encoding="utf-8")
        self.assertIn("com.vibestick.bridge.plist", uninstaller)
        self.assertIn("Finder", uninstaller)
        self.assertNotIn('rm -rf "$HOME/Library/Application Support/VibeStick"',
                         uninstaller)


if __name__ == "__main__":
    unittest.main()
