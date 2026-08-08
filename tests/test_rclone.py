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
            "_run",
            return_value=subprocess.CompletedProcess([], 0, stdout=output, stderr=""),
        ):
            result = client.begin_oauth("work", Provider.GOOGLE_DRIVE)
        self.assertFalse(result.complete)
        self.assertEqual(result.question.name, "config_is_local")

    def test_remote_name_validation(self):
        with self.assertRaises(ValueError):
            RcloneClient._validate_remote_name("bad:name")


if __name__ == "__main__":
    unittest.main()
