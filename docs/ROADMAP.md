# TuxDrive feature suggestions and roadmap

This document records completed safety work and proposes future work. Suggestions should preserve TuxDrive's two primary roles:

1. a dependable Ubuntu client for synchronizing and streaming files from cloud services; and
2. a private direct peer-to-peer file synchronization tool that can operate without storing files in a cloud or intermediary server.

The longer-term product direction is a **“Signal for files and cooperation”**: private workspaces in which people verify devices, exchange files and messages, synchronize offline changes, and—where a format supports it—edit together in real time. This is a design goal, not a present security claim. Every feature must ship with an explicit threat model and must identify which content and metadata remain visible to endpoints, relays, storage providers, Tor observers, and workspace administrators.

## Current baseline: 0.14.0

Version 0.14.0 is the current documented and packaged release. It adds locally encrypted configuration backup, provider-linked TuxDrive Profiles, cloud discovery, inspected restore and explicit opt-in migration of OAuth credentials and peer private keys. Version 0.13.1 retained provider identity icons and compact controls. Ranks 1–19 are implemented. Ranks 20–40 define the next portability, privacy, secure-workspace, optional-server and local-first collaboration work.

The next recommended development milestone is **1.0.0 — operational hardening**, focusing on the headless peer agent, protocol versioning, hydration/throughput metrics, relay deployment guidance, large-tree delta stress testing, isolated per-role service endpoints and a published threat model. Tor transport and secure-workspace primitives should follow only after that foundation is externally reviewable. No planned item should be read as available until its status changes to a shipped version.

## Prioritization principles

- Prevent silent data loss before adding convenience features.
- Keep private keys, OAuth tokens and file contents under endpoint control.
- Make destructive operations visible, bounded and recoverable.
- Preserve a fully manual IP/key mode even if automatic discovery is added.
- Prefer interoperable protocols and provider APIs over proprietary emulation.
- Treat real-time document collaboration as a separate consistency problem from ordinary file synchronization.
- Keep direct/LAN operation available; Tor, relay and coordination services must remain optional transports rather than mandatory trust anchors.
- Encrypt content and collaboration operations end to end before they reach an optional server; document unavoidable metadata separately.
- Fail closed when an onion-only, verified-device or no-retention policy cannot be satisfied.
- Do not synchronize a ZIP-based office document on every keystroke. Collaborative ODF work requires a structured document model, deterministic export and explicit compatibility boundaries.

## Top 40 feature status and proposals

