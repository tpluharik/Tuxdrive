import hashlib
import json
import tempfile
import base64
import unittest
from pathlib import Path
from unittest.mock import patch

from tuxdrive.updater import UpdateManager, version_key
from tuxdrive.update_helper import PrivilegedUpdateError, stage_verified_package
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.position = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size=-1):
        if size < 0:
            size = len(self.payload)
        chunk = self.payload[self.position:self.position + size]
        self.position += len(chunk)
        return chunk


class UpdateManagerTests(unittest.TestCase):
    def setUp(self):
        self.private = Ed25519PrivateKey.generate()
        self.public = base64.b64encode(self.private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw,
        )).decode("ascii")

    def release_payload(self, version="0.5.1", body=b"deb"):
        signed = {
            "version": version,
            "url": f"https://raw.githubusercontent.com/tpluharik/Tuxdrive/main/dist/tuxdrive_{version}_all.deb",
            "sha256": hashlib.sha256(body).hexdigest(),
            "notes": "Test release",
            "expires_at": "2999-01-01T00:00:00+00:00",
        }
        canonical = json.dumps(signed, sort_keys=True, separators=(",", ":")).encode()
        return json.dumps({**signed, "signature": base64.b64encode(self.private.sign(canonical)).decode("ascii")}).encode()

    def test_version_comparison_is_numeric(self):
        self.assertGreater(version_key("0.10.0"), version_key("0.9.9"))

    def test_repository_manifest_matches_current_debian_release(self):
        """Block releases whose signed update channel was left behind."""
        from tuxdrive import __version__

        package = Path(f"dist/tuxdrive_{__version__}_all.deb")
        self.assertTrue(package.is_file(), "build/sign the current Debian package before release")
        release = UpdateManager.parse_manifest(Path("update/latest-v2.json").read_bytes())
        self.assertEqual(release.version, __version__)
        self.assertEqual(release.url.rsplit("/", 1)[-1], package.name)
        self.assertEqual(release.sha256, hashlib.sha256(package.read_bytes()).hexdigest())

    def test_legacy_bridge_manifest_targets_current_release(self):
        """Keep 0.18.1 on its old trust root without weakening the new channel."""
        from tuxdrive import __version__

        old_public = "xyquZ4Mp8SGBpNiNjEcjhkeaPxBkAOwiBT0AhdhjolU="
        release = UpdateManager.parse_manifest(Path("update/latest.json").read_bytes(), old_public)
        self.assertEqual(release.version, __version__)
        self.assertEqual(release.url.rsplit("/", 1)[-1], f"tuxdrive_{__version__}_all.deb")

    def test_manifest_rejects_untrusted_download(self):
        payload = self.release_payload().replace(b"raw.githubusercontent.com/tpluharik/Tuxdrive", b"example.com")
        with self.assertRaises(ValueError):
            UpdateManager.parse_manifest(payload, self.public)

    def test_check_reports_only_newer_version(self):
        manager = UpdateManager("0.5.0", public_key=self.public)
        with patch("urllib.request.urlopen", return_value=FakeResponse(self.release_payload())):
            self.assertEqual(manager.check().version, "0.5.1")
        with patch("urllib.request.urlopen", return_value=FakeResponse(self.release_payload("0.5.0"))):
            self.assertIsNone(manager.check())

    def test_download_verifies_checksum(self):
        body = b"valid-debian-package-placeholder"
        release = UpdateManager.parse_manifest(self.release_payload(body=body), self.public)
        with tempfile.TemporaryDirectory() as directory:
            manager = UpdateManager("0.5.0", Path(directory))
            with patch("urllib.request.urlopen", return_value=FakeResponse(body)):
                target = manager.download(release)
            self.assertEqual(target.read_bytes(), body)

    def test_download_reports_progress(self):
        body = b"progress-data"
        release = UpdateManager.parse_manifest(self.release_payload(body=body), self.public)
        updates = []
        with tempfile.TemporaryDirectory() as directory:
            manager = UpdateManager("0.6.0", Path(directory))
            with patch("urllib.request.urlopen", return_value=FakeResponse(body)):
                manager.download(release, lambda received, total: updates.append((received, total)))
        self.assertTrue(updates)
        self.assertEqual(updates[-1], (len(body), len(body)))

    def test_download_removes_bad_partial(self):
        release = UpdateManager.parse_manifest(self.release_payload(body=b"expected"), self.public)
        with tempfile.TemporaryDirectory() as directory:
            manager = UpdateManager("0.5.0", Path(directory))
            with patch("urllib.request.urlopen", return_value=FakeResponse(b"tampered")):
                with self.assertRaises(ValueError):
                    manager.download(release)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_privileged_helper_reverifies_root_owned_copy(self):
        body = b"signed package"
        release = UpdateManager.parse_manifest(self.release_payload(version="0.5.1", body=body), self.public)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "tuxdrive_0.5.1_all.deb"
            source.write_bytes(body)
            staged = stage_verified_package(source, root / "staged.deb", release)
            self.assertEqual(staged.read_bytes(), body)

    def test_privileged_helper_rejects_symlink_and_wrong_digest(self):
        body = b"signed package"
        release = UpdateManager.parse_manifest(self.release_payload(version="0.5.1", body=body), self.public)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real = root / "real.deb"
            real.write_bytes(body)
            link = root / "tuxdrive_0.5.1_all.deb"
            link.symlink_to(real)
            with self.assertRaises(PrivilegedUpdateError):
                stage_verified_package(link, root / "stage-one.deb", release)
            link.unlink()
            link.write_bytes(b"replaced after desktop verification")
            with self.assertRaisesRegex(PrivilegedUpdateError, "digest"):
                stage_verified_package(link, root / "stage-two.deb", release)


if __name__ == "__main__":
    unittest.main()
