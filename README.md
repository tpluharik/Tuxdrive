# TuxDrive

<p align="center"><img src="branding/tuxdrive-logo.png" width="180" alt="TuxDrive black-and-white penguin head logo"></p>

TuxDrive is a native Ubuntu desktop client for **Google Drive, Microsoft OneDrive, Dropbox, Box, pCloud, MEGA, Proton Drive, and Nextcloud**. It combines a GTK desktop interface with rclone's mature cloud backends, browser-based OAuth or provider authentication, and transfer engine.

📘 **[Complete illustrated user guide](docs/USER_GUIDE.md)**

🧪 **[Testing and release verification](docs/TESTING.md)** · 💡 **[Feature status and top-20 roadmap](docs/ROADMAP.md)** · 📝 **[Release history](CHANGELOG.md)**

## Community and development

TuxDrive is publicly readable. Direct repository writes remain restricted to maintainers, while everyone can participate through [Issues](https://github.com/tpluharik/Tuxdrive/issues), comments, forks, and pull requests.

- [Report a bug](https://github.com/tpluharik/Tuxdrive/issues/new?template=bug_report.yml)
- [Suggest a feature](https://github.com/tpluharik/Tuxdrive/issues/new?template=feature_request.yml)
- [Contribution guide](CONTRIBUTING.md)
- [Code of conduct](CODE_OF_CONDUCT.md)

Version 0.11.4 targets Ubuntu 26.04. The installer resolves desktop dependencies automatically and TuxDrive securely downloads and verifies its pinned transfer engine on first launch if the system does not already provide a compatible one.

### 0.9.0 release highlights

This release expands private collaboration: each shared folder can authorize multiple named devices with immediate key revocation, peer jobs coordinate expiring edit leases, local shares can be discovered without a directory server, and invitations can be exchanged as offline QR images. Existing single-peer 0.7/0.8 configurations migrate automatically. See the [changelog](CHANGELOG.md) and [roadmap](docs/ROADMAP.md).

### 0.10.0 desktop integration

Nautilus now shows TuxDrive status metadata and a right-click **TuxDrive** submenu for configured folders and their contents. It can show the job in TuxDrive, run its safety-checked synchronization, or open activity logs. Actions are sent to the single running application instance; if needed, Nautilus starts TuxDrive in the background and waits until its transfer runtime is ready.

Version 0.10.1 hardens that integration against disconnected FUSE endpoints: the extension performs no path-resolution I/O, unexpected streaming exits detach stale kernel mounts immediately, and startup recovers orphaned configured mounts before reconnecting.

Version 0.10.2 corrects the Nautilus 4 information-provider callback and packages dedicated green synchronized, blue streaming, and red error emblems, ensuring badges do not depend on the active Ubuntu icon theme.

Version 0.10.3 removes an exact GI minor-version pin that blocked the extension after Ubuntu 26.04 preloaded Nautilus 4.1. The extension now follows GNOME's host-loaded namespace model and supports both Nautilus 4.0 and 4.1.

Version 0.11.4 adds safe provider-web navigation from Nautilus and live badges for pending, synchronizing, synchronized, streaming, paused, and error states. Exact provider items open where a private item ID/path is available; unsupported backends fall back to their account root without creating a public share.

## What works

- eight providers: Google Drive, Microsoft OneDrive, Dropbox, Box, pCloud, MEGA, Proton Drive, and Nextcloud
- provider-native browser OAuth where available, plus guided credential or app-password configuration for MEGA, Proton Drive, and Nextcloud
- Proton Drive has explicit username, password, 2FA/OTP-secret, and two-password mailbox fields; credentials are protected in rclone's private configuration and the remote is tested before it is shown as connected
- Proton Drive opens a dedicated in-app 2FA challenge only when Proton requests a fresh code
- direct peer-to-peer collaborative folders between two TuxDrive computers over encrypted SFTP, with no intermediary file server
- multi-peer shared folders with named device keys, enable/disable controls, immediate revocation, and one authenticated endpoint per folder
- cooperative expiring edit leases that pause peer synchronization instead of overwriting a file another device is actively editing
- optional LAN multicast discovery with host-key fingerprint confirmation and no central discovery service
- offline QR invitation display and QR-image import; no online QR service receives pairing data
- generated Ed25519 identities, exchanged public keys, host-key pinning, editable IP/DNS address and port, and per-share folder selection
- OAuth 2.0 authorization in the default web browser—no cloud password is given to TuxDrive
- multiple accounts from either provider
- two-way synchronization with retained conflict copies
- per-job local version history and recycle recovery with configurable retention and one-click restore
- ransomware and mass-change protection that dry-runs established jobs, pauses suspicious rewrite/deletion bursts, and requires review before retry
- on-demand integrity audits with selected-path repair from either the local or cloud/peer side
- a conflict review center for choosing the authoritative version instead of silently overwriting differences
- client-side encrypted cloud vaults layered over an existing cloud account, including content, filename, and directory-name encryption
- rename and folder-move tracking to avoid unnecessary duplicate transfers
- download-only and upload-only mirror modes
- visual, lazy-loading cloud folder tree with multi-folder selective synchronization
- separate Google location browsing for My Drive, Shared with me, and every Shared Drive
- a FUSE virtual-drive mode with full VFS caching for files-on-demand behavior
- streaming drives expose the complete cloud tree without downloading file contents; opening a file fetches it in chunks and keeps a bounded local cache
- streaming mount health checks, automatic restart after an unexpected disconnect, and prevention of overlapping/non-empty mount points
- hybrid layouts: a streaming drive may live inside a normal synchronized tree and is automatically excluded from parent full/incremental synchronization
- automatic background synchronization at a configurable interval
- real-time incremental synchronization: local save callbacks and cloud delta polling transfer only changed paths
- debounced change handling, move/delete propagation, and full-sync fallback for simultaneous conflicts
- automatic suppression of LibreOffice, Microsoft Office, browser, editor, and partial-download temporary files
- pause/resume, sync now, cancellation, and tray controls
- native Nautilus 4 status/emblem integration and context actions for configured TuxDrive paths
- live Nautilus state transitions and safe **Open online/cloud folder** navigation without public-link creation
- launch at login, desktop notifications, daily diagnostic logs
- clickable per-job exception rules with add/remove controls, deletion safety ceiling, bandwidth limits, and conflict policy
- interactive blocked-file recovery: safely exclude the file or explicitly allow and retry
- explicit per-job opt-in for Google files flagged as malware or spam; disabled by default
- refresh/reconnect OAuth and account removal from the desktop UI
- import of existing Google Drive and OneDrive remotes from rclone
- live in-app activity and synchronization logs
- account, folder, and tray icons with connected, synchronizing, paused, and error states
- original TuxDrive penguin branding throughout the launcher, windows, tray, dialogs, installer, and documentation
- provider-specific icons for all eight services in account selection and connected-account views
- in-app repository update checks with HTTPS download, SHA-256 verification, and PolicyKit-authorized installation
- update window with visible checking, download percentage, verification, installation, success, and failure states
- one-click display-name editing that does not rename local or cloud folders
- streaming preflight diagnostics, stale FUSE mount recovery, detailed mount logs, and a 45-second connection window
- startup, application, thread-exception, and native crash logging

## Install on Ubuntu

Download the `.deb`, then run:

```bash
sudo apt install ./tuxdrive_0.11.4_all.deb
```

Open **TuxDrive** from the application menu. Choose **Connect account**, select a provider, and complete its guided authorization. Then add a local synchronized folder or virtual drive. The same visual cloud tree and multi-folder selection are used for all eight providers.

For a streaming drive, choose an empty mount folder. It may be a child of a normal synchronized tree, for example `~/Tuxdrive/tpluarikgdrive/Online`, and TuxDrive automatically excludes that subtree from the parent sync. A streaming drive must not be the parent of another sync job. Once connected, opening the mount folder loads the remote directory tree while file bodies remain online until opened.

For direct collaboration, open the network icon in TuxDrive. Both users copy and exchange their public identity keys through a trusted channel. One user selects **Share a folder**, enters the reachable IP/DNS address and port, and copies the invitation; the other selects **Connect to a peer**, loads that invitation, chooses a local folder, and connects. TuxDrive pins the host public key and verifies the peer before starting two-way synchronization. Internet connections may require router port forwarding or a peer-reachable VPN address.

This is the only installation command required: APT resolves the Ubuntu desktop libraries automatically, while TuxDrive installs a pinned, SHA-256-verified rclone engine into the user's private application directory when needed. Virtual drives require FUSE access; on managed systems an administrator may need to permit user mounts.

## Build from source

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
sh scripts/build-deb.sh
```

The installer is written to `dist/tuxdrive_0.11.4_all.deb`.

The current suite contains 69 automated tests covering transfer-engine bootstrap, configuration safety, recovery/version history, integrity auditing, synchronization, streaming and stale-mount recovery, provider setup and private online URLs, Proton 2FA, multi-peer authorization, edit leases, LAN/QR pairing, live Nautilus actions/emblems, packaging, diagnostics and verified updates. See [Testing and release verification](docs/TESTING.md) for details.

## Suggestions and roadmap

The [feature status and top-20 roadmap](docs/ROADMAP.md) records the safety foundation shipped in 0.8.0 and the multi-peer, lease, LAN-discovery, and QR-pairing work shipped in 0.9.0. Community discussion should use the feature-request issue form.

## Update from the app

Open **Settings → Check for updates**. TuxDrive reads `update/latest.json` from this repository, compares versions, downloads the listed `.deb` over HTTPS, verifies its SHA-256 checksum, and asks Ubuntu PolicyKit for authorization before installing it. No cloud credentials are involved. Restart TuxDrive after a successful update.

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
- Every synchronization enforces a configurable maximum deletion count. Established jobs also perform a non-destructive preview and pause suspicious mass changes.
- Local recovery data is stored under `~/.local/share/tuxdrive/recovery`; retention is configured per job. Cloud-side version backups are stored in the job remote's `.tuxdrive-versions` area.
- Encrypted vault passwords are protected in rclone's private configuration. They are not recoverable by TuxDrive; keep them in a password manager.

Back up important data before introducing any new synchronization tool. A mirror or bidirectional sync intentionally propagates changes and, within the configured safety ceiling, deletions.

## Parity and scope

TuxDrive implements the core desktop behaviors of the Windows clients through public provider APIs and rclone. It does not copy Microsoft or Google's proprietary source code, branding, telemetry, private protocols, or Office integration. Version 0.11.4 provides Nautilus 4.0/4.1 live status metadata, packaged state emblems, safe provider navigation and context menus, but does not yet provide a kernel-level placeholder API identical to Windows Cloud Files, per-file offline pinning, Office coauthoring hooks, or a standalone graphical cloud file content browser. Streaming-drive mode is the Linux-native files-on-demand equivalent.

## License

MIT. rclone is a separate program distributed under its own license.
