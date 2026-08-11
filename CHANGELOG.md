# TuxDrive release history

This changelog summarizes user-visible releases. Detailed operation, safety limitations, and recovery instructions are maintained in the [user guide](docs/USER_GUIDE.md).

## 0.20.0 — reliable offline pinning, folder groups and GitHub sync

- Fixed **Always keep available offline** for both streaming-drive roots and nested items, with rollback on failed hydration and symlink-safe path handling.
- Added per-item Nautilus hydration metadata: blue synchronization arrows while content downloads and a green check with **Available offline** only after full hydration finishes.
- Added editable internal groups for synchronized folders. Creating, renaming, moving entries between, or deleting groups changes only TuxDrive list organization and never moves local/cloud files.
- Added GitHub repository synchronization through system Git: clone, automatic commit, fetch, safe rebase and push for two-way jobs; fast-forward-only download mode; guarded upload-only mode; actionable conflict/authentication failures.
- GitHub credentials remain with the system SSH agent or Git credential helper. TuxDrive rejects credential-bearing repository URLs and stores no GitHub token.
- Added GitHub URL/branch validation, offline hydration, group migration, package/icon and Git command regression coverage. The complete suite now contains 132 tests.

## 0.19.2 — visible functional Nautilus status badges

- Replaced the penguin-branded Nautilus status emblems with six compact functional badges designed to remain readable at normal Files icon sizes.
- Assigned every state a dedicated color, silhouette, and white foreground symbol: green check for synchronized, blue rotation arrows for synchronizing, teal cloud/download for files on demand, purple pause bars for paused, amber clock/diamond for pending, and red exclamation/octagon for error.
- Kept the existing Nautilus state mapping, live cache refresh, context actions, provider identity, and application branding unchanged.
- Added an SVG regression test that rejects a reused state color, missing accessibility description, wrong state identity, or return of the former penguin palette.
- Updated the illustrated user guide, roadmap, release packaging, and signed v2 update channel.

## 0.19.1 — signed updater trust bridge

- Restored automatic updates for 0.18.1 without weakening signature checks. The legacy `latest.json` channel remains signed by the original offline key and points only to 0.19.1.
- Moved 0.19.1 and later clients to the separately signed `latest-v2.json` channel using the rotated offline key, preventing a single static manifest from being interpreted under two trust roots.
- Added release tests that verify both manifests target the exact current Debian package and validate under their respective Ed25519 public keys.
- Kept the complete 0.19.0 critical/high remediation unchanged.

## 0.19.0 — critical/high security remediation

- Closed the in-app updater's privilege-boundary race. A fixed PolicyKit helper now independently retrieves and verifies the signed manifest, copies the user-owned package through a no-follow file descriptor into a root-only directory, verifies the immutable copy's SHA-256 and Debian identity, and only then invokes APT.
- Replaced shared peer authorization with a distinct SFTP listener and one-key authorization file per enabled device. Read-only/receive-only endpoints are server read-only; send-only devices receive an isolated inbox instead of workspace visibility.
- Moved one-time drops to dedicated per-invitation roots and ports, so a modified SFTP client cannot browse the containing workspace while its invitation remains active.
- Added persistent per-device endpoint allocation and multi-port Onion publication while retaining host-key pinning, direct/Tor policies and existing read/write behavior.
- Bounded collaborative operation counts and JSON size/schema, replaced recursive CRDT traversal, and rejected unsafe operation graphs.
- Hardened ODT/ODS import against ZIP bombs, duplicate/traversal entries, excessive archive/XML sizes and unsafe XML entities by using `defusedxml` and explicit resource limits.
- Added eight focused updater, peer-isolation, archive and deep/cyclic-CRDT regression tests; the complete suite now contains 125 tests.
- Documented the remaining medium hardening work in the roadmap and updated the repository and in-app security guidance.
- Rotated the offline update signing trust root. Version 0.19.1 subsequently introduced a separately signed legacy bridge after the original release key was recovered from protected storage.

## 0.18.1 — Arabic and Hebrew localization

