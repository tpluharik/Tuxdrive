import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tuxdrive.platform_support import _os_release, format_report, inspect_host


class PlatformSupportTests(unittest.TestCase):
    def test_os_release_parser_does_not_execute_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "os-release"
            source.write_text('ID=debian\nPRETTY_NAME="Debian GNU/Linux"\n', encoding="utf-8")
            self.assertEqual(_os_release(source)["ID"], "debian")

    @patch("tuxdrive.platform_support.platform.machine", return_value="x86_64")
    @patch("tuxdrive.platform_support.shutil.which", return_value="/usr/bin/tool")
    def test_supported_host_report_is_machine_readable(self, _which, _machine):
        report = inspect_host()
        self.assertTrue(report["architecture_supported"])
        self.assertTrue(report["required_ready"])
        self.assertEqual(report["installation"]["launcher"], "/usr/bin/tuxdrive")
        json.dumps(report)
        self.assertIn("TuxDrive system check: READY", format_report(report))

    @patch("tuxdrive.platform_support.platform.machine", return_value="riscv64")
    def test_unsupported_bootstrap_architecture_is_blocking(self, _machine):
        report = inspect_host()
        self.assertFalse(report["architecture_supported"])
        self.assertFalse(report["required_ready"])


if __name__ == "__main__":
    unittest.main()
