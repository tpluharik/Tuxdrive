#!/usr/bin/env python3
"""Read/create TuxDrive's rclone key using macOS Keychain APIs, never argv."""

from __future__ import annotations

import ctypes
import getpass
import secrets
import sys


security = ctypes.CDLL("/System/Library/Frameworks/Security.framework/Security")
core = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
service = b"io.github.tuxdrive.TuxDrive.rclone-config"
account = getpass.getuser().encode("utf-8")

security.SecKeychainFindGenericPassword.argtypes = [
    ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint32,
    ctypes.c_char_p, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_void_p),
    ctypes.POINTER(ctypes.c_void_p),
]
security.SecKeychainAddGenericPassword.argtypes = [
    ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint32,
    ctypes.c_char_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
]
security.SecKeychainItemFreeContent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
core.CFRelease.argtypes = [ctypes.c_void_p]


def read_secret() -> tuple[str | None, ctypes.c_void_p]:
    length = ctypes.c_uint32()
    data = ctypes.c_void_p()
    item = ctypes.c_void_p()
    status = security.SecKeychainFindGenericPassword(
        None, len(service), service, len(account), account,
        ctypes.byref(length), ctypes.byref(data), ctypes.byref(item),
    )
    if status != 0:
        return None, item
    try:
        value = ctypes.string_at(data, length.value).decode("utf-8")
    finally:
        security.SecKeychainItemFreeContent(None, data)
    return value, item


def main() -> int:
    value, item = read_secret()
    try:
        if value is None and "--ensure" in sys.argv[1:]:
            value = secrets.token_urlsafe(48)
            encoded = value.encode("utf-8")
            created = ctypes.c_void_p()
            status = security.SecKeychainAddGenericPassword(
                None, len(service), service, len(account), account,
                len(encoded), ctypes.cast(ctypes.c_char_p(encoded), ctypes.c_void_p), ctypes.byref(created),
            )
            if created:
                core.CFRelease(created)
            if status != 0:
                print(f"TuxDrive could not store its Keychain secret (OSStatus {status})", file=sys.stderr)
                return 1
        if not value:
            print("TuxDrive configuration key is unavailable in macOS Keychain", file=sys.stderr)
            return 1
        print(value)
        return 0
    finally:
        if item:
            core.CFRelease(item)


if __name__ == "__main__":
    raise SystemExit(main())
