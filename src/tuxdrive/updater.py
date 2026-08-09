from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


MANIFEST_URL = "https://raw.githubusercontent.com/tpluharik/Tuxdrive/main/update/latest.json"
ALLOWED_PREFIX = "https://raw.githubusercontent.com/tpluharik/Tuxdrive/"


@dataclass(frozen=True, slots=True)
class UpdateRelease:
    version: str
    url: str
    sha256: str
    notes: str = ""


def version_key(value: str) -> tuple[int, ...]:
    parts = value.removeprefix("v").split(".")
    if not parts or any(not part.isdigit() for part in parts):
        raise ValueError(f"Invalid release version: {value}")
    return tuple(int(part) for part in parts)


class UpdateManager:
    def __init__(self, current_version: str, cache_dir: Path | None = None) -> None:
        self.current_version = current_version
        self.cache_dir = cache_dir or Path.home() / ".cache" / "tuxdrive" / "updates"

    @staticmethod
    def parse_manifest(payload: bytes) -> UpdateRelease:
        data = json.loads(payload.decode("utf-8"))
        release = UpdateRelease(
            version=str(data["version"]),
            url=str(data["url"]),
            sha256=str(data["sha256"]).lower(),
            notes=str(data.get("notes", "")),
        )
        version_key(release.version)
        if not release.url.startswith(ALLOWED_PREFIX) or not release.url.endswith(".deb"):
            raise ValueError("The update package URL is not an approved TuxDrive repository URL")
        if len(release.sha256) != 64 or any(c not in "0123456789abcdef" for c in release.sha256):
            raise ValueError("The update manifest has an invalid SHA-256 checksum")
        return release

    def check(self) -> UpdateRelease | None:
        request = urllib.request.Request(MANIFEST_URL, headers={"User-Agent": "TuxDrive-Updater"})
        with urllib.request.urlopen(request, timeout=20) as response:
            release = self.parse_manifest(response.read(128 * 1024))
        return release if version_key(release.version) > version_key(self.current_version) else None

    def download(
        self,
        release: UpdateRelease,
        progress: Callable[[int, int], None] | None = None,
    ) -> Path:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        target = self.cache_dir / f"tuxdrive_{release.version}_all.deb"
        temporary = target.with_suffix(".deb.part")
        request = urllib.request.Request(release.url, headers={"User-Agent": "TuxDrive-Updater"})
        digest = hashlib.sha256()
        with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as output:
            total = int(response.headers.get("Content-Length", 0)) if hasattr(response, "headers") else 0
            received = 0
            while chunk := response.read(1024 * 1024):
                digest.update(chunk)
                output.write(chunk)
                received += len(chunk)
                if progress:
                    progress(received, total)
        if digest.hexdigest() != release.sha256:
            temporary.unlink(missing_ok=True)
            raise ValueError("Downloaded package failed SHA-256 verification")
        temporary.replace(target)
        if progress:
            progress(target.stat().st_size, target.stat().st_size)
        return target

    def install(self, package: Path) -> None:
        pkexec = shutil.which("pkexec")
        apt_get = shutil.which("apt-get") or "/usr/bin/apt-get"
        if not pkexec:
            raise RuntimeError("The PolicyKit update helper (pkexec) is unavailable")
        result = subprocess.run(
            [pkexec, apt_get, "install", "-y", str(package.resolve())],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=600,
            check=False,
        )
        if result.returncode:
            detail = result.stdout.strip()[-2000:]
            raise RuntimeError(detail or f"Package installer exited with status {result.returncode}")
