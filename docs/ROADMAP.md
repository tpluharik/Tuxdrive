# TuxDrive feature suggestions and roadmap

This document proposes future work; it is **not** a promise that the features already exist. Suggestions should preserve TuxDrive's two primary roles:

1. a dependable Ubuntu client for synchronizing and streaming files from cloud services; and
2. a private direct peer-to-peer file synchronization tool that can operate without storing files in a cloud or intermediary server.

## Prioritization principles

- Prevent silent data loss before adding convenience features.
- Keep private keys, OAuth tokens and file contents under endpoint control.
- Make destructive operations visible, bounded and recoverable.
- Preserve a fully manual IP/key mode even if automatic discovery is added.
- Prefer interoperable protocols and provider APIs over proprietary emulation.
- Treat real-time document collaboration as a separate consistency problem from ordinary file synchronization.

## Top 20 proposed features

| Rank | Proposed feature | Focus | Priority | Why it matters / suggested approach |
|---:|---|---|---|---|
| 1 | Local version history and recycle recovery | Both | Critical | Archive files replaced or deleted by an incoming sync, with retention by age/count and one-click restore. This provides a recovery layer against mistakes, bad conflicts and remote deletions. |
| 2 | Ransomware and mass-change protection | Both | Critical | Detect unusually large rename, rewrite, encryption-extension or deletion bursts; pause the job and require review before propagation. Combine event thresholds with the existing maximum-deletion guard. |
| 3 | Integrity audit and repair | Both | Critical | Compare file counts, sizes and available hashes, display mismatches, then repair selected paths. Schedule non-destructive verification separately from synchronization. |
| 4 | Conflict review center | Both | Critical | Present both versions, timestamps, origins and text/image previews; allow keep-local, keep-remote, keep-both or external merge instead of hiding conflicts in renamed files. |
| 5 | Encrypted cloud vaults | Cloud | High | Add opt-in client-side filename and content encryption using a crypt layer above supported cloud remotes. Include password recovery warnings and encrypted-name previews. |
| 6 | Multi-peer shared folders | Peer | High | Extend one-host/one-guest sharing to several explicitly authorized devices, with individual keys, readable device names and immediate per-device revocation. |
| 7 | Safe file leases and edit locks | Peer | High | Publish short authenticated edit leases so two users are warned before editing the same office/design file. Locks must expire safely and never permanently block access. |
| 8 | Block-level delta transfer | Peer | High | Transfer only changed blocks of large files and reuse blocks already present locally. This is especially valuable for VM images, mail archives, media projects and unreliable links. |
| 9 | LAN discovery and QR pairing | Peer | High | Discover TuxDrive peers by local multicast, then confirm the fingerprint/QR code on both screens. Keep manual IP and public-key exchange available for isolated networks. |
| 10 | NAT traversal with optional no-storage relay | Peer | High | Try UPnP/NAT-PMP and direct hole punching; offer an optional end-to-end encrypted transport relay when direct reachability fails. A relay may forward ciphertext but must never receive decryption keys or retain file content. |
| 11 | Per-file offline availability controls | Cloud | High | Add **Online only**, **Available offline** and **Always keep locally** actions for streamed files/folders, including cache usage and hydration progress. |
| 12 | Nautilus integration | Cloud | High | Show sync/hydration/error badges and context actions for sync now, keep offline, free local space, copy cloud link, exclude and inspect history. |
| 13 | Network, battery and schedule policies | Both | Medium | Pause or limit transfers on metered/mobile networks, low battery, specified Wi-Fi networks or working hours; permit small metadata checks while deferring large bodies. |
| 14 | Read-only, send-only and receive-only peer roles | Peer | Medium | Give each authorized device explicit folder permissions. Enforce the direction both in TuxDrive jobs and at the served endpoint rather than relying only on user discipline. |
| 15 | Peer activity and audit timeline | Peer | Medium | Record which authenticated device uploaded, replaced, moved or deleted each path, with retention controls and secret-safe export. This is essential for collaborative troubleshooting. |
| 16 | One-time encrypted file drop | Peer | Medium | Generate an expiring, single-purpose invitation allowing a peer to upload selected files into a controlled inbox without exposing the rest of the shared folder. |
| 17 | Provider capability matrix and adaptive UI | Cloud | Medium | Detect whether each backend supports hashes, polling, server-side copy/move, versions, sharing and quotas; show only safe controls and explain fallbacks. |
| 18 | Sync health dashboard | Both | Medium | Display pending files, last successful verification, transferred bytes, current rate, retry queue, cache use, peer reachability and provider throttling in one view. |
| 19 | Encrypted configuration backup and device migration | Both | Medium | Export selected jobs, filters and public metadata in a password-protected bundle. Private identities and OAuth credentials should be opt-in, strongly encrypted and clearly separated. |
| 20 | Headless and cross-platform peer agent | Peer | Strategic | Provide a minimal daemon for Ubuntu Server and later interoperable desktop peers on Windows/macOS, using the same invitation, key-pinning and folder-policy model. |

## Suggested delivery sequence

### Safety foundation

Implement ranks 1–4 first: version history, ransomware protection, integrity checking and conflict review. These reduce the consequences of every later cloud and peer feature.

### Private collaboration

Then implement ranks 6–10 and 14–16: multi-device authorization, edit leases, delta transfer, pairing, connectivity and granular peer permissions. Manual direct mode must continue working without a discovery or relay service.

### Desktop parity and operations

Implement ranks 11–13, 17 and 18 for files-on-demand usability, Nautilus integration, transfer policies and observability.

### Portability

Encrypted migration and a headless/cross-platform agent should follow after the peer protocol and configuration schema are stable.

## Suggestions and discussion

Community proposals are welcome through the repository's feature-request form. A useful suggestion should include:

- the user problem and whether it affects cloud, peer or both modes;
- a concrete workflow or mock-up;
- expected behavior during disconnection, conflict and restart;
- deletion and recovery implications;
- authentication, encryption and metadata exposure;
- compatibility with existing accounts and jobs;
- the minimum automated and manual tests required.

Large proposals should be divided into a design issue and small reviewable implementation pull requests. Features that weaken host-key verification, expose rclone's remote-control API beyond loopback, silently bypass deletion limits, or upload peer files to an intermediary should not be accepted without an explicit security design and opt-in model.

## Technical basis

The roadmap intentionally builds on capabilities already present in the transfer ecosystem: rclone supports a [client-side crypt layer](https://rclone.org/crypt/), [integrity checking](https://rclone.org/commands/rclone_check/) and a [local remote-control API](https://rclone.org/rc/), while mature peer synchronizers demonstrate the value of [block-level transfer](https://docs.syncthing.net/users/syncing.html) and [retained file versions](https://docs.syncthing.net/users/versioning.html). Any remote-control integration must remain loopback-only and authenticated because control access is equivalent to access to the user's files and stored provider credentials.
