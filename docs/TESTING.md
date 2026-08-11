# TuxDrive testing and release verification

TuxDrive treats synchronization, deletion propagation, authentication, mounting, and software updates as safety-sensitive behavior. Every change affecting these areas should add or update an automated test and describe any remaining manual verification.

## Run the automated suite

From the repository root:

```bash
python3 -m pip install .
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m compileall -q src
```

The dependency-install step is required when using an isolated Python environment such as GitHub Actions. Python-package builds require `cryptography>=50.0.0,<51`; Ubuntu `.deb` installations use the distribution-maintained `python3-cryptography` package so official Ubuntu backported security fixes are recognized by APT rather than compared only by the upstream version string.

CI pins third-party actions by immutable commit, runs high-severity Bandit checks and `pip-audit`, and publishes a CycloneDX dependency SBOM with the package.

The TuxDrive 0.19.1 suite contains **126 automated tests**. Tests use temporary directories and mocked cloud/Tor processes where possible, so they do not require or expose real OAuth tokens, cloud accounts, Onion credentials, peer identities, vault passwords, presence passphrases, or personal files. The updater tests validate both the original-key legacy bridge and the rotated-key v2 channel against the exact packaged release.

## Test groups

| Test module | Tests | What it verifies |
|---|---:|---|
| `test_audit.py` | 2 | Private audit persistence, filtering and malformed historical-line handling. |
| `test_bootstrap.py` | 5 | Linux/macOS transfer-engine selection, rejection of incompatible rclone versions, supported CPU architectures, and pinned release checksums. |
| `test_capabilities.py` | 3 | Complete provider records and conservative adaptive-mode restrictions. |
| `test_config.py` | 3 | Round-trip persistence of accounts, jobs, peer shares and profile linkage; private `0600` permissions; invalid configuration quarantine. |
| `test_delta.py` | 1 | Rolling BLAKE2 block signatures identify only modified ranges and calculate transferred bytes. |
| `test_diagnostics.py` | 1 | Startup failures are written before GTK imports, allowing diagnosis when the graphical runtime cannot start. |
| `test_platform_support.py` | 4 | Safe distribution parsing, Linux/macOS machine-readable capability reporting and unsupported-architecture blocking. |
| `test_engine.py` | 20 | Two-way initialization, one-way direction, rename tracking, deletion ceilings, conflict flags, selective Google scopes, incremental changed-path commands, transient-file suppression, streaming commands, safe folder overlap, stale-mount startup recovery, unexpected-exit and orderly-shutdown cleanup, peer-lease metadata exclusion, blocked Google-file recovery, failure summaries and transfer-engine replacement. |
| `test_i18n_help.py` | 2 | Six-language UI fallback, Arabic/Hebrew RTL detection and complete localized in-app help topics. |
| `test_migration.py` | 5 | AES-GCM profile round trips, wrong-password/tamper rejection, provider copy/restore, secret opt-in, private permissions and input validation. |
| `test_packaging.py` | 10 | Debian launcher/layout checks, optional-integration package boundaries, GTK/GDK version pinning, UI feature presence, provider icons, peer runtime inclusion, Nautilus routing, InfoProvider completion and packaged emblems. |
| `test_collaboration.py` | 11 | Offline CRDT convergence, iterative deep-chain handling, immutable/bounded operation state, checkpoints, review/presence, deterministic ODT/ODS round trips, ZIP-bomb rejection, unsafe XML rejection and binary fallback. |
| `test_peer.py` | 19 | Invitation compatibility/roles/drops/relay parsing, verified atomic delta application, fingerprints, isolated per-device role/root enforcement, multi-device authorization, legacy migration, host-key pinning, edit leases and private-identity authentication. |
| `test_policies.py` | 3 | Maximum-usage defaults plus controlled battery and schedule deferral. |
| `test_recovery.py` | 3 | Local archive/restore behavior, mass-change and ransomware-suffix blocking, and integrity-audit result parsing. |
| `test_security.py` | 2 | Symlink/parent escape rejection plus Ed25519 signed-transaction tamper detection. |
| `test_rclone.py` | 18 | OAuth question parsing, callback handling, remote validation, provider behavior, Proton protection, and automatic Secret Service-backed rclone configuration encryption. |
| `test_updater.py` | 9 | Numeric version comparison, trusted release URLs, progress, download verification, corrupt-partial cleanup, privileged no-follow immutable staging/digest checks, and signed manifest/package release coherence. |

## Important safety invariants covered

- A first two-way synchronization uses the explicit recovery/merge path instead of assuming either side is empty.
- Later synchronizations do not silently repeat the initial resynchronization.
- Upload-only and download-only jobs preserve their configured direction.
- Streaming folders may be protected children of synchronized folders, but unsafe overlaps are rejected.
- Office lock files, editor temporary files and partial downloads are not synchronized.
- Google malware/spam acknowledgement is opt-in and scoped to one job.
- Peer invitations contain public SSH connection material only. A protocol-v5 Tor invitation may intentionally contain the receiving device's scoped Onion client secret and must be handled like a password; neither the host SSH identity nor the general TuxDrive identity private key enters it.
- Tor-only policy rejects direct fallback, invalid Onion addresses are refused, client authorization is device-scoped/revocable, and Tor configuration/authorization files are private.
- Bridge credentials remain out of subprocess arguments, invitations, and application audit/log messages.
- A peer client pins the server host key and authenticates with its own private key.
- Proton accounts are not accepted until an actual remote listing succeeds.
- Update packages are not installed until both desktop and privileged helper verification succeed; the helper verifies a root-only staged copy and trusts neither a user-supplied digest nor the previously opened user-writable path.
- Incoming replacement/deletion recovery retains restorable content before changing the local file.
- Ransomware-like extensions and configured mass-change thresholds pause propagation.
- Integrity audit differences are parsed into explicit, selectable repair findings.
- A legacy one-key share migrates into the named-device model without losing access.
- Every enabled public key receives a distinct authorization file/listener; role-limited keys cannot share a broader endpoint and revoked/disabled keys are omitted.
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
- ODF archives are rejected before expansion when entry count, bytes, entry size, duplicate/path or compression-ratio limits fail; unsafe XML entities never enter the structured editor.
- Collaborative operation files are bounded regular JSON with validated identifiers/counters, a global count ceiling and non-recursive deterministic traversal.

