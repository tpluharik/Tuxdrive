# TuxDrive

TuxDrive is a native Ubuntu desktop client for **Google Drive** and **Microsoft OneDrive**. It combines a GTK desktop interface with rclone's mature cloud backends, browser-based OAuth, and transfer engine.

Version 0.2.0 targets Ubuntu 26.04. The installer resolves desktop dependencies automatically and TuxDrive securely downloads and verifies its pinned transfer engine on first launch if the system does not already provide one.

## What works

- Google Drive and Microsoft OneDrive Personal, Business, and supported SharePoint libraries
- OAuth 2.0 authorization in the default web browser—no cloud password is given to TuxDrive
- multiple accounts from either provider
- two-way synchronization with retained conflict copies
- download-only and upload-only mirror modes
- selective synchronization by cloud subfolder and independent local destination
- a FUSE virtual-drive mode with full VFS caching for files-on-demand behavior
- automatic background synchronization at a configurable interval
- pause/resume, sync now, cancellation, and tray controls
- launch at login, desktop notifications, daily diagnostic logs
- per-job exclusion patterns, deletion safety ceiling, bandwidth limits, and conflict policy
- refresh/reconnect OAuth and account removal from the desktop UI
- import of existing Google Drive and OneDrive remotes from rclone
- persistent tray icon with ready, synchronizing, and error states
- startup, application, thread-exception, and native crash logging

## Install on Ubuntu

Download the `.deb`, then run:

```bash
sudo apt install ./tuxdrive_0.2.0_all.deb
```

Open **TuxDrive** from the application menu. Choose **Connect account**, select Google Drive or Microsoft OneDrive, and complete authorization in your browser. Then add a local synchronized folder or virtual drive.

This is the only installation command required: APT resolves the Ubuntu desktop libraries automatically, while TuxDrive installs a pinned, SHA-256-verified rclone engine into the user's private application directory when needed. Virtual drives require FUSE access; on managed systems an administrator may need to permit user mounts.

## Build from source

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
sh scripts/build-deb.sh
```

The installer is written to `dist/tuxdrive_0.2.0_all.deb`.

## Crash and startup diagnostics

TuxDrive logs before importing any GUI libraries, so even early startup failures leave evidence:

- `~/.local/state/tuxdrive/startup.log` — launcher output and missing-runtime errors
- `~/.local/state/tuxdrive/tuxdrive.log` — rotating application and synchronization lifecycle log
- `~/.local/state/tuxdrive/crash.log` — uncaught Python/thread exceptions and native fault traces
- `~/.cache/tuxdrive/logs/` — individual rclone synchronization logs

Run `tuxdrive --diagnostics` to print the main diagnostic locations.

## OAuth application configuration

TuxDrive can use rclone's default OAuth application configuration for personal installations. For production distribution or organizational deployment, register dedicated desktop OAuth applications and enter the client ID and secret in the connection dialog:

### Google Drive

1. Create a project in Google Cloud Console and enable Google Drive API.
2. Configure the OAuth consent screen and required Drive scopes.
3. Create an OAuth client of type **Desktop app**.
4. Add the intended users while the consent screen is in testing, or complete Google's verification/publishing process.

### Microsoft OneDrive

1. Register a public/native client in Microsoft Entra ID.
2. Allow the appropriate account audience (organizational, personal, or both).
3. Add delegated Microsoft Graph file permissions and `offline_access`.
4. Enable the native-client redirect/loopback flow required by desktop authorization.

Do not commit client secrets, access tokens, refresh tokens, or an rclone configuration file to this repository.

## Storage and security

- TuxDrive settings live in `~/.config/tuxdrive/config.json` with mode `0600`.
- OAuth tokens remain in rclone's protected config (normally `~/.config/rclone/rclone.conf`).
- Operational logs live under `~/.cache/tuxdrive/logs` and do not contain a config dump.
- First two-way synchronization merges both sides and prefers the newer version for an initial same-path collision. Later unresolved conflicts retain renamed copies.
- Every synchronization enforces a configurable maximum deletion count.

Back up important data before introducing any new synchronization tool. A mirror or bidirectional sync intentionally propagates changes and, within the configured safety ceiling, deletions.

## Parity and scope

TuxDrive implements the core desktop behaviors of the Windows clients through public provider APIs and rclone. It does not copy Microsoft or Google's proprietary source code, branding, telemetry, private protocols, or Office integration. Version 0.2.0 does not yet provide Nautilus per-file badges/context menus, a kernel-level placeholder API identical to Windows Cloud Files, Office coauthoring hooks, or a graphical cloud file browser. Virtual-drive mode is the Linux-native files-on-demand equivalent.

## License

MIT. rclone is a separate program distributed under its own license.