- Added complete Arabic and Hebrew primary-interface translations and all 18 offline documentation chapters.
- Added explicit right-to-left rendering for Arabic/Hebrew labels, help search, topic titles and documentation bodies while retaining the established application layout and control positions.
- Extended localization parity and directionality regression tests to all six supported languages.

## 0.18.0 — in-app documentation and multilingual interface

- Added an offline, searchable Help Center with 18 chapters covering every primary cloud, streaming, recovery, peer, privacy, collaboration, migration, update and diagnostics workflow.
- Added persistent English, German, French and Spanish language selection from a flag menu in the top bar.
- Localized primary navigation, account and synchronized-folder actions without restarting or interrupting background transfers.
- Documented practical user HOWTOs in the app and repository, including safety boundaries and troubleshooting guidance.
- Added localization fallback, translated-help completeness and packaging regression tests.

## 0.17.0 — local-first collaborative documents

- Added an operation-based CRDT for offline multi-peer Markdown/plain-text editing with deterministic convergence and explicit interoperable checkpoints.
- Stored collaboration state separately as immutable per-device operation files suitable for the existing folder synchronizer.
- Added optional AES-256-GCM authenticated, expiring cursor/selection presence that is disabled without a shared key and excluded from long-lived audit logs.
- Added immutable comments, suggestions, tracked-change records, mentions, approvals and file tasks.
- Added structured experimental ODT and ODS import/export with deterministic archives, formula/style metadata, original XML recovery and round-trip warnings.
- Kept DOCX, XLSX, PDF and unproven binary formats in safe lease/version/review mode.
- Added the GTK collaborative editor under peer sharing, seven focused tests and updated documentation.
- Removed the experimental macOS package workflow and sources; release CI now produces the adaptive `.deb` and SBOM only.
- Published the signed 0.17.0 in-app update manifest and added a CI regression test that rejects manifest/package/version drift.

## 0.16.0 — adaptive Debian/GNOME packaging

- Added an experimental macOS 13+ Apple-silicon `.app`/`.pkg` CI build with Keychain-backed rclone configuration encryption, LaunchAgent login startup, native URL opening, pinned macOS rclone bootstrap and optional macFUSE handling. Finder integration, notarization and the automatic updater are not yet available.
- Added install-time and user-session host capability discovery with human-readable and JSON output through `tuxdrive --system-check`.
- Reduced the mandatory package set to the secure GTK/Secret-Service core and moved Nautilus, tray, FUSE, Tor, NAT, network-policy, QR, notification and update integrations to recommendations.
- Added per-feature availability and remediation reporting so an absent optional integration does not block unrelated cloud synchronization.
- Declared amd64 and arm64 as the supported verified-rclone bootstrap architectures and documented the current Debian, Ubuntu, GNOME and file-manager boundaries.
- Added packaging and platform-discovery regression tests and included the installation capability snapshot in `/var/lib/tuxdrive`.

- Raised Python-package installations to `cryptography` 50.0.0 or newer after the 0.15.1 dependency audit identified PYSEC-2026-3552, PYSEC-2026-3553, PYSEC-2026-3554, and GHSA-537c-gmf6-5ccf in the previously allowed 46.x series.
- Kept Ubuntu `.deb` installations on the distribution-maintained `python3-cryptography` package so Ubuntu security backports remain installable without an impossible upstream-version constraint.
- Updated release packaging, SBOM paths, installer metadata and documentation to 0.16.0.

## 0.15.1 — comprehensive security hardening