| Rank | Proposed feature | Focus | Priority | Why it matters / suggested approach |
|---:|---|---|---|---|
| 1 | Local version history and recycle recovery | Both | Completed 0.8.0 | Archives files replaced/deleted by incoming changes, adds dated two-side version directories, configurable retention, and one-click restore. |
| 2 | Ransomware and mass-change protection | Both | Completed 0.8.0 | Dry-run and callback gates detect large rewrite/deletion batches and ransomware-like suffixes, then pause the job for review. |
| 3 | Integrity audit and repair | Both | Completed 0.8.0 | Non-destructive comparison lists mismatches and repairs selected paths from an explicitly chosen authoritative side. |
| 4 | Conflict review center | Both | Completed 0.8.0 | Filters content conflicts into a review surface with selected-path local or cloud/peer resolution. Rich previews remain future enhancement. |
| 5 | Encrypted cloud vaults | Cloud | Completed 0.8.0 | Client-side content and name encryption layers a dedicated crypt path over a connected cloud account with password-loss warnings. |
| 6 | Multi-peer shared folders | Peer | Completed 0.9.0 | Each share accepts multiple named public keys with enable/disable controls and immediate revocation on restart. |
| 7 | Safe file leases and edit locks | Peer | Completed 0.9.0 | Peer jobs publish short cooperative leases and pause transfers when another device holds an unexpired lease. These are advisory application locks, not OS-enforced locks. |
| 8 | Block-level delta transfer | Peer | Completed 0.12.0 | Direct peer callbacks upload content-addressed changed blocks, verify each BLAKE2 digest and the final SHA-256, and atomically replace the receiver file. Initial/unmatched files transfer all blocks. |
| 9 | LAN discovery and QR pairing | Peer | Completed 0.9.0 | Optional local multicast lists shares; users verify pinned fingerprints and exchange invitations through locally generated/scanned QR images. Manual pairing remains available. |
| 10 | NAT traversal with optional no-storage relay | Peer | Completed 0.12.0 | Shares attempt UPnP then NAT-PMP mapping. An optional SSH reverse tunnel forwards the already encrypted, host-key-pinned SFTP stream and stores no file content or TuxDrive key. Manual direct mode remains available. |
| 11 | Per-file offline availability controls | Cloud | Completed 0.12.0 | Streaming files/folders expose **Always keep available offline** and **Free local space** in Nautilus; persistent rules hydrate VFS content and prevent normal age eviction. Hydration progress remains a future UI refinement. |
| 12 | Nautilus integration | Cloud | Phase 3 completed 0.12.0 | Live state emblems, safe sync/web/log actions and per-item streaming availability controls are shipped. Integration is optional in Settings and enabled by default. |
| 13 | Network, battery and schedule policies | Both | Completed 0.12.0 | Settings can defer transfers on metered networks, below a battery threshold, or outside a daily window. Default **Maximum usage** applies no limits. |
| 14 | Read-only, send-only and receive-only peer roles | Peer | Completed 0.13.0 | Protocol-v4 invitations persist directional roles; full and incremental jobs enforce them. All-receive endpoints add server-side read-only enforcement; separate endpoints remain recommended for hostile generic clients in mixed-role shares. |
| 15 | Peer activity and audit timeline | Peer | Phase 1 completed 0.13.0 | A private, permission-restricted, compacted JSONL timeline and GTK view record peer/sync lifecycle, failures, delta application and drop events. Device-attributed SFTP operation parsing and export/retention controls remain future refinements. |
| 16 | One-time encrypted file drop | Peer | Completed 0.13.0 | Expiring protocol-v4 invitations scope an upload-only sender to a random hidden inbox; ordinary jobs exclude inboxes and the host persists consumption after the first received file. |
| 17 | Provider capability matrix and adaptive UI | Cloud | Phase 1 completed 0.13.0 | All providers declare conservative streaming, polling, hash, move, version and sharing capabilities. Job modes and share actions adapt accordingly; live server capability probes remain future work. |
| 18 | Sync health dashboard | Both | Phase 1 completed 0.13.0 | A consolidated GTK view reports job state, mode/role, mount/callback status, last run/error, audit events and the provider matrix. Byte-rate, cache and retry-depth telemetry remain future refinements. |
| 19 | Encrypted configuration backup and device migration | Both | Completed 0.14.0 | A TuxDrive Profile is encrypted locally with AES-256-GCM/scrypt and stored in a selected user-owned OAuth cloud. New devices discover it after connecting that provider, inspect metadata and restore atomically. OAuth credentials and peer private keys are excluded by default and require explicit sensitive opt-in. |
| 20 | Headless and cross-platform peer agent | Peer | Strategic | Provide a minimal daemon for Ubuntu Server and later interoperable desktop peers on Windows/macOS, using the same invitation, key-pinning and folder-policy model. |
| 21 | Tor v3 Onion Service transport | Privacy | High | Let a peer or workspace endpoint publish an ephemeral or persistent `.onion` address so collaborators can connect without opening an inbound public port or revealing the host address to one another. Keep Tor optional and never silently fall back to clearnet. |
| 22 | Onion client authorization and revocation | Privacy | High | Bind each authorized TuxDrive device to Tor v3 client-authorization material in addition to the application identity key. Provide per-device issuance, QR transfer, rotation and revocation; make clear that Tor reload/restart semantics affect when revocation takes effect. |
| 23 | Fail-closed transport and anonymity policies | Privacy | High | Add per-workspace policies such as **Direct only**, **Tor only**, **No relay**, **No public IP discovery** and **Never use provider cloud**. A policy violation pauses traffic and produces an actionable audit event instead of degrading silently. |
| 24 | Tor bridges and pluggable-transport profiles | Privacy | Medium | Allow advanced users in filtered networks to select a system-managed bridge/pluggable transport without placing bridge credentials in logs or invitations. Treat this as censorship-resistance transport configuration, not proof of anonymity. |
| 25 | Metadata-minimizing transfer mode | Privacy | Research | Offer bounded padding, randomized batching, opaque workspace/object identifiers and reduced presence signals. Display the bandwidth/latency cost and state plainly that endpoint compromise, timing correlation and file-size inference are not eliminated. |
| 26 | Modern group key agreement with forward secrecy | Security | High | Replace static shared workspace encryption with an audited group-key layer based on Messaging Layer Security (MLS) or an equivalently reviewed construction. Membership changes create new epochs; removed devices cannot decrypt later operations, and regularly refreshed keys provide post-compromise recovery properties. |
| 27 | Device safety numbers and key-transparency view | Security | High | Give every contact/workspace a human-verifiable safety number and QR comparison, show every authorized device and key change, and pause sensitive transfers until unexpected identity changes are acknowledged. A later transparency service may be auditable but must not become trusted for content confidentiality. |
| 28 | Hardware-backed keys and recovery trustees | Security | Medium | Support TPM/FIDO2-backed device keys where available and optional threshold recovery split across user-selected trusted devices. Recovery must never allow a TuxDrive server or a single provider account to decrypt workspace content. |
| 29 | Encrypted workspace messaging and file comments | Cooperation | High | Add end-to-end encrypted text threads, replies, reactions, file annotations and decisions beside shared files. Messages use the same verified membership model but a separate versioned event stream so file synchronization cannot corrupt conversation state. |
| 30 | Secure workspace membership and administration | Cooperation | High | Add owner/admin/member/guest roles, invitation approval, expiry, device-level revocation and a signed membership history. Administrative actions must be authenticated, locally auditable and unable to reveal past plaintext to newly added members unless users explicitly re-share it. |
| 31 | Optional zero-knowledge mailbox server | Server | High | Provide a small self-hostable service that temporarily queues opaque encrypted operations for offline devices. Enforce quotas, expiry and abuse controls; the server should not receive content keys, filenames or plaintext, while documentation must disclose observable IP, timing, size and account metadata. |
| 32 | Optional encrypted object and snapshot server | Server | Medium | Add a self-hosted, content-addressed ciphertext store for large files and workspace snapshots when no peer is online. Use client-side encryption, signed manifests, retention limits and garbage collection; direct peer transfer remains preferred when available. |
| 33 | Federated workspace directory and rendezvous | Server | Research | Let independently operated TuxDrive servers exchange only signed device/workspace routing envelopes, without federation-wide user search by default. Support HTTPS and authenticated onion endpoints, domain pinning and server migration without changing end-to-end workspace identity. |
| 34 | Reproducible TuxDrive server appliance | Server | Medium | Package the mailbox/rendezvous/object roles as a hardened container and Ubuntu service with minimal ports, automatic key rotation, backup/restore, metrics without filenames, safe upgrades and an onion-service deployment profile. Offer each role independently to minimize metadata concentration. |
| 35 | Local-first real-time Markdown and text editing | Editing | High | Build the first collaborative editor around a well-tested CRDT: multi-peer cursors, offline edits, deterministic convergence, comments and plain Markdown/text export. Store the collaboration state separately from the exported file and preserve ordinary editor interoperability through explicit import/export checkpoints. |
| 36 | Structured ODT collaborative editing | Editing | Research | Model ODF paragraphs, styles, lists, tables, comments and tracked changes as structured operations rather than repeatedly syncing the zipped `.odt` binary. Export deterministic standards-compliant ODT snapshots, retain unsupported XML safely and warn when round-tripping may lose an unsupported feature. |
| 37 | ODS and common document-format adapters | Editing | Research | Extend the structured approach to ODS cells/formulas and selected open formats. DOCX/XLSX/PDF should initially use lock/version/review workflows; real-time editing is enabled only after format-specific convergence and round-trip tests prove it safe. |
| 38 | Presence, cursors, review and approval workflows | Editing | Medium | Add optional encrypted presence, selections, suggestions, tracked changes, mentions, approvals and file tasks. Presence expires quickly, can be disabled, and must not be written into long-lived audit logs unless policy requires it. |
| 39 | Deterministic snapshots, branches and signed releases | Cooperation | High | Turn collaborative event streams into reproducible file snapshots; allow named branches, reviewed merges, cryptographically signed milestones and rollback. Users can always export a normal folder without requiring the collaboration engine to read it later. |
| 40 | Offline-first workspace engine and convergence test lab | Both | Strategic | Create one versioned operation log for messages, membership, document edits and file manifests, with causal ordering, deduplication, bounded compaction and recovery after long offline periods. Ship a deterministic multi-device simulator covering partitions, reordering, malicious events, revocation and format round trips before calling real-time collaboration stable. |

