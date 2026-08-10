# TuxDrive testing and release verification

TuxDrive treats synchronization, deletion propagation, authentication, mounting, and software updates as safety-sensitive behavior. Every change affecting these areas should add or update an automated test and describe any remaining manual verification.

## Run the automated suite

From the repository root:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m compileall -q src
```

The TuxDrive 0.8.0 suite contains **56 automated tests**. Tests use temporary directories and mocked cloud processes where possible, so they do not require or expose real OAuth tokens, cloud accounts, peer identities, vault passwords, or personal files.

## Test groups

| Test module | Tests | What it verifies |
|---|---:|---|
| `test_bootstrap.py` | 4 | Transfer-engine selection, rejection of incompatible rclone versions, supported CPU architectures, and pinned release checksums. |
| `test_config.py` | 2 | Round-trip persistence of accounts, jobs and peer shares; private `0600` permissions; invalid configuration quarantine. |
| `test_diagnostics.py` | 1 | Startup failures are written before GTK imports, allowing diagnosis when the graphical runtime cannot start. |
| `test_engine.py` | 15 | Two-way initialization, one-way direction, rename tracking, deletion ceilings, conflict flags, selective Google scopes, incremental changed-path commands, transient-file suppression, streaming commands, safe folder overlap, blocked Google-file recovery, failure summaries and transfer-engine replacement. |
| `test_packaging.py` | 6 | Launcher import path, installed Python layout, GTK/GDK version pinning, UI feature presence, provider icon packaging, peer runtime inclusion and OpenSSH key-generator dependency. |
| `test_peer.py` | 5 | Invitation parsing, host-key pinning, public-key validation, unprivileged port enforcement, authorized-peer-only SFTP serving and private-identity client authentication. |
| `test_recovery.py` | 3 | Local archive/restore behavior, mass-change and ransomware-suffix blocking, and integrity-audit result parsing. |
| `test_rclone.py` | 14 | OAuth question parsing, stale callback handling, remote-name validation, cloud folder listing, Google locations, all provider backends, Nextcloud configuration, Proton credential protection, conditional Proton 2FA detection/update, account discovery and pre-connection remote validation. |
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

## Build and inspect the Debian package

```bash
sh scripts/build-deb.sh
dpkg-deb --info dist/tuxdrive_0.8.0_all.deb
dpkg-deb --contents dist/tuxdrive_0.8.0_all.deb
sha256sum dist/tuxdrive_0.8.0_all.deb
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
| Peer sharing | Two clean machines on one LAN, wrong guest key rejection, wrong host key rejection, address edit, restart recovery and a large-file transfer. |
| Internet peer sharing | Routed/VPN connection or explicit port forwarding; verify that no intermediary storage is used. |
| Update | No-update result, valid update, corrupted package rejection and cancelled PolicyKit prompt. |
| Diagnostics | Startup log, application log, per-job log and crash-log paths contain useful information without secrets. |
| Recovery | Replace and remotely delete test files, restore several versions, expire retention, and verify current-file archival before restore. |
| Mass-change safety | Preview a disposable large rename/deletion burst and ransomware-like suffix batch; confirm the job pauses before real propagation. |
| Integrity repair | Produce local-only, remote-only, changed and unreadable paths; repair reviewed subsets from each side and re-audit. |
| Encrypted vault | Create a dedicated vault, verify ciphertext/name encryption in the backing account, sync/stream through the vault, and confirm a wrong password cannot read data. |

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