- Added Ed25519-signed, expiring update manifests, bounded downloads, Debian package identity checks, and an external release-signing trust root.
- Bound Tor-only and no-public-IP peer endpoints to loopback and added explicit invitation transport allowlists that remove forbidden relay/direct fallback.
- Added descriptor-walk path confinement to reject symlink escapes during incremental transfer, delta application, recovery, integrity repair, and offline hydration.
- Signed block-delta instructions with the sender's Ed25519 identity, authorized signers on receipt, bounded delta resources, and retained safe full-transfer fallback.
- Fixed peer-role synchronization mapping; immediately rebuilds authorization and terminates sessions after consuming a one-time drop.
- Randomized and readiness-tested per-remote Tor SOCKS listeners, isolated Tor SSH wrappers, restricted pluggable-transport executables, strict relay host verification, and NAT mapping cleanup.
- Raised the cryptography dependency floor to 46.0.5, required rclone 1.75.0+, strengthened new profile backups to scrypt N=131072 with a 14-character minimum, bounded profiles, and excluded bridge material from non-sensitive backups.
- Added automatic rclone configuration encryption backed by GNOME Secret Service, while preserving independently encrypted advanced-user configurations.
- Hardened log/config permissions, sensitive child-process visibility, Python launcher isolation, Nautilus executable paths, CI action pinning, dependency auditing, static analysis, and SBOM generation.
- Retained peer sharing and one-time drops. Per-key server-side role/drop isolation remains explicitly deferred to the planned peer server authorization layer.

## 0.15.0 — Tor transport and fail-closed workspace privacy

- Added isolated Tor v3 Onion Services for peer workspaces with persistent or ephemeral service identity and no automatic clearnet fallback.
- Added per-device Tor v3 client authorization, invitation/QR transfer, key rotation by re-issuance, revocation files, and Tor reload handling alongside existing SSH identity and host-key checks.
- Added workspace transport policies for direct-only, Tor-only, no-relay, no-public-IP-discovery, and never-provider-cloud operation; violations stop or pause traffic and enter the private audit timeline.
- Added bridge and pluggable-transport profiles stored only in private Tor configuration, excluded from invitations, subprocess arguments, and TuxDrive logs.
- Added GTK peer-workspace controls, protocol-v5 invitations, migration-safe configuration fields, Tor/torsocks/obfs4 package dependencies, and automated security tests.

## 0.14.0 — encrypted TuxDrive Profiles and device migration

- Added a TuxDrive Profile linked to an existing Google Drive, OneDrive, Dropbox, Box, or pCloud OAuth account; no TuxDrive-operated account server stores the profile.
- Added local AES-256-GCM authenticated encryption with a memory-hard scrypt password derivation and a standard private cloud object path.
- Added backup discovery after OAuth account connection, password-protected metadata inspection, and in-app device restore with a local pre-migration configuration copy.
- Configuration-only backup is the safe default. OAuth credentials and peer private identities are included and restored only through an explicit sensitive-migration checkbox.
- Added wrong-password, tamper, cloud copy, settings migration, secret opt-in and private-permission tests; updated documentation, dependencies, package and update metadata.

## 0.13.1 — provider icons and compact job controls

- Job and account rows now consistently use the connected provider's icon instead of substituting the TuxDrive/state icon.
- Synchronization state remains available in row text, tooltips, the health dashboard and Nautilus state emblems.
- Added an application-scoped GTK switch style, explicit size request and centered alignment to prevent oversized enable controls across Ubuntu themes and display scaling.
- Updated visual documentation, packaging metadata, regression checks and the verified update manifest.

## 0.13.0 — controlled peer access and operational visibility

- Added read/write, read-only, send-only and receive-only roles to named peer devices and protocol-v4 invitations, with migration-safe read/write defaults.
- Enforced role direction in complete and incremental synchronization; all-receive endpoints also launch the SFTP service in server-side read-only mode.
- Added expiring, upload-only encrypted file-drop invitations scoped to random hidden inboxes, with persistent first-file consumption markers.
- Added a private permission-restricted audit timeline for synchronization, policy, peer, block-delta and file-drop events.
- Added a provider capability matrix covering streaming, polling, hashes, server moves, versions and safe share links.
- Made job modes and share-link controls adapt to conservative provider capabilities and explain fallbacks in the folder dialog.
- Added a three-page operations dashboard for job/mount/callback health, audit events and provider capabilities.
- Expanded migration, role, expiry, direction, audit and capability regression coverage and updated the installer/documentation.

