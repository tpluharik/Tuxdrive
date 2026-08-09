import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tuxdrive.updater import UpdateManager, version_key


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
    def release_payload(self, version="0.5.1", body=b"deb"):
        return json.dumps({
            "version": version,
            "url": f"https://raw.githubusercontent.com/tpluharik/Tuxdrive/main/dist/tuxdrive_{version}_all.deb",
            "sha256": hashlib.sha256(body).hexdigest(),
            "notes": "Test release",
        }).encode()

    def test_version_comparison_is_numeric(self):
        self.assertGreater(version_key("0.10.0"), version_key("0.9.9"))

    def test_manifest_rejects_untrusted_download(self):
        payload = self.release_payload().replace(b"raw.githubusercontent.com/tpluharik/Tuxdrive", b"example.com")
        with self.assertRaises(ValueError):
            UpdateManager.parse_manifest(payload)

    def test_check_reports_only_newer_version(self):
        manager = UpdateManager("0.5.0")
        with patch("urllib.request.urlopen", return_value=FakeResponse(self.release_payload())):
            self.assertEqual(manager.check().version, "0.5.1")
        with patch("urllib.request.urlopen", return_value=FakeResponse(self.release_payload("0.5.0"))):
            self.assertIsNone(manager.check())

    def test_download_verifies_checksum(self):
        body = b"valid-debian-package-placeholder"
        release = UpdateManager.parse_manifest(self.release_payload(body=body))
        with tempfile.TemporaryDirectory() as directory:
            manager = UpdateManager("0.5.0", Path(directory))
            with patch("urllib.request.urlopen", return_value=FakeResponse(body)):
                target = manager.download(release)
            self.assertEqual(target.read_bytes(), body)

    def test_download_reports_progress(self):
        body = b"progress-data"
        release = UpdateManager.parse_manifest(self.release_payload(body=body))
        updates = []
        with tempfile.TemporaryDirectory() as directory:
            manager = UpdateManager("0.6.0", Path(directory))
            with patch("urllib.request.urlopen", return_value=FakeResponse(body)):
                manager.download(release, lambda received, total: updates.append((received, total)))
        self.assertTrue(updates)
        self.assertEqual(updates[-1], (len(body), len(body)))

    def test_download_removes_bad_partial(self):
        release = UpdateManager.parse_manifest(self.release_payload(body=b"expected"))
        with tempfile.TemporaryDirectory() as directory:
            manager = UpdateManager("0.5.0", Path(directory))
            with patch("urllib.request.urlopen", return_value=FakeResponse(b"tampered")):
                with self.assertRaises(ValueError):
                    manager.download(release)
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
