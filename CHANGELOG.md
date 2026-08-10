# TuxDrive release history

This changelog summarizes user-visible releases. Detailed operation, safety limitations, and recovery instructions are maintained in the [user guide](docs/USER_GUIDE.md).

## 0.10.0 — Nautilus desktop integration

- Added a native Nautilus 4 extension for Ubuntu 26.04.
- Added a TuxDrive context submenu on configured local folders and their contents.
- Added safe **Show in TuxDrive**, **Synchronize this TuxDrive folder now**, and **Open TuxDrive activity logs** actions.
- Added Nautilus status metadata and synchronized/error emblems for configured paths.
- Routed actions through the running TuxDrive application so Nautilus never starts a competing transfer engine; startup-time requests wait for runtime readiness.
- Added extension packaging, dependency resolution, documentation, and automated coverage.

## 0.9.0 — multi-peer collaboration, leases, and local pairing

- Added multiple named authorized devices per shared folder, including enable/disable controls and immediate public-key revocation when the share is saved.
- Migrates legacy single-key peer shares automatically.
- Added cooperative expiring edit leases for peer jobs; active foreign leases pause incremental transfers and complete reconciliations.
- Added optional LAN-only multicast discovery without a central directory or intermediary storage.
- Added pinned host-key fingerprint presentation and explicit verification guidance for discovered peers.
- Added offline QR invitation generation and QR-image import using local `qrencode` and `zbarimg` tools installed by the Debian package.
- Added invitation protocol v2 with share identity and lease duration while retaining v1 import compatibility.
- Expanded automated coverage to 61 tests.

## 0.8.0 — recovery, integrity, and encrypted vaults

- Added per-job local version history and recycle recovery with configurable retention and one-click restore.
- Added dated backup handling for replaced/deleted data during normal synchronization.
- Added ransomware and mass-change protection for full-sync previews and incremental callback batches.
- Added automatic pausing when configured path/percentage/deletion thresholds or ransomware-like filename patterns are detected.
- Added non-destructive integrity audits and selected-path repair from an explicitly chosen local or cloud/peer authority.
- Added a conflict review center for content mismatches.
- Added client-side encrypted cloud vaults with encrypted content, file names, and directory names over an existing provider account.
- Added recovery, protection, audit, conflict, and vault controls to the GTK interface.
- Expanded automated coverage to 56 tests and updated the Ubuntu 26.04 Debian package and update manifest.

## 0.7.0 — direct encrypted peer collaboration

- Added direct peer-to-peer shared folders over authenticated encrypted SFTP with no intermediary file storage.
- Added generated Ed25519 identities, exchanged public keys, pinned host verification, and editable IP/DNS/port settings.
- Added Proton Drive credential setup and an on-demand in-app 2FA challenge.

## 0.6.x — provider expansion and authentication hardening

- Expanded the supported cloud set to Google Drive, OneDrive, Dropbox, Box, pCloud, MEGA, Proton Drive, and Nextcloud.
- Added guided provider credentials where browser OAuth is unavailable.
- Added remote validation before an account is shown as connected.

## 0.5.x — branding and verified updates

- Added TuxDrive penguin branding and provider-specific account icons.
- Added in-app update checking, visible progress, SHA-256 package verification, and PolicyKit-authorized installation.

## 0.4.x — selective sync, callbacks, and streaming

- Added the visual cloud folder tree, multi-folder selection, in-app activity logs, and activity-state icons.
- Added incremental saved-file callbacks, temporary-file suppression, moves/deletions, and clickable exception rules.
- Added FUSE files-on-demand streaming, hybrid synchronized/streamed layouts, mount diagnostics, and restart handling.

## 0.2.x–0.3.x — desktop runtime and synchronization foundation

- Added the GTK application, tray status, crash/startup diagnostics, OAuth account setup, and Debian packaging.
- Added two-way/one-way synchronization, conflict policies, deletion limits, Google location discovery, and transfer-engine compatibility handling.