## “Signal for files” target architecture

The target is not a clone of Signal's interface or protocol. It applies comparable user expectations—verified correspondents, strong end-to-end encryption, multi-device operation, safe key changes and minimal server trust—to larger stateful objects and collaborative documents.

| Layer | Responsibility | Trust boundary |
|---|---|---|
| Identity | Per-device keys, safety numbers, QR verification, revocation and optional hardware protection | A server may distribute public material but cannot silently replace a verified key without a visible safety change. |
| Group security | Epoch-based membership and end-to-end encryption for operations and object keys | Evaluate MLS or another audited group construction; do not invent a TuxDrive group ratchet. |
| Collaboration | Local CRDT/event state, deterministic snapshots, leases for unsupported formats, review and audit | Convergence does not guarantee authorization; every operation must also be signed, membership-checked and resource-bounded. |
| Transport | LAN/direct SFTP, authenticated relay, Tor onion and future secure transports | Transport is selectable and replaceable. Onion-only and no-relay policies fail closed. |
| Optional services | Prekey/device directory, mailbox, rendezvous and encrypted object cache | Services handle opaque bounded data and metadata only; roles can be separately self-hosted and disabled. |
| Export | Normal folders, Markdown/text and deterministic ODF snapshots | Users retain portable files and can leave TuxDrive without surrendering content or keys. |

