from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).parents[1] / "scripts" / "sticks3_device_guard.py"
SPEC = spec_from_file_location("sticks3_device_guard", SCRIPT)
assert SPEC and SPEC.loader
guard = module_from_spec(SPEC)
sys.modules[SPEC.name] = guard
SPEC.loader.exec_module(guard)


class StickS3DeviceGuardTests(unittest.TestCase):
    def test_parse_identity_accepts_sticks3_mac(self):
        output = """
Chip is ESP32-S3-PICO-1 (LGA56) (revision v0.2)
MAC: 02:00:00:00:00:01
"""
        identity = guard.parse_identity("/dev/cu.usbmodem-test", output)
        self.assertEqual(identity.mac, "02:00:00:00:00:01")
        self.assertEqual(identity.port, "/dev/cu.usbmodem-test")

    def test_parse_identity_rejects_other_chip(self):
        with self.assertRaisesRegex(guard.GuardError, "not an ESP32-S3"):
            guard.parse_identity(
                "/dev/cu.usbmodem-test",
                "Chip is ESP32-C6\nMAC: 02:00:00:00:00:02\n",
            )

    def test_registry_rejects_duplicate_hardware(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "devices.json"
            path.write_text(
                """
{
  "version": 1,
  "devices": [
    {"name": "S3-A", "mac": "02:00:00:00:00:01", "profile": "unassigned"},
    {"name": "S3-B", "mac": "02:00:00:00:00:01", "profile": "unassigned"}
  ]
}
""",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(guard.GuardError, "duplicate"):
                guard.load_registry(path)

    def test_masked_mac_does_not_expose_full_identifier(self):
        masked = guard.masked_mac("02:00:00:00:00:01")
        self.assertEqual(masked, "…:00:01")
        self.assertNotIn("02:00:00:00", masked)

if __name__ == "__main__":
    unittest.main()
