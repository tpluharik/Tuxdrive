# TuxDrive 0.20.6 security hardening and secure operation

This document explains the controls retained through TuxDrive 0.20.6, including the second-round critical/high remediation, explicit online-only/offline retention, GitHub synchronization boundaries, what changed for existing users, which data remain sensitive, what the controls do not guarantee, and how maintainers verify a release. It complements the concise vulnerability-reporting policy in [`SECURITY.md`](../SECURITY.md).

## Supported baseline and immediate action

Version **0.20.6** is the supported baseline. It retains root-side update re-verification, per-key peer endpoints, isolated send/drop roots and bounded ODF/CRDT parsing while adding GitHub URL/branch validation, system-owned Git credentials, hydration rollback, exact per-file rules, explicit-selection-only availability actions, a stable non-remounting VFS policy, last-known-good credential-free Nautilus menu/badge metadata and mount-relative local-manifest verification without reconnect-time cloud reads. Python/PyPI installations require `cryptography>=50.0.0,<51`; Debian installations use the distribution-maintained `python3-cryptography` package so vendor backports remain valid.

Upgrade, restart TuxDrive and Nautilus, verify cloud access, inspect peer authorization, run an integrity check on important jobs, and retain an independent backup. Do not continue using a package whose signed update manifest has expired or failed verification.

The 0.19.1 release completes a trust-root rotation without disabling verification. The legacy `latest.json` manifest is signed by the original offline key embedded in 0.18.1 and is restricted to the 0.19.1 bridge package. Version 0.19.1 reads `latest-v2.json`, signed by the rotated offline key, for all later updates. Both private keys remain outside the repository with mode `0600`; the original key should be retired after the documented legacy-support window.

## Security control inventory

| Area | 0.20.6 behavior | Security purpose |
|---|---|---|
| Updates | Desktop verification plus independent privileged manifest retrieval, signature/expiry validation, no-follow copy to root-only staging, SHA-256 and Debian identity verification before APT | Prevent unsigned, replayed, substituted, oversized, wrong-package and verification-to-install race attacks |
| Cloud credentials | rclone authenticated encrypted configuration; random config key in GNOME Secret Service; password-command retrieval; private permissions; sensitive child processes disable same-user dumpability | Keep tokens/passwords out of TuxDrive JSON, ordinary arguments, and world-readable files |
| Filesystem writes | Relative-path validation plus descriptor-based no-follow traversal and atomic replacement for incremental downloads, deltas, recovery, hydration, and repair | Resist traversal and symlink-swap writes outside the configured root |
| Peer deltas | Canonical signed instructions, authorized Ed25519 signer, bounded block count/size, BLAKE2 block checks, final SHA-256, atomic install, full-file fallback | Reject unauthenticated, tampered, or resource-abusive delta transactions |
| Tor transport | Tor-only/no-public-IP services bind loopback; explicit invitation transport allowlists; randomized per-remote SOCKS listeners; readiness checks; no silent clearnet fallback | Enforce workspace transport policy and reduce accidental address exposure |
| Bridges and relays | Packaged pluggable-transport executable allowlist; bridge material excluded from invitations, arguments, logs, and ordinary profile backup; strict SSH host verification and batch mode | Reduce credential leakage and command/path injection opportunities |
| Peer roles | One listener and authorization file per key; server read-only for read/receive roles; private inbox root for send-only | Prevent hostile generic clients from bypassing a role label |
| One-time drops | Dedicated key/port/inbox root, consumption marker, authorization rebuild, endpoint restart and expiry validation | Prevent parent-workspace browsing and retire a temporary grant promptly after use |
| Collaborative inputs | Defused XML, ZIP count/size/ratio/path limits, bounded operation JSON/schema/count and iterative CRDT traversal | Prevent archive/XML/operation resource-exhaustion attacks arriving through sync or peers |
| Configuration backup | Version-2 AES-256-GCM, scrypt `N=131072`, unique minimum 14-character password, 128 MiB bundle limit; version-1 read compatibility | Increase offline-guessing cost and bound memory/storage abuse while preserving migration |
| Runtime | Isolated Python launcher, cleared Python environment, mode-0600 logs/config, mode-0700 state directories, systemd `UMask=0077`, `PrivateTmp`, and `LockPersonality` | Reduce environment injection and accidental local disclosure |
| Transfer engine | rclone 1.75.0+ plus required safety capabilities; bounded verified bootstrap archive with unique safe member extraction | Reject unsupported or unsafe engines and malicious archives |
| GitHub repositories | Credential-free GitHub-only URLs, validated branches/origins, noninteractive system Git credentials, fast-forward/rebase guards, conflict abort | Avoid token leakage, command injection and silent Git history overwrite |
| Offline hydration | Root/child confinement, symlink rejection, failed-pin rollback, exact file rules, stable no-remount retention, explicit nested online-only exceptions, and confined local pin manifests checked without remote reads | Avoid sibling downloads, detached Nautilus views, silent reconnect downloads, false offline claims, generic-cache eviction of pinned content, and path escape |
| CI/release | Pinned GitHub Action SHAs, 155 tests, compile checks, high-severity Bandit, `pip-audit`, Debian inspection, CycloneDX SBOM, signed-manifest verification | Make security regressions and vulnerable dependencies release blockers |

## Dependency advisory response

The 0.15.1 workflow installed `cryptography` 46.0.7 and `pip-audit` reported PYSEC-2026-3552, PYSEC-2026-3553, PYSEC-2026-3554, and GHSA-537c-gmf6-5ccf. The highest required fixed version was 50.0.0, so 0.16.0 raises the upstream floor to 50.0.0 rather than ignoring the audit.

