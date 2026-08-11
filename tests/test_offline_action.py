import unittest

from tuxdrive.nautilus_support import availability_route, command_line_path


class OfflineActionTests(unittest.TestCase):
    def test_command_line_fallback_accepts_both_path_forms(self):
        self.assertEqual(
            command_line_path(["--offline-path", "/mnt/Cloud/a b"], "offline-path"),
            "/mnt/Cloud/a b",
        )
        self.assertEqual(
            command_line_path(["--offline-path=/mnt/Cloud/a b"], "offline-path"),
            "/mnt/Cloud/a b",
        )
        self.assertEqual(command_line_path(["--background"], "offline-path"), "")

    def test_running_mount_dispatches_without_runtime_discovery(self):
        self.assertEqual(
            availability_route(mounted=True, runtime_ready=False, enabled=True),
            "dispatch",
        )

    def test_cold_mount_queues_until_runtime_is_ready(self):
        self.assertEqual(
            availability_route(mounted=False, runtime_ready=False, enabled=True),
            "queue",
        )
        self.assertEqual(
            availability_route(mounted=False, runtime_ready=True, enabled=True),
            "start-mount",
        )


if __name__ == "__main__":
    unittest.main()
