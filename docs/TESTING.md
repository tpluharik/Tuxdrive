# TuxDrive testing and release verification

TuxDrive treats synchronization, deletion propagation, authentication, mounting, and software updates as safety-sensitive behavior. Every change affecting these areas should add or update an automated test and describe any remaining manual verification.

## Run the automated suite

From the repository root:

```bash
python3 -m pip install .
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m compileall -q src
```

The dependency-install step is required when using an isolated Python environment such as GitHub Actions. Ubuntu installations receive the same runtime through the `.deb` package's `python3-cryptography` dependency.

The TuxDrive 0.14.0 suite contains **89 automated tests**. Tests use temporary directories and mocked cloud processes where possible, so they do not require or expose real OAuth tokens, cloud accounts, peer identities, vault passwords, or personal files.

## Test groups

| Test module | Tests | What it verifies |
|---|---:|---|
| `test_audit.py` | 2 | Private audit persistence, filtering and malformed historical-line handling. |
| `test_bootstrap.py` | 4 | Transfer-engine selection, rejection of incompatible rclone versions, supported CPU architectures, and pinned release checksums. |
| `test_capabilities.py` | 3 | Complete provider records and conservative adaptive-mode restrictions. |
| `test_config.py` | 3 | Round-trip persistence of accounts, jobs, peer shares and profile linkage; private `0600` permissions; invalid configuration quarantine. |
| `test_delta.py` | 1 | Rolling BLAKE2 block signatures identify only modified ranges and calculate transferred bytes. |
| `test_diagnostics.py` | 1 | Startup failures are written before GTK imports, allowing diagnosis when the graphical runtime cannot start. |
| `test_engine.py` | 20 | Two-way initialization, one-way direction, rename tracking, deletion ceilings, conflict flags, selective Google scopes, incremental changed-path commands, transient-file suppression, streaming commands, safe folder overlap, stale-mount startup recovery, unexpected-exit and orderly-shutdown cleanup, peer-lease metadata exclusion, blocked Google-file recovery, failure summaries and transfer-engine replacement. |
| `test_migration.py` | 5 | AES-GCM profile round trips, wrong-password/tamper rejection, provider copy/restore, secret opt-in, private permissions and input validation. |
| `test_packaging.py` | 8 | Launcher import path, installed Python layout, GTK/GDK version pinning, UI feature presence, provider icon packaging, peer runtime inclusion, Nautilus extension dependency/layout/action routing, InfoProvider completion, and packaged state emblems. |
| `test_peer.py` | 13 | Invitation compatibility/roles/drops/relay parsing, verified atomic delta application, fingerprints, multi-device authorization, legacy migration, host-key pinning, edit-lease blocking, SFTP serving and private-identity authentication. |
| `test_policies.py` | 3 | Maximum-usage defaults plus controlled battery and schedule deferral. |
| `test_recovery.py` | 3 | Local archive/restore behavior, mass-change and ransomware-suffix blocking, and integrity-audit result parsing. |
| `test_rclone.py` | 17 | OAuth question parsing, stale callback handling, remote-name validation, cloud folder listing, exact Google parent-listing fallback, safe Google/Dropbox online URLs without public-link creation, Google locations, all provider backends, Nextcloud configuration, Proton credential protection, conditional Proton 2FA detection/update, account discovery and pre-connection remote validation. |
| `test_updater.py` | 6 | Numeric version comparison, trusted release URLs, visible download progress, SHA-256 validation and removal of corrupt partial packages. |

## Important safety invariants covered

- A first two-way synchronization uses the explicit recovery/merge path instead of assuming either side is empty.
- Later synchronizations do not silently repeat the initial resynchronization.
- Upload-only and download-only jobs preserve their configured direction.
- Streaming folders may be protected children of synchronized folders, but unsafe overlaps are rejected.
- Office lock files, editor temporary files and partial downloads are not synchronized.
- Google malware/spam acknowledgement is opt-in and scoped to one job.
- Peer invitations contain public connection material only; private keys never enter an invitation.
- A peer client pins the server host key and authenticates with its own private key.
- Proton accounts are not accepted until an actual remote listing succeeds.
- Update packages are not installed until their SHA-256 checksum matches the signed repository manifest value.
- Incoming replacement/deletion recovery retains restorable content before changing the local file.
- Ransomware-like extensions and configured mass-change thresholds pause propagation.
- Integrity audit differences are parsed into explicit, selectable repair findings.
- A legacy one-key share migrates into the named-device model without losing access.
- Multiple enabled public keys are written to the authenticated endpoint; revoked/disabled keys are omitted.
- A foreign unexpired edit lease blocks acquisition instead of allowing an overwrite.
- LAN/QR invitations preserve the pinned host key and lease duration; protocol-v1 invitations remain importable.
- Nautilus actions route through the single application instance, and startup-time sync requests wait for runtime readiness.
- Peer delta blocks are individually BLAKE2-verified, the reconstructed file is SHA-256-verified, and replacement is atomic.
- Transfer policy defaults remain unrestricted; controlled mode defers jobs on configured battery, metered-network, and schedule conditions.
- Protocol-v4 peer invitations preserve roles, drop scope and expiry while legacy protocols remain importable.
- Expired one-time drops are rejected before a remote is saved.
- Read-only, send-only and receive-only jobs reject incremental changes from the prohibited direction; read-only copies do not delete local extras.
- Every provider has a capability record and unsupported peer streaming/unsafe Proton sharing controls are rejected by the adaptive model.
- Audit events are written with mode `0600`, can be filtered by job and ignore malformed historical lines safely.
- Encrypted profiles reveal no clear configuration, reject wrong passwords and modification, and exclude OAuth/peer secrets unless the sensitive option is explicitly selected.
- Restored configuration and opted-in credential/key files retain private `0600` permissions, while a local pre-migration configuration is kept for rollback.

