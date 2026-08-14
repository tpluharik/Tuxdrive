"""Store the rclone configuration password in the native desktop key store."""

from __future__ import annotations

import argparse
import secrets
import sys


SERVICE = "io.github.tuxindrive.TuxInDrive"
LEGACY_SERVICE = "io.github.tuxdrive.TuxDrive"
ACCOUNT = "rclone-config"


def _keyring():
    try:
        import keyring
    except ImportError as exc:  # pragma: no cover - desktop package dependency
        raise RuntimeError("The native credential-store integration is unavailable") from exc
    return keyring


def configuration_password(ensure: bool = False) -> str:
    keyring = _keyring()
    password = keyring.get_password(SERVICE, ACCOUNT)
    if not password:
        password = keyring.get_password(LEGACY_SERVICE, ACCOUNT)
    if not password and ensure:
        password = secrets.token_urlsafe(48)
        keyring.set_password(SERVICE, ACCOUNT, password)
    if not password:
        raise RuntimeError("TuxInDrive configuration key is unavailable")
    return password


def store_configuration_password(password: str) -> None:
    if not password or len(password) > 1024:
        raise RuntimeError("The TuxInDrive configuration key is invalid")
    _keyring().set_password(SERVICE, ACCOUNT, password)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--ensure", action="store_true")
    args = parser.parse_args(argv)
    try:
        print(configuration_password(args.ensure))
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
