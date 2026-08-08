import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tuxdrive.bootstrap import BootstrapError, RCLONE_SHA256, install_rclone, resolve_rclone


class BootstrapTests(unittest.TestCase):
    def test_explicit_executable_is_preferred(self):
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "rclone"
            executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            executable.chmod(0o755)
            with patch("tuxdrive.bootstrap.rclone_compatible", return_value=True):
                self.assertEqual(resolve_rclone(str(executable)), str(executable))

    def test_incompatible_system_rclone_is_rejected(self):
        with patch("tuxdrive.bootstrap.shutil.which", return_value="/usr/bin/rclone"), patch(
            "tuxdrive.bootstrap.Path.is_file", return_value=True
        ), patch("tuxdrive.bootstrap.os.access", return_value=True), patch(
            "tuxdrive.bootstrap.rclone_compatible", return_value=False
        ):
            self.assertIsNone(resolve_rclone())

    def test_release_checksums_cover_supported_architectures(self):
        self.assertEqual(len(RCLONE_SHA256["amd64"]), 64)
        self.assertEqual(len(RCLONE_SHA256["arm64"]), 64)

    @patch("tuxdrive.bootstrap.resolve_rclone", return_value=None)
    @patch("tuxdrive.bootstrap.platform.machine", return_value="mips64")
    def test_unsupported_architecture_is_explained(self, _machine, _resolve):
        with self.assertRaisesRegex(BootstrapError, "Unsupported CPU architecture"):
            install_rclone()


if __name__ == "__main__":
    unittest.main()