### Security gates before implementation claims

- Publish protocol schemas, downgrade rules, key lifecycle, metadata map and recovery behavior.
- Commission review of the group-key, invitation, server-envelope and Tor client-authorization integrations.
- Add resource limits for ciphertext queues, CRDT histories, device counts, skipped keys, decompression and document complexity.
- Test malicious and stale members, server equivocation, rollback, duplicate/reordered events, long partitions and device compromise.
- Separate confidentiality claims from anonymity claims; Tor changes network exposure but cannot secure an infected endpoint or guarantee resistance to a global traffic analyst.
- Keep real-time editing marked experimental until independent clients converge and export byte-valid documents across a published compatibility corpus.

## Suggested delivery sequence

### Safety foundation

Ranks 1–5 shipped in 0.8.0. Continue hardening them with live-provider, large-tree, retention, fault-injection, and desktop usability testing.

### Private collaboration

Versions 0.9.0–0.13.0 delivered multi-peer authorization, leases, LAN/QR pairing, verified block deltas, optional NAT/relay connectivity, directional roles, audit visibility and expiring file drops. Next prioritize isolated role endpoints, attributed operation parsing and multi-peer/delta stress testing. Then develop ranks 21–28 behind experimental flags: fail-closed Tor transport, verified devices and reviewed group keying. Manual direct mode must continue working without discovery, Tor or relay services.

### Desktop parity and operations

Versions 0.10.0–0.13.0 delivered live Nautilus integration, per-file offline rules, transfer policies, adaptive provider controls and baseline health observability. Next add hydration progress, throughput, cache accounting, retry depth and live backend capability probes.

### Portability

Encrypted provider-linked migration shipped in 0.14.0. A headless/cross-platform agent should follow after the peer protocol and configuration schema are stable.

### Secure workspace services

Ranks 29–34 should start with encrypted comments/messaging and a minimal self-hosted mailbox. Split directory, mailbox, object storage and rendezvous roles so an operator need not collect all metadata. Direct delivery remains the default; offline server queues must be encrypted, quota-limited and expiring.

### Real-time collaboration

Ranks 35–40 begin with Markdown/plain text and a deterministic convergence test lab. ODT/ODS work follows as structured adapters with compatibility corpora. Binary office formats remain lease/version-based until an adapter can prove convergent edits and safe round trips; marketing must not call ordinary last-writer-wins file synchronization “real-time collaboration.”

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

The roadmap intentionally builds on published protocols and existing transfer primitives rather than novel cryptography:

- rclone provides a [client-side crypt layer](https://rclone.org/crypt/), [integrity checking](https://rclone.org/commands/rclone_check/) and a [local remote-control API](https://rclone.org/rc/); remote control must remain loopback-only and authenticated because it is equivalent to access to files and stored provider credentials;
- mature peer synchronizers demonstrate [block-level transfer](https://docs.syncthing.net/users/syncing.html) and [retained versions](https://docs.syncthing.net/users/versioning.html);
- Tor documents [v3 Onion Service client authorization](https://community.torproject.org/onion-services/advanced/client-auth/) with per-client X25519 authorization material; TuxDrive must follow supported Tor interfaces and their revocation behavior rather than implementing an onion protocol itself;
- [RFC 9420 Messaging Layer Security](https://www.rfc-editor.org/rfc/rfc9420.html) specifies asynchronous group key establishment with forward secrecy and post-compromise security, while also documenting delivery-service and metadata limitations;
- Signal's published [Double Ratchet](https://signal.org/docs/specifications/doubleratchet/) and [Sesame](https://signal.org/docs/specifications/sesame/) specifications inform the required key-change, asynchronous and multi-device threat analysis, but are not drop-in file synchronization protocols; and
- Automerge's [local-first storage and synchronization model](https://automerge.org/docs/tutorial/local-sync/) demonstrates separating local document state from network adapters. Any selected CRDT still requires TuxDrive-specific authorization, encryption, resource limits, snapshot and file-format validation.
