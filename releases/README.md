# TuxInDrive platform release channels

Each platform has a dedicated folder containing its signed `latest-v2.json`
update manifest, plus a visible `packages/` directory documenting the exact
durable download location. Large installers are kept as GitHub Release assets
because Windows, macOS and Android packages can exceed GitHub's 100 MiB
repository-file limit. Workflow artifacts are temporary build outputs and are
never used as update sources.

- `android/` — Android APK channel
- `macos/` — macOS DMG channel
- `windows/` — Windows x64 installer channel

Clients trust only expiring Ed25519-signed manifests, an approved TuxInDrive
download origin, a version-bound package filename, and the declared SHA-256.

A push to `main` builds verification artifacts only. A version tag such as
`v0.26.8` publishes the durable installers at:

`https://github.com/tpluharik/Tuxindrive/releases/tag/v0.26.8`

Maintainer signing, validation, publication, and rollback rules are documented
in [`docs/RELEASES.md`](../docs/RELEASES.md).
