import signal
import subprocess
import unittest
from unittest.mock import MagicMock, patch

from tuxindrive.process_control import new_process_group, reload_process, terminate_process


class ProcessControlTests(unittest.TestCase):
    @patch("tuxindrive.process_control.platform.system", return_value="Windows")
    def test_windows_processes_use_native_group_flag(self, _system):
        self.assertEqual(
            new_process_group()["creationflags"],
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200),
        )

    @patch("tuxindrive.process_control.platform.system", return_value="Windows")
    def test_windows_process_is_terminated_without_posix_signals(self, _system):
        process = MagicMock()
        process.poll.return_value = None
        self.assertTrue(terminate_process(process))
        process.terminate.assert_called_once_with()

    @patch("tuxindrive.process_control.platform.system", return_value="Linux")
    @patch("tuxindrive.process_control.os.killpg")
    def test_unix_process_group_receives_signal(self, killpg, _system):
        process = MagicMock(pid=1234)
        process.poll.return_value = None
        self.assertTrue(terminate_process(process, force=True))
        killpg.assert_called_once_with(1234, signal.SIGKILL)

    @patch("tuxindrive.process_control.platform.system", return_value="Windows")
    def test_windows_reload_fails_closed(self, _system):
        process = MagicMock()
        process.poll.return_value = None
        self.assertFalse(reload_process(process))


if __name__ == "__main__":
    unittest.main()