## Build and inspect the Debian package

```bash
sh scripts/build-deb.sh
dpkg-deb --info dist/tuxdrive_0.14.0_all.deb
dpkg-deb --contents dist/tuxdrive_0.14.0_all.deb
sha256sum dist/tuxdrive_0.14.0_all.deb
```

The build script performs an additional import smoke test against the exact staged `/usr/lib` layout used after installation. It verifies the TuxDrive version and confirms that the desktop application, updater, peer, and recovery modules are discoverable.

## Manual release matrix

Automated tests do **not** replace live provider and desktop testing. Before a stable release, maintainers should record results for this matrix:

| Area | Required manual scenario |
|---|---|
| Installation | Clean Ubuntu 26.04 install, upgrade from the previous package, application-menu launch and tray visibility. |
| OAuth | New Google Drive and OneDrive accounts, browser cancellation, reconnect and expired-token recovery. |
| Credential providers | MEGA, Nextcloud app password, Proton password plus conditional 2FA challenge. |
| Selective sync | Nested folder selection, multiple selected roots, rename/move, deletion and conflict copy. |
| Streaming | Empty mount, file hydration on open, write-back, disconnect, unexpected mount loss and restart. |
| Offline availability | Pin individual streamed files/folders, disconnect networking, open pinned content, free local space, restart the mount, and confirm rules persist. |
| Block delta | Change one block in a multi-gigabyte peer file, verify reduced transmitted bytes in logs, corrupt a queued block, and confirm the receiver rejects it without replacing the destination. |
| Peer sharing | Three or more clean machines, simultaneous access, named-key revocation, disabled key, wrong key rejection, address edit, restart recovery and a large-file transfer. |
| Peer roles | Exercise each role in both directions, including local/remote deletion. Verify an all-receive endpoint is server read-only and document that mixed-role enforcement requires paired TuxDrive clients or separate service endpoints. |
| One-time drop | Test expiry before connection, inbox isolation, first-file consumption, current-session completion, reconnect rejection and host restart persistence. Confirm ordinary jobs exclude `.tuxdrive-drops`. |
| Audit timeline | Produce success, failure, policy, peer, delta and drop events; verify local-only storage, permissions, compaction, path sensitivity and malformed-line recovery. |
| Capability UI | Change among all providers and confirm unsupported modes/actions disappear or disable while server-specific caveats remain visible. |
| Sync health | Verify running, mounted, paused, callback, last-run and error states against actual job behavior, then reopen to refresh the snapshot. |
| Main-window identity | Connect one account for every provider and confirm account/job rows retain the provider icon in idle, syncing, paused and error states. Test the compact enable switch with Ubuntu default, dark and high-DPI themes. |
| Edit leases | Simultaneous save of the same file, foreign lease pause, normal release, application crash, lease expiry and retry. Confirm non-TuxDrive writers are documented as outside advisory enforcement. |
| LAN/QR pairing | Discovery on one subnet, no discovery across a routed boundary, full fingerprint comparison, QR display/import, invalid image rejection and manual-pairing fallback. |
| Nautilus integration | Test enabled and disabled settings after restarting Nautilus; confirm menus/badges disappear when disabled and streaming items expose pin/free-space actions when enabled. |
| Internet peer sharing | Direct, UPnP, NAT-PMP and reverse-relay connections; verify host-key pinning, relay fallback, no retained relay content, tunnel recovery, and manual direct mode. |
| Transfer policies | Maximum default, metered connection, AC/battery transition, overnight schedule, invalid/disconnected NetworkManager state, and queued retry after a policy becomes permissive. |
| Update | No-update result, valid update, corrupted package rejection and cancelled PolicyKit prompt. |
| Diagnostics | Startup log, application log, per-job log and crash-log paths contain useful information without secrets. |
| Recovery | Replace and remotely delete test files, restore several versions, expire retention, and verify current-file archival before restore. |
| Mass-change safety | Preview a disposable large rename/deletion burst and ransomware-like suffix batch; confirm the job pauses before real propagation. |
| Integrity repair | Produce local-only, remote-only, changed and unreadable paths; repair reviewed subsets from each side and re-audit. |
| Encrypted vault | Create a dedicated vault, verify ciphertext/name encryption in the backing account, sync/stream through the vault, and confirm a wrong password cannot read data. |
| TuxDrive Profile | Store configuration-only and sensitive backups on each supported OAuth provider; inspect and restore on a clean device, test a wrong password/tampered object, confirm discovery, verify rollback and confirm that default backups do not migrate tokens or private keys. |

Use test accounts and disposable folders. Back up both sides before testing deletion, conflict, migration or bidirectional recovery behavior.

## Current coverage boundaries

The repository suite is primarily deterministic unit and command-construction testing. It does not currently provide:

- automated live-provider OAuth tests;
- a disposable two-host network integration environment;
- GTK screenshot regression testing;
- fault injection for power loss during transfers or configuration writes;
- multi-gigabyte performance and memory benchmarks;
- compatibility testing against every provider account type and regional endpoint.

These gaps are tracked as roadmap work rather than implied coverage.

## Adding a regression test

1. Reproduce the failure with sanitized paths and no credentials.
2. Add a focused test to the closest `tests/test_*.py` module.
3. Assert the safety outcome, not only the generated command—for example, that a destructive action is stopped or a key mismatch is rejected.
4. Run the complete suite and package build.
5. Document any provider-specific or manual verification still required.