## 0.12.0 — efficient peer transfer, connectivity and desktop policies

- Added verified 4 MiB block-level delta transactions for direct peer callback updates, with BLAKE2 block checks, final SHA-256 verification and atomic receiver replacement.
- Added best-effort UPnP/NAT-PMP port mapping and an optional SSH reverse-tunnel relay that forwards encrypted SFTP traffic without storing file content or receiving TuxDrive keys.
- Added persistent per-file/per-folder **Always keep available offline** and **Free local space** actions for streaming drives in Nautilus.
- Made Nautilus integration optional in Settings while retaining the default-on behavior.
- Added opt-in metered-network, battery-threshold and daily schedule policies; **Maximum usage** remains the unrestricted default.
- Added installer dependencies, migration-safe configuration fields, tests, release documentation and roadmap status updates.

## 0.11.4 — exact Google Drive folder navigation

- Resolves the selected Google Drive folder from its direct parent when `rclone lsjson --stat` omits the private item ID.
- Preserves My Drive, Shared-with-me, and Shared Drive scopes while resolving nested folders.
- Opens the selected folder's private Drive URL instead of falling back to the Drive home page.

## 0.11.3 — reliable Nautilus request delivery

- Replaced the desktop-dependent Nautilus D-Bus action discovery for online folders with a registered GApplication command-line request.
- Requests are forwarded to the primary TuxDrive instance, logged on receipt, and handled without foregrounding the application window.

## 0.11.2 — monitored online-folder launch

- The Nautilus online-folder action no longer foregrounds TuxDrive.
- Provider URLs are opened through a monitored `xdg-open` process, with its exit status and diagnostic output checked.
- Failed launches now produce a desktop notification and activity-log error containing the actionable desktop-handler detail.

## 0.11.1 — reliable desktop browser handoff

- Opens provider web folders through GNOME's registered default URI handler, fixing silent browser-launch failures when the action originates in Nautilus over D-Bus.
- Reports browser-launch failures in both the application activity message and diagnostic log instead of claiming that the folder opened.

## 0.11.0 — provider web folders and live Nautilus states

- Added **Open online/cloud folder** to the Nautilus TuxDrive submenu.
- Opens exact Google Drive, Dropbox, Box, and supported OneDrive paths where provider identifiers allow it; otherwise opens the safe account root and explains the fallback.
- Never creates a public share link while opening an online folder.
- Added an atomic local runtime-state channel watched by Nautilus.
- Added live synchronized, synchronizing, streaming, paused, pending, and error emblems with automatic metadata invalidation.
- Added provider URL and no-public-link regression coverage.

## 0.10.3 — Nautilus 4.1 compatibility

- Fixed extension startup on Ubuntu 26.04 where Nautilus preloads GI namespace version 4.1.
- Removed the incorrect exact `Nautilus` 4.0 namespace requirement, following GNOME's host-loaded extension model.
- Restores TuxDrive context menus, status metadata, and state emblems on Nautilus 4.1 while remaining compatible with Nautilus 4.0.
- Tracker and GSConnect warnings emitted during `nautilus -q` are unrelated desktop-service messages and do not affect TuxDrive.

## 0.10.2 — visible Nautilus status emblems

- Fixed the Nautilus 4 `InfoProvider` callback contract and explicit completion result.
- Added packaged TuxDrive emblems for synchronized, files-on-demand, and error states.
- Removed reliance on optional theme-specific emblem names.
- Icon cache refresh remains part of package installation; restart Nautilus once after upgrading.

## 0.10.1 — disconnected streaming mount recovery

- Fixed Nautilus directory failures caused by an orphaned FUSE endpoint returning `Transport endpoint is not connected`.
- Streaming-process failure now lazily detaches the kernel mount before automatic retry.
- Application startup recovers untracked configured streaming mounts left behind by a crash or forced shutdown.
- Nautilus status/menu matching now uses lexical local paths and never resolves or stats a streaming endpoint.
- Added regression coverage for startup cleanup and unexpected streaming-process exits.

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
