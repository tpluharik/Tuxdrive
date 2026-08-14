# TuxInDrive platform release channels

Each platform has a dedicated folder containing its signed `latest-v2.json`
update manifest and human-readable package information. Large installers are
kept as durable GitHub Release assets so Android packages can exceed GitHub's
100 MiB repository-file limit.

- `android/` — Android APK channel
- `macos/` — macOS DMG channel
- `windows/` — Windows x64 installer channel

Clients trust only expiring Ed25519-signed manifests, an approved TuxInDrive
download origin, a version-bound package filename, and the declared SHA-256.
