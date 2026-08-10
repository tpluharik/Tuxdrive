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
        for system in ("linux", "osx"):
            self.assertEqual(len(RCLONE_SHA256[(system, "amd64")]), 64)
            self.assertEqual(len(RCLONE_SHA256[(system, "arm64")]), 64)

    @patch("tuxdrive.bootstrap.resolve_rclone", return_value=None)
    @patch("tuxdrive.bootstrap.platform.system", return_value="Darwin")
    @patch("tuxdrive.bootstrap.platform.machine", return_value="arm64")
    @patch("tuxdrive.bootstrap.urllib.request.urlopen")
    def test_macos_bootstrap_selects_osx_archive(self, urlopen, _machine, _system, _resolve):
        urlopen.side_effect = OSError("offline test")
        with tempfile.TemporaryDirectory() as temporary, patch(
            "tuxdrive.bootstrap.user_rclone_path", return_value=Path(temporary) / "rclone"
        ):
            with self.assertRaises(BootstrapError):
                install_rclone()
        self.assertIn("rclone-v1.75.0-osx-arm64.zip", urlopen.call_args.args[0])

    @patch("tuxdrive.bootstrap.resolve_rclone", return_value=None)
    @patch("tuxdrive.bootstrap.platform.machine", return_value="mips64")
    def test_unsupported_architecture_is_explained(self, _machine, _resolve):
        with self.assertRaisesRegex(BootstrapError, "Unsupported CPU architecture"):
            install_rclone()


if __name__ == "__main__":
    unittest.main()
