import json
import subprocess
import unittest
from unittest.mock import patch

from tuxdrive.models import Provider
from tuxdrive.rclone import RcloneClient, google_scoped_remote


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

    def test_nested_cloud_folders_are_listed_for_tree_browser(self):
        client = RcloneClient()
        completed = subprocess.CompletedProcess(
            [], 0, stdout="Reports/\nProjects/\n", stderr=""
        )
        with patch.object(client, "_run", return_value=completed) as run:
            folders = client.list_directories("work", "Shared")
        self.assertEqual(folders, ["Projects", "Reports"])
        self.assertEqual(run.call_args.args[0][1], "work:Shared")

    def test_google_locations_include_my_drive_shared_with_me_and_shared_drives(self):
        client = RcloneClient()
        output = json.dumps([{"id": "drive-123", "name": "Operations"}])
        with patch.object(
            client,
            "_run",
            return_value=subprocess.CompletedProcess([], 0, stdout=output, stderr=""),
        ):
            locations = client.google_drive_locations("work")
        self.assertEqual(locations[0].name, "My Drive")
        self.assertEqual(locations[1].name, "Shared with me")
        self.assertTrue(any(item.name == "Shared Drive · Operations" for item in locations))
        shared = next(item for item in locations if item.key == "shared_drive:drive-123")
        self.assertIn("team_drive=drive-123", shared.scoped_remote)

    def test_google_scopes_override_a_preconfigured_shared_drive(self):
        self.assertIn("team_drive=", google_scoped_remote("work", "my_drive"))
        self.assertIn("root_folder_id=root", google_scoped_remote("work", "my_drive"))
        self.assertIn("shared_with_me=true", google_scoped_remote("work", "shared_with_me"))

    def test_eight_cloud_backends_and_direct_peer_backend_are_available(self):
        self.assertEqual(len(Provider), 10)
        self.assertEqual(Provider.DROPBOX.rclone_type, "dropbox")
        self.assertEqual(Provider.BOX.rclone_type, "box")
        self.assertEqual(Provider.PCLOUD.rclone_type, "pcloud")
        self.assertEqual(Provider.MEGA.rclone_type, "mega")
        self.assertEqual(Provider.PROTON_DRIVE.rclone_type, "protondrive")
        self.assertEqual(Provider.NEXTCLOUD.rclone_type, "webdav")
        self.assertEqual(Provider.PEER.rclone_type, "sftp")

    def test_nextcloud_configuration_sets_webdav_vendor(self):
        client = RcloneClient()
        with patch.object(
            client,
            "_run_oauth",
            return_value=subprocess.CompletedProcess([], 0, stdout="", stderr=""),
        ) as run:
            self.assertTrue(client.begin_oauth("cloud", Provider.NEXTCLOUD).complete)
        self.assertEqual(
            run.call_args.args[0][:6],
            ["config", "create", "cloud", "webdav", "vendor", "nextcloud"],
        )

    def test_proton_credentials_are_protected_and_written(self):
        client = RcloneClient()
        credentials = {
            "username": "user@proton.me",
            "password": "raw-password",
            "2fa": "123456",
        }
        with patch.object(
            client, "_obscure", side_effect=lambda value: f"obscured:{value}"
        ) as obscure, patch.object(
            client,
            "_run_oauth",
            return_value=subprocess.CompletedProcess([], 0, stdout="", stderr=""),
        ) as run:
            result = client.begin_oauth(
                "proton", Provider.PROTON_DRIVE, credentials=credentials
            )
        self.assertTrue(result.complete)
        args = run.call_args.args[0]
        self.assertIn("username", args)
        self.assertIn("user@proton.me", args)
        self.assertIn("obscured:raw-password", args)
        self.assertIn("123456", args)
        self.assertNotIn("raw-password", args)
        self.assertEqual(obscure.call_count, 1)
        self.assertEqual(args[-1], "--non-interactive")

    def test_remote_is_listed_before_account_is_accepted(self):
        client = RcloneClient()
        with patch.object(
            client,
            "_run",
            return_value=subprocess.CompletedProcess([], 0, stdout="", stderr=""),
        ) as run:
            client.validate_remote("proton")
        self.assertEqual(
            run.call_args.args[0],
            ["lsf", "proton:", "--dirs-only", "--max-depth", "1"],
        )

    def test_proton_two_factor_requirement_is_detected(self):
        self.assertTrue(RcloneClient.requires_proton_2fa("2FA enabled, but no code provided"))
        self.assertTrue(RcloneClient.requires_proton_2fa("invalid two-factor authentication code"))
        self.assertFalse(RcloneClient.requires_proton_2fa("username and password are required"))

    def test_proton_two_factor_code_is_updated_without_password_obscuring(self):
        client = RcloneClient()
        with patch.object(
            client,
            "_run",
            return_value=subprocess.CompletedProcess([], 0, stdout="", stderr=""),
        ) as run, patch.object(client, "_obscure") as obscure:
            client.update_credentials("proton", Provider.PROTON_DRIVE, {"2fa": "123456"})
        self.assertEqual(
            run.call_args.args[0],
            ["config", "update", "proton", "2fa", "123456", "--non-interactive"],
        )
        obscure.assert_not_called()

    def test_account_discovery_recognizes_added_backends(self):
        configured = {
            "drop": {"type": "dropbox"},
            "mega": {"type": "mega"},
            "next": {"type": "webdav", "vendor": "nextcloud"},
        }
        client = RcloneClient()
        with patch.object(
            client, "_run",
            return_value=subprocess.CompletedProcess([], 0, stdout=json.dumps(configured), stderr=""),
        ):
            accounts = client.discover_accounts()
        self.assertEqual(accounts["drop"], Provider.DROPBOX)
        self.assertEqual(accounts["mega"], Provider.MEGA)
        self.assertEqual(accounts["next"], Provider.NEXTCLOUD)


if __name__ == "__main__":
    unittest.main()