There are two installation trust paths:

- Python/PyPI builds resolve the explicit `>=50.0.0,<51` requirement and are checked by `pip-audit`.
- The Ubuntu `.deb` depends on Ubuntu's `python3-cryptography`. Distribution security teams may backport fixes without changing the apparent upstream major version, so administrators must follow Ubuntu Security Notices and installed package changelogs. An upstream-version-only Debian constraint could incorrectly reject a patched Ubuntu package.

Never interpret a green dependency audit as proof that application logic is safe. Conversely, do not replace a distribution security assessment with an upstream version comparison alone.

## Credential and key locations

| Data | Normal location | Protection and backup advice |
|---|---|---|
| TuxDrive settings | `~/.config/tuxdrive/config.json` | Mode `0600`; contains job/account metadata, paths, peer public material, and policy—not the managed rclone config password |
| rclone configuration | `~/.config/rclone/rclone.conf` | Authenticated encrypted form; treat as sensitive even when encrypted |
| rclone config password | GNOME Secret Service entry `TuxDrive rclone configuration` | Do not delete or copy into scripts; include in a tested device-migration plan |
| Peer private identity | TuxDrive private data directory | Mode `0600`; never send it—exchange only public keys and verified fingerprints |
| Tor service/client authorization | Private TuxDrive Tor state | Treat client invitations/QR as passwords; revoke unused devices and account for Tor reload timing |
| Update signing private key | Offline release environment only | Never commit, ship, log, or store beside public artifacts |
| Recovery/version data | `~/.local/share/tuxdrive/recovery` and remote `.tuxdrive-versions` | Sensitive filenames/content may be retained; include it in retention and secure-erasure policy |
| Logs and audit | `~/.local/state/tuxdrive`, `~/.cache/tuxdrive/logs`, `~/.local/share/tuxdrive/audit.jsonl` | Private permissions; may reveal paths, peer names, timing, errors, and operational metadata |

## Upgrade and migration behavior

On first secure rclone use, TuxDrive detects an unencrypted managed configuration, generates a random password, stores it in GNOME Secret Service, asks rclone to encrypt the configuration, and records a private managed marker. An already encrypted advanced-user setup is preserved. If Secret Service is unavailable, configuration migration must fail visibly rather than writing a password into TuxDrive JSON.

Existing jobs, provider remotes, peer public metadata, recovery data, and version-1 encrypted profile backups remain usable. Create new profile backups after upgrading so they receive the stronger version-2 scrypt parameters. Test restore on non-critical data before deleting an older backup.

## Trust boundaries and residual risk

- TuxDrive cannot protect files after malware or another process compromises the desktop user account.
- Provider OAuth and rclone still grant the configured cloud permissions. A malicious provider, revoked token, policy change, or provider-side corruption remains outside TuxDrive's control.
- Tor hides direct routing in Tor-only mode but does not guarantee anonymity against endpoint compromise, traffic correlation, invitation leakage, or a global observer.
- Relays see addresses, timing, connection duration, and byte volume even when they cannot decrypt nested SFTP content.
- Local recovery, cache, names, logs, and audit records expose operational metadata unless the endpoint/storage is separately protected.
- The stable streaming cache does not use rclone's generic LRU quota because it cannot distinguish pinned from ordinary files. Opened content can therefore consume local disk until the user applies **Free local space** to an item or resets the streaming drive to online-only.
- Synchronization deliberately propagates valid changes and deletions. Mass-change limits, history, and verification reduce impact but do not replace immutable or offline backup.

### Intentionally retained peer-server limitation

Peer sharing and one-time drops remain enabled with per-key isolation. Read/write peers retain the selected workspace, read/receive peers receive a server read-only view, and send-only/drop peers receive private inbox roots. Collaborators remain trusted for content they are legitimately allowed to read or modify. Per-endpoint quotas, operation telemetry and immediate upload-session termination remain scheduled in the roadmap.

## Operator verification checklist

1. Install only the repository package whose SHA-256 matches the signed manifest.
2. Confirm the running version is 0.20.6 and the update check reports a valid signature and expiry.
3. Verify configuration/state directories are owned by the user and not group/world accessible.
4. Confirm the rclone config is encrypted and the Secret Service entry is recoverable through an approved migration procedure.
5. Review enabled cloud accounts, jobs, exception rules, peer keys, roles, Tor client credentials, relay settings, and public/NAT exposure.
6. Exercise restore, conflict review, integrity verification, and ransomware/mass-change pause with test files.
7. Inspect logs for repeated authentication failures, policy blocks, unexpected fallback attempts, delta signature failures, and update verification errors.
8. Maintain an offline or immutable backup and document recovery objectives separately from TuxDrive's convenience history.

## Maintainer release verification

Run the unit suite, compilation, shell syntax, `git diff --check`, Bandit, `pip-audit`, package build/inspection, SBOM generation, signed-manifest parsing, package digest comparison, and a clean-machine install/upgrade test. Real provider, FUSE, Nautilus, LAN, NAT, relay, Onion, 2FA, suspend/resume, and large-tree tests remain mandatory manual gates because mocks cannot validate those operating-system and provider boundaries.

Any new credential field must be available to every relevant user/account flow, stored only in the established encrypted/Secret-Service path, redacted from UI errors, logs, and diagnostics, included in explicit sensitive migration only, and covered by round-trip, wrong-secret, permission, and upgrade tests.
