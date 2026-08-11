# TuxDrive

<p align="center"><img src="branding/tuxdrive-logo.png" width="180" alt="TuxDrive black-and-white penguin head logo"></p>

TuxDrive is a native Ubuntu desktop client for **Google Drive, Microsoft OneDrive, Dropbox, Box, pCloud, MEGA, Proton Drive, Nextcloud, and GitHub repositories**. It combines a GTK desktop interface with rclone's mature cloud backends, system Git, browser-based OAuth or provider authentication, and transfer engine.

📘 **[Complete illustrated user guide](docs/USER_GUIDE.md)**

🧪 **[Testing and release verification](docs/TESTING.md)** · 🛡️ **[Security hardening and upgrade guide](docs/SECURITY_HARDENING.md)** · 💡 **[Feature status and roadmap](docs/ROADMAP.md)** · 📝 **[Release history](CHANGELOG.md)**

🔐 **[Security policy, trust boundaries, and vulnerability reporting](SECURITY.md)**

## Community and development

TuxDrive is publicly readable. Direct repository writes remain restricted to maintainers, while everyone can participate through [Issues](https://github.com/tpluharik/Tuxdrive/issues), comments, forks, and pull requests.

- [Report a bug](https://github.com/tpluharik/Tuxdrive/issues/new?template=bug_report.yml)
- [Suggest a feature](https://github.com/tpluharik/Tuxdrive/issues/new?template=feature_request.yml)
- [Contribution guide](CONTRIBUTING.md)
- [Code of conduct](CODE_OF_CONDUCT.md)

Version 0.20.9 targets Ubuntu 24.04/26.04 and Debian 12/13 GNOME on amd64 and arm64. Streaming mounts remain files-on-demand after reconnect: saved pins are verified against rclone's real mount-relative cache objects without downloading cloud content, while explicit **Keep available offline** and **Free local space (make online-only)** actions control each selected item. A selected file hydrates only that exact file; a stalled provider read is cancelled and retried instead of leaving a permanent pending badge. The Nautilus provider retains only URI keys, reacquires current cached file objects for badge updates, and emits its dedicated menu-refresh signal, so localization cannot suppress the TuxDrive menu. Package upgrades retire an older in-memory TuxDrive process before the new version accepts Nautilus actions. TuxDrive also retains editable internal folder groups, GitHub synchronization, the 0.19 security baseline, unbranded six-state Nautilus badges, searchable offline documentation and persistent English, German, French, Spanish, Arabic and Hebrew localization.

### Current security baseline

- Python/PyPI installations require `cryptography>=50.0.0,<51` following PYSEC-2026-3552, PYSEC-2026-3553, PYSEC-2026-3554, and GHSA-537c-gmf6-5ccf. Ubuntu `.deb` installations use Ubuntu's maintained `python3-cryptography` package so official security backports remain valid.
- CI blocks releases on high-severity Bandit findings or audited vulnerable Python dependencies and produces a CycloneDX SBOM with the Debian installer.
- The complete control inventory, upgrade procedure, credential migration behavior, residual risks, and operator checklist are in the [security-hardening guide](docs/SECURITY_HARDENING.md).

The following controls are enforced in 0.20.9:

- Signed and expiring update manifests are verified in both the desktop process and a fixed privileged helper. The helper stages the package in a root-only directory and rechecks its digest and Debian identity before APT executes it.
- Tor-only/no-public-IP shares bind SFTP to loopback, and protocol-v5 invitations carry an explicit transport allowlist so direct-only and no-relay policies cannot silently fall back.
- Incremental download, recovery, integrity repair, offline hydration, and block-delta paths reject symlinked parents/targets outside their configured root.
- Block-delta instructions are signed with the sender's Ed25519 peer identity and accepted only from an authorized device; unavailable delta signing safely falls back to a complete file transfer.
- Encrypted profile backups use a stronger scrypt work factor and 14-character minimum for new backups while retaining read compatibility with version-1 profiles.
- OAuth/configuration subprocesses disable same-user process inspection on Linux; logs/configuration files use explicit private permissions; the launcher runs Python in isolated mode.
- Provider tokens/passwords are migrated into rclone's authenticated encrypted configuration; its random key is retrieved from GNOME Secret Service and never committed to the application JSON. Independently encrypted advanced-user rclone configurations are preserved.
- Each authorized peer key receives an isolated listener and authorization file. Read-only/receive-only restrictions are applied by the server, while send-only and one-time-drop devices are rooted in private inboxes rather than the shared workspace.
- Collaborative operation logs and ODT/ODS imports have explicit count, byte, compression-ratio and schema limits; unsafe XML entities are rejected before document processing.
- GitHub synchronization accepts only credential-free `github.com` HTTPS or SSH clone URLs, validates branch names, disables interactive credential prompts, and delegates secrets to the system SSH agent or Git credential helper.

### 0.20.9 online-only/offline availability, groups and GitHub

- Right-click a streamed file, folder, or drive root and choose **Keep available offline**. Blue arrows remain while TuxDrive explicitly reads the complete selection into the durable VFS cache; a green check appears only after local verification. Reconnects never start that download automatically. Choose **Free local space (make online-only)** to remove the rule and cached bytes. A child can be made online-only even when its parent is pinned. The streaming-job button in TuxDrive provides a whole-drive fallback if Nautilus integration is unavailable.
- Pinning or releasing one item never reconnects the streaming mount. File rules are exact; folder and drive-root rules are recursive only when those objects are explicitly selected. The stable retention cache is released through the per-item or whole-drive online-only controls.
- Select **New group** to create list-only groups such as Work, Personal, or Customers. Use **Group** on a synchronized folder to move its entry. Renaming/deleting groups never moves or deletes files.
- Select **Connect account → GitHub**, enter a credential-free repository URL, branch, local folder, mode, and commit identity. Two-way mode automatically commits local changes, fetches, rebases and pushes. Configure an SSH key or system Git credential helper for private/write access.

### 0.15.0 private Onion workspaces

- Publish a peer workspace as a persistent or ephemeral Tor v3 Onion Service without opening an inbound public port.
- Issue and revoke a separate Onion client credential for each named device, carried by the existing offline invitation/QR workflow and protected again by pinned SSH identities.
- Enforce direct-only or Tor-only operation plus no-relay, no-public-IP-discovery and never-provider-cloud restrictions. TuxDrive records a blocked audit event instead of silently switching transports.
- Configure advanced bridge/pluggable-transport profiles without copying bridge material into invitations, command lines, or application logs.

### 0.9.0 release highlights

This release expands private collaboration: each shared folder can authorize multiple named devices with immediate key revocation, peer jobs coordinate expiring edit leases, local shares can be discovered without a directory server, and invitations can be exchanged as offline QR images. Existing single-peer 0.7/0.8 configurations migrate automatically. See the [changelog](CHANGELOG.md) and [roadmap](docs/ROADMAP.md).

### 0.10.0 desktop integration

Nautilus now shows TuxDrive status metadata and a right-click **TuxDrive** submenu for configured folders and their contents. It can show the job in TuxDrive, run its safety-checked synchronization, or open activity logs. Actions are sent to the single running application instance; if needed, Nautilus starts TuxDrive in the background and waits until its transfer runtime is ready.

Version 0.10.1 hardens that integration against disconnected FUSE endpoints: the extension performs no path-resolution I/O, unexpected streaming exits detach stale kernel mounts immediately, and startup recovers orphaned configured mounts before reconnecting.

Version 0.10.2 corrects the Nautilus 4 information-provider callback and packages dedicated green synchronized, blue streaming, and red error emblems, ensuring badges do not depend on the active Ubuntu icon theme.

Version 0.10.3 removes an exact GI minor-version pin that blocked the extension after Ubuntu 26.04 preloaded Nautilus 4.1. The extension now follows GNOME's host-loaded namespace model and supports both Nautilus 4.0 and 4.1.

Version 0.19.2 replaces the penguin status overlays with compact, high-contrast functional badges. Synchronized, synchronizing, files-on-demand, paused, pending, and error use a green check, blue rotation arrows, teal cloud/download, purple pause, amber clock/diamond, and red exclamation/octagon respectively. Color, silhouette, and glyph all differ, so status is not communicated by color alone.

### 0.12.0 efficient transfer and connectivity policies

Version 0.12.0 adds verified block-level delta transactions for direct peer updates, automatic UPnP/NAT-PMP traversal, an optional SSH reverse-tunnel relay that forwards encrypted bytes without storing file content, per-file streaming availability controls in Nautilus, an optional default-on Nautilus integration flag, and metered-network/battery/schedule policies. Policy mode defaults to **Maximum usage**, preserving unrestricted behavior until the user explicitly enables controls.

### 0.13.0 controlled collaboration and operational visibility

Version 0.13.0 adds read/write, read-only, send-only and receive-only peer invitations; expiring upload-only encrypted file drops; a private local peer/sync audit timeline; a provider capability matrix that adapts mode and sharing controls; and a consolidated health dashboard showing running, mounted, callback, last-run and failure state. Existing peer invitations/configurations migrate to read/write behavior.

### 0.14.0 encrypted profiles and device migration

TuxDrive Profile links the application to an existing Google Drive, OneDrive, Dropbox, Box, or pCloud OAuth account and stores a locally encrypted configuration backup in that user-owned cloud. On a new device, connect the same provider and restore from Settings. AES-256-GCM authentication and a memory-hard scrypt key derivation protect the bundle; its password never leaves the device. OAuth tokens and peer private keys remain excluded unless the user explicitly enables sensitive full-device migration.

## What works

- eight providers: Google Drive, Microsoft OneDrive, Dropbox, Box, pCloud, MEGA, Proton Drive, and Nextcloud
- encrypted TuxDrive Profile backup stored in a linked OAuth account, with discovery after provider connection and password-protected restore on a new device
- configuration-only backup by default; OAuth credentials and peer private keys require an explicit sensitive-migration opt-in
- provider-native browser OAuth where available, plus guided credential or app-password configuration for MEGA, Proton Drive, and Nextcloud
- Proton Drive has explicit username, password, 2FA/OTP-secret, and two-password mailbox fields; credentials are protected by rclone configuration encryption backed by GNOME Secret Service and the remote is tested before it is shown as connected
- Proton Drive opens a dedicated in-app 2FA challenge only when Proton requests a fresh code
- direct peer-to-peer collaborative folders between two TuxDrive computers over encrypted SFTP, with no intermediary file server
- block-level peer delta transactions signed by the sender identity, with BLAKE2 block verification, final SHA-256 validation, atomic receiver replacement, and safe full-file fallback
- automatic UPnP/NAT-PMP port mapping and optional encrypted reverse-tunnel relay; the relay forwards ciphertext and stores no file content or TuxDrive keys
- multi-peer shared folders with named device keys, enable/disable controls, immediate revocation, and an isolated authenticated server endpoint per device
- per-device read/write, read-only, send-only and receive-only roles enforced at both transfer and SFTP server boundaries; send-only devices see only their dedicated inbox
- expiring, dedicated-root encrypted file-drop invitations that cannot browse the containing workspace and retire after the first received file
- a private append-only peer and synchronization audit timeline with job, result, peer, path, and bounded diagnostic detail
- an operations dashboard showing sync/mount/callback health, recent failures, peer access mode, audit events, and provider capabilities
- a provider capability matrix for streaming, polling, hashes, server moves, share links and versions; unsupported modes/actions are disabled with an explanation
- cooperative expiring edit leases that pause peer synchronization instead of overwriting a file another device is actively editing
- optional LAN multicast discovery with host-key fingerprint confirmation and no central discovery service
- offline QR invitation display and QR-image import; no online QR service receives pairing data
- generated Ed25519 identities, exchanged public keys, host-key pinning, editable IP/DNS address and port, and per-share folder selection
- OAuth 2.0 authorization in the default web browser for Google Drive, OneDrive, Dropbox, Box, and pCloud—no provider password is given to TuxDrive for those OAuth flows
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
- Nautilus **Keep available offline** and **Free local space (make online-only)** controls for individual streamed files and folders
- streaming mount health checks, automatic restart after an unexpected disconnect, and prevention of overlapping/non-empty mount points
- hybrid layouts: a streaming drive may live inside a normal synchronized tree and is automatically excluded from parent full/incremental synchronization
- automatic background synchronization at a configurable interval
- real-time incremental synchronization: local save callbacks and cloud delta polling transfer only changed paths
- debounced change handling, move/delete propagation, and full-sync fallback for simultaneous conflicts
- automatic suppression of LibreOffice, Microsoft Office, browser, editor, and partial-download temporary files
- pause/resume, sync now, cancellation, and tray controls
- native Nautilus 4 status/emblem integration and context actions for configured TuxDrive paths
- Nautilus integration can be disabled in Settings and is enabled by default
- optional metered-network, battery-threshold and daily schedule policies; unrestricted maximum transfer usage remains the default
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
- in-app repository update checks with an Ed25519-signed expiring manifest, HTTPS download, SHA-256 verification, Debian identity check, and an independently verifying root-side PolicyKit helper
- update window with visible checking, download percentage, verification, installation, success, and failure states
- one-click display-name editing that does not rename local or cloud folders
- streaming preflight diagnostics, stale FUSE mount recovery, detailed mount logs, and a 45-second connection window
- startup, application, thread-exception, and native crash logging

## Install on Ubuntu

Download the `.deb`, then run:

```bash
sudo apt install ./tuxdrive_0.20.9_all.deb
```

Open **TuxDrive** from the application menu. Choose **Connect account**, select a provider, and complete its guided authorization. Then add a local synchronized folder or virtual drive. The same visual cloud tree and multi-folder selection are used for all eight cloud providers; GitHub uses a dedicated repository/branch/local-folder dialog.

For a streaming drive, choose an empty mount folder. It may be a child of a normal synchronized tree, for example `~/Tuxdrive/tpluarikgdrive/Online`, and TuxDrive automatically excludes that subtree from the parent sync. A streaming drive must not be the parent of another sync job. Once connected, opening the mount folder loads the remote directory tree while file bodies remain online until opened.

For direct collaboration, open the network icon in TuxDrive. Both users copy and exchange their public identity keys through a trusted channel. One user selects **Share a folder**, enters the reachable IP/DNS address and port, and copies the invitation; the other selects **Connect to a peer**, loads that invitation, chooses a local folder, and connects. TuxDrive pins the host public key and verifies the peer before starting two-way synchronization. Automatic NAT mapping is attempted by default. Where direct reachability is impossible, configure an SSH relay account and public forwarding port; the relay carries nested encrypted SFTP traffic without receiving file keys or retaining content.

APT installs the secure graphical core and normally installs supported optional recommendations. The same package adapts when an integration is unavailable; check the actual logged-in desktop with `tuxdrive --system-check`. TuxDrive installs a pinned, SHA-256-verified rclone engine into the user's private application directory when needed. Virtual drives require FUSE access; on managed systems an administrator may need to permit user mounts. See the [distribution compatibility table and adaptive installation guide](docs/PLATFORM_SUPPORT.md).

## Build from source

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
sh scripts/build-deb.sh
```

The installer is written to `dist/tuxdrive_0.20.9_all.deb`. TuxDrive publishes Debian packages only.

### Local-first collaborative documents

Open **Peer-to-peer sharing → Collaborate → Open collaborative editor**. Markdown and plain text changes are stored as immutable per-device CRDT operations under `.tuxdrive-collaboration`, so offline peers converge after the containing folder synchronizes. **Merge peer changes** records local edits and merges remote operations; **Export checkpoint** updates the ordinary `.md`/`.txt` file for any editor. Optional presence is AES-256-GCM encrypted, expires quickly and is not copied to the long-lived audit timeline. Comments, suggestions, tracked-change records, approvals, mentions and tasks are immutable workspace review events.

ODT paragraphs/styles/comments/tracked-change markers and ODS cells/formulas are imported structurally. Deterministic export retains the original `content.xml` inside the snapshot for recovery and warns where unsupported inline features may flatten. DOCX, XLSX, PDF and unknown binary formats deliberately remain under edit leases, local versions and review rather than making an unsafe real-time claim.

### Documentation and language

Select the **?** button in the top bar to open the searchable offline documentation center. Its 18 chapters describe accounts and OAuth, visual folder selection, synchronization modes, streaming/offline files, every job action, exceptions, recovery, integrity/conflicts, peer/Tor sharing, collaborative editing, encrypted migration, Nautilus, updates, transfer policies, diagnostics and safe removal. Each chapter includes practical user steps.

The flag selector switches **English**, **German**, **French**, **Spanish**, **Arabic**, or **Hebrew** immediately and stores the choice privately. Arabic and Hebrew labels and documentation use right-to-left text flow without moving the interface controls. Provider and rclone diagnostics may remain in their source language so technical evidence is not mistranslated.

The current suite contains 161 automated tests, including bounded and retried stalled FUSE hydration, upgrade-process isolation, lexical single-file action routing, sibling-file rule isolation, real mount-relative VFS cache verification, legacy pin migration, background-menu isolation, delayed exact cache publication, stable non-remounting retention, URI-based pending-to-verified Nautilus menu/badge refresh, nested online-only exceptions, local no-download reconnect verification, root/item hydration and rollback, GitHub guards, synchronized-folder groups, update trust, peer isolation, hostile ODF/CRDT input and six-language help parity. See [Testing and release verification](docs/TESTING.md) for details.

## Suggestions and roadmap

The [feature status and top-40 roadmap](docs/ROADMAP.md) records shipped safety and synchronization work plus the proposed path toward optional Tor/onion transport, reviewed group security, self-hosted encrypted services and local-first multi-peer document collaboration—described as a long-term “Signal for files and cooperation” direction rather than a current security claim. Community discussion should use the feature-request issue form.

## Update from the app

Open **Settings → Check for updates**. TuxDrive verifies the signed manifest and download before asking for authorization. A fixed root-side helper then obtains the signed manifest independently, copies the untrusted package into a root-only staging directory through a no-follow descriptor, and rechecks its digest and Debian identity before APT runs. No user-supplied digest or cloud credential is trusted by the helper. Restart TuxDrive after a successful update.

**0.18.1 → 0.19.1 → current trust-root transition:** 0.18.1 verifies an original-key-signed legacy manifest and first installs the fixed 0.19.1 bridge. Version 0.19.1 switches to the separately signed v2 channel and can then install 0.20.9 and later releases. On 0.18.1, run the in-app update check a second time after restarting 0.19.1. Never bypass a signature error; a continuing failure means the manifest is stale, intercepted, or the installed package predates this bridge.

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
- OAuth tokens and credential-provider secrets remain in rclone's encrypted config (normally `~/.config/rclone/rclone.conf`). TuxDrive stores the random config password in GNOME Secret Service and retrieves it through a password command rather than application JSON or process arguments.
- Operational logs live under `~/.cache/tuxdrive/logs` and do not contain a config dump.
- First two-way synchronization merges both sides and prefers the newer version for an initial same-path collision. Later unresolved conflicts retain renamed copies.
- Every synchronization enforces a configurable maximum deletion count. Established jobs also perform a non-destructive preview and pause suspicious mass changes.
- Local recovery data is stored under `~/.local/share/tuxdrive/recovery`; retention is configured per job. Cloud-side version backups are stored in the job remote's `.tuxdrive-versions` area.
- Encrypted vault passwords are protected in rclone's private configuration. They are not recoverable by TuxDrive; keep them in a password manager.
- Upgrading from 0.15.0 or earlier automatically migrates an unencrypted managed rclone configuration into authenticated encrypted form when GNOME Secret Service is available. Existing independently encrypted advanced-user configurations are preserved.
- The updater accepts only a non-expired Ed25519-signed manifest, an approved repository URL, the declared SHA-256 digest, and a Debian package whose embedded name/version match the requested release.

For the complete threat boundaries, sensitive file locations, dependency response, verification commands, backup advice, and remaining peer-server limitation, read [Security hardening and secure operation](docs/SECURITY_HARDENING.md).

Back up important data before introducing any new synchronization tool. A mirror or bidirectional sync intentionally propagates changes and, within the configured safety ceiling, deletions.

## Parity and scope

TuxDrive implements the core desktop behaviors of the Windows clients through public provider APIs and rclone. It does not copy Microsoft or Google's proprietary source code, branding, telemetry, private protocols, or Office integration. Version 0.13.0 provides Nautilus 4.0/4.1 live status metadata, packaged state emblems, safe provider navigation, context menus, persistent per-file/per-folder offline availability controls, adaptive provider controls and an operational dashboard. It does not provide a kernel-level placeholder API identical to Windows Cloud Files or Office coauthoring hooks. Streaming-drive mode is the Linux-native files-on-demand equivalent.

## License

MIT. rclone is a separate program distributed under its own license.
