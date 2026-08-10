"""Host capability discovery for portable Debian-family installations."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class FeatureCheck:
    name: str
    available: bool
    required: bool
    detail: str
    install_hint: str = ""


def _os_release(path: Path = Path("/etc/os-release")) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                values[key] = value.strip().strip('"')
    except OSError:
        pass
    return values


def _command(name: str, required: bool, detail: str, hint: str) -> FeatureCheck:
    location = shutil.which(name)
    return FeatureCheck(name, bool(location), required, location or detail, hint)


def inspect_host() -> dict[str, object]:
    release = _os_release()
    machine = platform.machine().lower()
    supported_arch = machine in {"x86_64", "amd64", "aarch64", "arm64"}
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "unknown")
    session = os.environ.get("XDG_SESSION_TYPE", "unknown")
    checks = [
        _command("secret-tool", True, "Secret Service client missing", "Install libsecret-tools and enable a Secret Service keyring"),
        _command("xdg-open", True, "Desktop URL opener missing", "Install xdg-utils"),
        _command("fusermount3", False, "Streaming unavailable", "Install fuse3 and permit access to /dev/fuse"),
        _command("nautilus", False, "Nautilus integration unavailable", "Install nautilus and python3-nautilus, or leave integration disabled"),
        _command("pkexec", False, "In-app package installation unavailable", "Install the distribution's PolicyKit pkexec package"),
        _command("notify-send", False, "Desktop notifications unavailable", "Install libnotify-bin"),
        _command("nmcli", False, "Metered-network policies unavailable", "Install and enable NetworkManager"),
        _command("tor", False, "Onion transport unavailable", "Install tor and torsocks"),
        _command("obfs4proxy", False, "Obfs4 bridge profile unavailable", "Install obfs4proxy"),
        _command("upnpc", False, "UPnP NAT traversal unavailable", "Install miniupnpc"),
        _command("natpmpc", False, "NAT-PMP traversal unavailable", "Install natpmpc"),
        _command("qrencode", False, "QR invitation rendering unavailable", "Install qrencode"),
        _command("zbarimg", False, "QR invitation scanning unavailable", "Install zbar-tools"),
    ]
    try:
        crypto_version = importlib.metadata.version("cryptography")
    except importlib.metadata.PackageNotFoundError:
        crypto_version = "missing"
    checks.insert(0, FeatureCheck("cryptography", crypto_version != "missing", True, crypto_version, "Install python3-cryptography"))
    required_ok = supported_arch and all(item.available for item in checks if item.required)
    return {
        "schema": 1,
        "distribution": release.get("PRETTY_NAME", release.get("ID", "unknown")),
        "distribution_id": release.get("ID", "unknown"),
        "distribution_like": release.get("ID_LIKE", ""),
        "architecture": machine,
        "architecture_supported": supported_arch,
        "desktop": desktop,
        "session": session,
        "installation": {
            "launcher": "/usr/bin/tuxdrive",
            "application": "/usr/lib/tuxdrive",
            "nautilus_extension": "/usr/share/nautilus-python/extensions/tuxdrive.py",
            "machine_report": "/var/lib/tuxdrive/install-capabilities.json",
            "user_configuration": "${XDG_CONFIG_HOME:-~/.config}/tuxdrive",
        },
        "required_ready": required_ok,
        "features": [asdict(item) for item in checks],
    }


def format_report(report: dict[str, object]) -> str:
    status = "READY" if report["required_ready"] else "INCOMPLETE"
    lines = [
        f"TuxDrive system check: {status}",
        f"Host: {report['distribution']} · {report['architecture']} · {report['desktop']} ({report['session']})",
        f"Installed application: {report['installation']['application']}",
    ]
    if not report["architecture_supported"]:
        lines.append("[required] architecture: unsupported (use amd64 or arm64)")
    for item in report["features"]:
        marker = "ok" if item["available"] else ("MISSING" if item["required"] else "optional")
        lines.append(f"[{marker}] {item['name']}: {item['detail']}")
        if not item["available"] and item["install_hint"]:
            lines.append(f"         {item['install_hint']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check TuxDrive host integration support")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = inspect_host()
    print(json.dumps(report, indent=2) if args.json else format_report(report))
    return 0 if report["required_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
