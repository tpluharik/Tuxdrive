import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tuxdrive.diagnostics import crash_log_path, log_boot_failure


class DiagnosticsTests(unittest.TestCase):
    def test_boot_failure_is_persisted_before_gui_import(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, {"XDG_STATE_HOME": temporary}
        ):
            log_boot_failure("GTK import failed for test")
            log = crash_log_path()
            self.assertTrue(log.exists())
            self.assertIn("GTK import failed for test", log.read_text(encoding="utf-8"))
            self.assertEqual(log.parent.stat().st_mode & 0o777, 0o700)


if __name__ == "__main__":
    unittest.main()
