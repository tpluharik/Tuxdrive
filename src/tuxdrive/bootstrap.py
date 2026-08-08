from __future__ import annotations

import hashlib
import os
import platform
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable


RCLONE_VERSION = "1.75.0"
RCLONE_SHA256 = {
    "amd64": "aa2804e08f48250e71009c727124b6341cd0288465804a9a09d14663cabafbaa",
    "arm64": "d0ad88ba4c8e285b7c9efa591e0ab643280a91741e13c27f3a9c0957ccfa5203",
}


class BootstrapError(RuntimeError):
    pass


def user_rclone_path() -> Path:
    return Path.home() / ".local" / "lib" / "tuxdrive" / "rclone"


def resolve_rclone(configured: str = "rclone") -> str | None:
    if configured and configured != "rclone":
        explicit = Path(configured).expanduser()
        if explicit.is_file() and os.access(explicit, os.X_OK):
            return str(explicit)
    bundled = Path("/usr/lib/tuxdrive/bin/rclone")
    if bundled.is_file() and os.access(bundled, os.X_OK):
        return str(bundled)
    system = shutil.which("rclone")
    if system:
        return system
    local = user_rclone_path()
    if local.is_file() and os.access(local, os.X_OK):
        return str(local)
    return None


def install_rclone(progress: Callable[[str], None] | None = None) -> str:
    existing = resolve_rclone()
    if existing:
        return existing
    machine = platform.machine().lower()
    architecture = {
        "x86_64": "amd64",
        "amd64": "amd64",
        "aarch64": "arm64",
        "arm64": "arm64",
    }.get(machine)
    if not architecture:
        raise BootstrapError(f"Unsupported CPU architecture: {machine}")
    filename = f"rclone-v{RCLONE_VERSION}-linux-{architecture}.zip"
    url = f"https://downloads.rclone.org/v{RCLONE_VERSION}/{filename}"
    if progress:
        progress(f"Downloading rclone {RCLONE_VERSION}…")
    destination = user_rclone_path()
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix="tuxdrive-runtime-") as temporary:
        archive = Path(temporary) / filename
        try:
            with urllib.request.urlopen(url, timeout=60) as response, archive.open("wb") as output:
                shutil.copyfileobj(response, output)
        except OSError as exc:
            raise BootstrapError(
                "Could not download the embedded transfer engine. Check the internet connection."
            ) from exc
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if digest != RCLONE_SHA256[architecture]:
            raise BootstrapError("Downloaded rclone archive failed SHA-256 verification")
        if progress:
            progress("Installing verified transfer engine…")
        with zipfile.ZipFile(archive) as package:
            member = next((name for name in package.namelist() if name.endswith("/rclone")), None)
            if not member:
                raise BootstrapError("The rclone archive did not contain the expected executable")
            extracted = Path(package.extract(member, temporary))
            temporary_target = destination.with_suffix(".new")
            shutil.copy2(extracted, temporary_target)
            os.chmod(temporary_target, 0o755)
            os.replace(temporary_target, destination)
    return str(destination)
