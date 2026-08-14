import threading
import time
import unittest
from unittest.mock import patch

from tuxindrive.bandwidth import (
    GlobalBandwidthController,
    effective_rclone_limit,
    normalize_bandwidth_limit,
)


class GlobalBandwidthControllerTests(unittest.TestCase):
    def test_rates_are_validated_and_directional_limits_are_combined(self):
        self.assertEqual(normalize_bandwidth_limit(" 2M:10M "), "2M:10M")
        self.assertEqual(effective_rclone_limit("2M:10M", "5M:4M"), "2M:4M")
        self.assertEqual(effective_rclone_limit("off", "3M"), "3M")
        with self.assertRaises(ValueError):
            normalize_bandwidth_limit("weekday 10M")

    def test_rclone_uses_global_limit_unless_job_is_stricter(self):
        controller = GlobalBandwidthController("10M")
        self.assertEqual(controller.rclone_args(), ["--bwlimit", "10M"])
        self.assertEqual(controller.rclone_args("2M"), ["--bwlimit", "2M"])
        controller.configure("off")
        self.assertFalse(controller.enabled)

    def test_in_process_downloads_share_one_rate_clock(self):
        controller = GlobalBandwidthController("1")
        with patch("tuxindrive.bandwidth.time.monotonic", return_value=10.0), patch(
            "tuxindrive.bandwidth.time.sleep"
        ) as sleep:
            controller.throttle_download(1024)
            controller.throttle_download(1024)
        sleep.assert_called_once_with(1.0)

    def test_parallel_exclusive_callers_do_not_deadlock(self):
        controller = GlobalBandwidthController("1M", max_active=2)
        completed: list[int] = []

        def run(index: int) -> None:
            with controller.guard(exclusive=True):
                time.sleep(0.01)
                completed.append(index)

        threads = [threading.Thread(target=run, args=(index,)) for index in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=1)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertCountEqual(completed, [0, 1])


if __name__ == "__main__":
    unittest.main()
