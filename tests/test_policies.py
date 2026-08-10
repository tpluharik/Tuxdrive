import unittest
from datetime import datetime
from unittest.mock import patch

from tuxdrive.models import AppSettings
from tuxdrive.policies import TransferPolicy


class TransferPolicyTests(unittest.TestCase):
    def test_default_is_unrestricted_maximum_usage(self):
        settings = AppSettings()
        with patch.object(TransferPolicy, "_metered", return_value=True), patch.object(
            TransferPolicy, "_battery_percent", return_value=1
        ):
            self.assertTrue(TransferPolicy(settings).evaluate().allowed)

    def test_controlled_schedule_and_battery_pause(self):
        settings = AppSettings(
            network_policy="controlled", pause_below_battery_percent=30,
            schedule_start="08:00", schedule_end="18:00",
        )
        with patch.object(TransferPolicy, "_battery_percent", return_value=20), patch.object(
            TransferPolicy, "_on_ac_power", return_value=False
        ), patch.object(TransferPolicy, "_metered", return_value=False):
            decision = TransferPolicy(settings).evaluate(datetime(2026, 1, 1, 10, 0))
        self.assertFalse(decision.allowed)
        self.assertIn("battery", decision.reason)

    def test_controlled_schedule_pauses_outside_window(self):
        settings = AppSettings(network_policy="controlled", schedule_start="08:00", schedule_end="18:00")
        with patch.object(TransferPolicy, "_battery_percent", return_value=None), patch.object(
            TransferPolicy, "_metered", return_value=False
        ):
            self.assertFalse(TransferPolicy(settings).evaluate(datetime(2026, 1, 1, 22, 0)).allowed)
