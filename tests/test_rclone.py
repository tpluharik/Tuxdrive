import json
import subprocess
import unittest
from unittest.mock import patch

from tuxdrive.models import Provider
from tuxdrive.rclone import RcloneClient


class RcloneClientTests(unittest.TestCase):
    def test_noninteractive_question_is_parsed(self):
        output = json.dumps(
            {
                "State": "*oauth-islocal,",
                "Option": {
                    "Name": "config_is_local",
                    "Help": "Use browser?",
                    "Default": True,
                    "Examples": [{"Value": "true", "Help": "Yes"}],
                    "Required": False,
                    "IsPassword": False,
                    "Exclusive": True,
                },
                "Error": "",
            }
        )
        client = RcloneClient()
        with patch.object(
            client,
            "_run_oauth",
            return_value=subprocess.CompletedProcess([], 0, stdout=output, stderr=""),
        ):
            result = client.begin_oauth("work", Provider.GOOGLE_DRIVE)
        self.assertFalse(result.complete)
        self.assertEqual(result.question.name, "config_is_local")

    def test_oauth_address_in_use_error_is_concise(self):
        verbose = "Usage:\n" + ("flags\n" * 100) + "Fatal error: listen tcp 127.0.0.1:53682: bind: address already in use"
        message = RcloneClient._friendly_oauth_error(verbose)
        self.assertIn("callback port", message)
        self.assertLess(len(message), 220)

    def test_busy_callback_port_stops_before_starting_process(self):
        client = RcloneClient("/bin/true")
        with patch.object(client, "available", return_value=True), patch.object(
            client, "_callback_port_busy", return_value=True
        ), patch("tuxdrive.rclone.subprocess.Popen") as popen:
            with self.assertRaisesRegex(Exception, "already in use"):
                client.continue_oauth("work", "state", "true", "wizard-1")
        popen.assert_not_called()

    def test_remote_name_validation(self):
        with self.assertRaises(ValueError):
            RcloneClient._validate_remote_name("bad:name")


if __name__ == "__main__":
    unittest.main()