## Build and inspect the Debian package

```bash
sh scripts/build-deb.sh
dpkg-deb --info dist/tuxdrive_0.19.1_all.deb
dpkg-deb --contents dist/tuxdrive_0.19.1_all.deb
sha256sum dist/tuxdrive_0.19.1_all.deb
```

The CI **Static security analysis** step must run before tests and packaging:

```bash
bandit -q -r src -lll
pip-audit -r requirements-security.txt
```

The release is blocked on any high-severity Bandit result or unresolved dependency advisory. Do not add an ignore merely to make CI green; document exploitability and a time-bounded exception in `SECURITY.md` if no fixed dependency exists. The 0.16.0 floor was introduced because 46.0.7 was affected by PYSEC-2026-3552, PYSEC-2026-3553, PYSEC-2026-3554, and GHSA-537c-gmf6-5ccf.

Release manifests must be signed outside Git with the Ed25519 release key:

```bash
python3 scripts/sign-update.py --version 0.19.1 \
  --package dist/tuxdrive_0.19.1_all.deb \
  --private-key /secure/offline/TuxDrive-update-signing-private.pem
```

Only the public key belongs in source control. Store the private key offline or in a protected release secret, restrict release environments, and rotate the embedded public key through a separately reviewed application release if compromise is suspected.

After signing, parse the manifest with `UpdateManager.parse_manifest`, compare its SHA-256 with the package, inspect the embedded Debian package/version, and confirm the expiry is in the future. `test_repository_manifest_matches_current_debian_release` now blocks CI if a version/package is committed without its matching signed manifest. A successful unit suite alone is not a release authorization.

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
| Tor transport | Validate persistent/ephemeral Onion addresses, two separately authorized clients, QR import, revoked and rotated client authorization, Tor restart semantics, service failure, SOCKS failure, Tor-only clearnet refusal, no-relay/no-IP rules, bridges in a filtered-network lab and confirmation that secrets are absent from logs/process listings. |
| Peer roles | Exercise each role in both directions using both TuxDrive and a generic SFTP client. Verify distinct ports/one-key files, server read-only behavior, send-only inbox roots, revocation and mixed-role isolation. |
| One-time drop | Test its dedicated port/root with a generic client, parent-workspace denial, expiry, first-file consumption, current-session completion, reconnect rejection and restart persistence. Confirm ordinary jobs exclude `.tuxdrive-drops`. |
| Audit timeline | Produce success, failure, policy, peer, delta and drop events; verify local-only storage, permissions, compaction, path sensitivity and malformed-line recovery. |
| Capability UI | Change among all providers and confirm unsupported modes/actions disappear or disable while server-specific caveats remain visible. |
| Sync health | Verify running, mounted, paused, callback, last-run and error states against actual job behavior, then reopen to refresh the snapshot. |
| Main-window identity | Connect one account for every provider and confirm account/job rows retain the provider icon in idle, syncing, paused and error states. Test the compact enable switch with Ubuntu default, dark and high-DPI themes. |
| Edit leases | Simultaneous save of the same file, foreign lease pause, normal release, application crash, lease expiry and retry. Confirm non-TuxDrive writers are documented as outside advisory enforcement. |
| LAN/QR pairing | Discovery on one subnet, no discovery across a routed boundary, full fingerprint comparison, QR display/import, invalid image rejection and manual-pairing fallback. |
| Nautilus integration | Test enabled and disabled settings after restarting Nautilus; confirm menus/badges disappear when disabled and streaming items expose pin/free-space actions when enabled. |
| Internet peer sharing | Direct, UPnP, NAT-PMP and reverse-relay connections; verify host-key pinning, relay fallback, no retained relay content, tunnel recovery, and manual direct mode. |
| Transfer policies | Maximum default, metered connection, AC/battery transition, overnight schedule, invalid/disconnected NetworkManager state, and queued retry after a policy becomes permissive. |
| Update | No-update result, valid update, corrupted package, symlink, same-user replacement race, manifest change, cancelled PolicyKit prompt and successful installation from root-only staging. |
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
- automatic interpretation of Ubuntu backported security patches from an upstream-looking package version;
- automated privileged PolicyKit/real-APT race testing in an isolated VM;
- sustained hostile peer/drop quota and session-termination testing beyond the dedicated-root authorization tests.

These gaps are tracked as roadmap work rather than implied coverage.

## Adding a regression test

1. Reproduce the failure with sanitized paths and no credentials.
2. Add a focused test to the closest `tests/test_*.py` module.
3. Assert the safety outcome, not only the generated command—for example, that a destructive action is stopped or a key mismatch is rejected.
4. Run the complete suite and package build.
5. Document any provider-specific or manual verification still required.
