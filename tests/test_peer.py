import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tuxdrive.models import PeerShare
from tuxdrive.peer import (
    PeerError, PeerInvitation, PeerManager, normalize_public_key, validate_port,
)


KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIK7mfakebutsyntacticallyvalidkey1234567890"


class PeerSharingTests(unittest.TestCase):
    def test_invitation_round_trip_keeps_pinned_host_key(self):
        encoded = PeerInvitation("Project", "198.51.100.20", 22022, KEY).encode()
        decoded = PeerInvitation.decode(encoded)
        self.assertEqual(decoded.host, "198.51.100.20")
        self.assertEqual(decoded.port, 22022)
        self.assertEqual(decoded.host_key, KEY)
        self.assertEqual(json.loads(encoded)["tuxdrive_peer"], 1)

    def test_public_key_rejects_authorized_keys_options_and_multiline_input(self):
        self.assertEqual(normalize_public_key(KEY + " laptop"), KEY)
        with self.assertRaises(PeerError):
            normalize_public_key('command="bad" ' + KEY)
        with self.assertRaises(PeerError):
            normalize_public_key(KEY + "\n" + KEY)

    def test_privileged_peer_port_is_rejected(self):
        with self.assertRaises(PeerError):
            validate_port(22)

    def test_server_uses_authorized_peer_key_and_explicit_host_key(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "peer"
            folder = Path(temporary) / "shared"
            folder.mkdir()
            share = PeerShare("Project", str(folder), "192.0.2.10", 22022, KEY, id="share1")
            host = root / "hosts" / share.id
            host.parent.mkdir(parents=True)
            host.write_text("private", encoding="utf-8")
            host.with_suffix(".pub").write_text(KEY, encoding="utf-8")
            process = MagicMock()
            process.poll.return_value = None
            with patch.dict(os.environ, {"XDG_CACHE_HOME": temporary}), patch(
                "tuxdrive.peer.resolve_rclone", return_value="/usr/bin/rclone"
            ), patch(
                "tuxdrive.peer.subprocess.Popen", return_value=process
            ) as popen:
                manager = PeerManager(root=root)
                manager.start(share)
                command = popen.call_args.args[0]
                manager._servers.clear()  # prevent teardown signals against the mock
            self.assertEqual(command[:4], ["/usr/bin/rclone", "serve", "sftp", f":local:{folder}"])
            self.assertIn("--authorized-keys", command)
            self.assertEqual(command[command.index("--key") + 1], str(host))
            authorized = root / "authorized" / "share1.keys"
            self.assertEqual(authorized.read_text(encoding="utf-8").strip(), KEY)

    def test_client_configuration_pins_host_and_uses_private_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "peer"
            root.mkdir()
            private = root / "identity_ed25519"
            private.write_text("private", encoding="utf-8")
            private.with_suffix(".pub").write_text(KEY, encoding="utf-8")
            invitation = PeerInvitation("Project", "203.0.113.4", 22022, KEY)
            with patch("tuxdrive.peer.resolve_rclone", return_value="/usr/bin/rclone"), patch(
                "tuxdrive.peer.subprocess.run",
                return_value=MagicMock(returncode=0, stdout="", stderr=""),
            ) as run:
                PeerManager(root=root).configure_connection("peer-project", invitation)
            command = run.call_args.args[0]
            self.assertIn("key_file", command)
            self.assertEqual(command[command.index("key_file") + 1], str(private))
            self.assertEqual(command[command.index("host_keys") + 1], KEY)


if __name__ == "__main__":
    unittest.main()
