import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from tuxindrive.network_usage import NetworkUsageMeter, _linux_counters, format_bytes


class Sequence:
    def __init__(self, values):
        self.values = iter(values)

    def __call__(self):
        return next(self.values)


class NetworkUsageTests(unittest.TestCase):
    def test_current_rates_and_daily_totals(self):
        with tempfile.TemporaryDirectory() as temporary:
            meter = NetworkUsageMeter(
                Path(temporary) / "usage.json",
                reader=Sequence([(1000, 2000), (3048, 3024)]),
                clock=Sequence([10.0, 10.0, 12.0]),
                today=lambda: date(2026, 8, 13),
            )
            usage = meter.sample()
        self.assertEqual(usage.download_rate, 1024.0)
        self.assertEqual(usage.upload_rate, 512.0)
        self.assertEqual(usage.downloaded_today, 2048)
        self.assertEqual(usage.uploaded_today, 1024)

    def test_restart_restores_total_and_counts_traffic_while_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "usage.json"
            path.write_text(json.dumps({
                "day": "2026-08-13", "downloaded": 500,
                "uploaded": 250, "counters": [1000, 2000],
            }), encoding="utf-8")
            meter = NetworkUsageMeter(
                path, reader=lambda: (1600, 2300), clock=lambda: 5.0,
                today=lambda: date(2026, 8, 13),
            )
        self.assertEqual(meter.usage.downloaded_today, 1100)
        self.assertEqual(meter.usage.uploaded_today, 550)

    def test_new_day_resets_totals_and_counter_reset_is_safe(self):
        days = Sequence([date(2026, 8, 13), date(2026, 8, 14)])
        with tempfile.TemporaryDirectory() as temporary:
            meter = NetworkUsageMeter(
                Path(temporary) / "usage.json",
                reader=Sequence([(5000, 9000), (100, 200)]),
                clock=Sequence([1.0, 1.0, 2.0]), today=days,
            )
            usage = meter.sample()
        self.assertEqual((usage.downloaded_today, usage.uploaded_today), (0, 0))

    def test_linux_parser_excludes_loopback(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "dev"
            path.write_text(
                "Inter-| Receive | Transmit\n face |bytes packets errs drop fifo frame compressed multicast|bytes packets errs drop fifo colls carrier compressed\n"
                " lo: 900 0 0 0 0 0 0 0 800 0 0 0 0 0 0 0\n"
                "eth0: 1234 0 0 0 0 0 0 0 5678 0 0 0 0 0 0 0\n",
                encoding="utf-8",
            )
            self.assertEqual(_linux_counters(path), (1234, 5678))

    def test_human_readable_units(self):
        self.assertEqual(format_bytes(0), "0 B")
        self.assertEqual(format_bytes(1536), "1.5 KiB")
        self.assertEqual(format_bytes(1024 * 1024, rate=True), "1.0 MiB/s")


if __name__ == "__main__":
    unittest.main()
