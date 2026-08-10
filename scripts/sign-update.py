#!/usr/bin/env python3
"""Create a signed TuxDrive update manifest without exposing the private key."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--private-key", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("update/latest.json"))
    parser.add_argument("--valid-days", type=int, default=90)
    parser.add_argument("--notes", default="Security and reliability update")
    args = parser.parse_args()
    if args.valid_days < 1 or args.valid_days > 180:
        parser.error("--valid-days must be between 1 and 180")
    package = args.package.read_bytes()
    private = serialization.load_pem_private_key(args.private_key.read_bytes(), password=None)
    if not isinstance(private, Ed25519PrivateKey):
        parser.error("the release key must be Ed25519")
    signed = {
        "version": args.version,
        "url": f"https://raw.githubusercontent.com/tpluharik/Tuxdrive/main/dist/tuxdrive_{args.version}_all.deb",
        "sha256": hashlib.sha256(package).hexdigest(),
        "notes": args.notes,
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=args.valid_days)).isoformat(),
    }
    canonical = json.dumps(signed, sort_keys=True, separators=(",", ":")).encode("utf-8")
    manifest = {**signed, "signature": base64.b64encode(private.sign(canonical)).decode("ascii")}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
