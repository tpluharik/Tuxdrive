# TuxDrive feature suggestions and roadmap

This document records completed safety work and proposes future work. Suggestions should preserve TuxDrive's two primary roles:

1. a dependable Ubuntu client for synchronizing and streaming files from cloud services; and
2. a private direct peer-to-peer file synchronization tool that can operate without storing files in a cloud or intermediary server.

The longer-term product direction is a **“Signal for files and cooperation”**: private workspaces in which people verify devices, exchange files and messages, synchronize offline changes, and—where a format supports it—edit together in real time. This is a design goal, not a present security claim. Every feature must ship with an explicit threat model and must identify which content and metadata remain visible to endpoints, relays, storage providers, Tor observers, and workspace administrators.

## Current baseline: 0.20.10

Version 0.20.10 keeps availability changes inside the existing streaming mount. A file rule applies only to the selected file, selected folders remain explicitly recursive, and background menus cannot silently convert an intended item action into a current-folder/root hydration. Pin manifests use rclone's real mount-relative cache layout and preserve complete legacy records. A progress-based watchdog cancels and retries a provider read that stops delivering bytes, then rolls back the rule and pending badge on terminal failure. Package upgrades retire an older in-memory application before the new extension dispatches actions. The extension coalesces completion-time config/state events, primes its last complete credential-free snapshot, retains URI keys instead of caller-owned FileInfo wrappers, reacquires current cached objects for badge invalidation, emits the dedicated menu-update signal and uses Nautilus 4.1's supported sensitivity property. The TuxDrive menu therefore survives the pending-to-verified transition and verified cached files do not visually revert to cloud-only. Saved pins are verified locally without opening cloud files; only an explicit user action downloads content. The release retains online-only child exceptions, editable metadata-only groups, GitHub synchronization, the six functional Nautilus badges, the 0.19 security remediation and updater trust bridge, six-language documentation and the collaboration baseline.

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
| 8 | Block-level delta transfer | Peer | Hardened 0.15.1 | Direct peer callbacks sign transactions with the sender's authorized Ed25519 identity, upload changed blocks, verify BLAKE2 and final SHA-256 digests, bound resource use, reject symlink escapes, and atomically replace the receiver file. |
| 9 | LAN discovery and QR pairing | Peer | Completed 0.9.0 | Optional local multicast lists shares; users verify pinned fingerprints and exchange invitations through locally generated/scanned QR images. Manual pairing remains available. |
| 10 | NAT traversal with optional no-storage relay | Peer | Completed 0.12.0 | Shares attempt UPnP then NAT-PMP mapping. An optional SSH reverse tunnel forwards the already encrypted, host-key-pinned SFTP stream and stores no file content or TuxDrive key. Manual direct mode remains available. |
| 11 | Per-file offline availability controls | Cloud | Fixed 0.20.10 | Explicitly selected files/folders expose **Keep available offline** and **Free local space (make online-only)**. Exact file rules do not match siblings or parents; selected folders remain recursive, while background menus cannot trigger accidental folder/root hydration. Mount-relative versioned manifests verify the objects rclone actually caches. A stalled provider read is cancelled and retried, and terminal failure clears the pending state. |
| 12 | Nautilus integration | Cloud | Repaired 0.20.10 | Live state emblems, safe sync/web/log actions and per-item streaming availability controls are shipped. The extension coalesces completion metadata, primes its last valid credential-free snapshot, stores URI keys rather than caller-owned FileInfo wrappers, reacquires current cache entries for badge refresh, emits the dedicated menu-update signal and uses the real Nautilus 4.1 property API. Package upgrades retire an old application process before new extension actions are accepted. Six unbranded, color/shape/glyph-distinct functional badges identify each state. |
| 13 | Network, battery and schedule policies | Both | Completed 0.12.0 | Settings can defer transfers on metered networks, below a battery threshold, or outside a daily window. Default **Maximum usage** applies no limits. |
| 14 | Read-only, send-only and receive-only peer roles | Peer | Hardened 0.19.1 | Protocol-v5 invitations persist directional roles. Each key now receives a distinct listener: read-only/receive-only uses server read-only mode, send-only is rooted in a dedicated inbox, and read/write retains the selected workspace. |
| 15 | Peer activity and audit timeline | Peer | Phase 1 completed 0.13.0 | A private, permission-restricted, compacted JSONL timeline and GTK view record peer/sync lifecycle, failures, delta application and drop events. Device-attributed SFTP operation parsing and export/retention controls remain future refinements. |
| 16 | One-time encrypted file drop | Peer | Hardened 0.19.1 | Every active drop receives a one-key, dedicated-port SFTP endpoint rooted at its random inbox. A modified client cannot list the parent workspace; ordinary jobs exclude inboxes and consumption is persisted after the first received file. |
| 17 | Provider capability matrix and adaptive UI | Cloud | Extended 0.20.0 | All cloud, GitHub, peer and vault backends declare conservative streaming, polling, hash, move, version and sharing capabilities. Job modes/actions adapt accordingly; live server capability probes remain future work. |
| 18 | Sync health dashboard | Both | Phase 1 completed 0.13.0 | A consolidated GTK view reports job state, mode/role, mount/callback status, last run/error, audit events and the provider matrix. Byte-rate, cache and retry-depth telemetry remain future refinements. |
| 19 | Encrypted configuration backup and device migration | Both | Completed 0.14.0 | A TuxDrive Profile is encrypted locally with AES-256-GCM/scrypt and stored in a selected user-owned OAuth cloud. New devices discover it after connecting that provider, inspect metadata and restore atomically. OAuth credentials and peer private keys are excluded by default and require explicit sensitive opt-in. |
| 20 | Headless and cross-platform peer agent | Peer | Strategic | Provide a minimal daemon for Ubuntu Server and later interoperable desktop peers on Windows/macOS, using the same invitation, key-pinning and folder-policy model. |
| 21 | Tor v3 Onion Service transport | Privacy | Hardened 0.15.1 | Persistent/ephemeral services bind their SFTP target to loopback, use readiness-tested randomized client SOCKS listeners, and fail closed without clearnet fallback. |
| 22 | Onion client authorization and revocation | Privacy | Completed 0.15.0 | Named devices receive distinct X25519 Onion authorization material through protocol-v5 invitation/QR, with host-side public files, rotation by re-issuance, deletion/reload revocation and documented circuit timing. |
| 23 | Fail-closed transport and anonymity policies | Privacy | Hardened 0.15.1 | Invitations carry explicit transport allowlists; Tor-only/no-public-IP listeners bind loopback and forbidden relay fields are omitted. Provider-cloud enforcement remains a server-agent policy item. |
| 24 | Tor bridges and pluggable-transport profiles | Privacy | Hardened 0.15.1 | Bridge profiles remain in the user's mode-0600 local configuration and isolated Tor files, are excluded from ordinary profile backups, invitations, process arguments and logs, and pluggable transports are restricted to packaged executables. Secret-Service separation remains future work. |
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
| 35 | Local-first real-time Markdown and text editing | Editing | Completed 0.17.0 | An operation-based CRDT stores immutable per-actor operations separately from exported files, supports offline edits and deterministic merge order, and exposes explicit import/export checkpoints compatible with ordinary Markdown/text editors. |
| 36 | Structured ODT collaborative editing | Editing | Research adapter 0.17.0 | ODT imports paragraphs, style references, comments and tracked-change markers. Deterministic snapshots preserve original XML for recovery and warn before unsupported inline structures can flatten; broader structured operations and round-trip fixtures remain research. |
| 37 | ODS and common document-format adapters | Editing | Research adapter 0.17.0 | ODS sheets/cells/formulas have structured import and deterministic recoverable export. DOCX/XLSX/PDF deliberately use lock/version/review rather than unsafe real-time mutation pending format-specific convergence evidence. |
| 38 | Presence, cursors, review and approval workflows | Editing | Completed 0.17.0 | Optional AES-256-GCM cursor/selection presence expires quickly and is excluded from the audit timeline. Immutable workspace events cover comments, suggestions, tracked changes, mentions, approvals and file tasks. |
| 39 | Deterministic snapshots, branches and signed releases | Cooperation | High | Turn collaborative event streams into reproducible file snapshots; allow named branches, reviewed merges, cryptographically signed milestones and rollback. Users can always export a normal folder without requiring the collaboration engine to read it later. |
| 40 | Offline-first workspace engine and convergence test lab | Both | Strategic | Create one versioned operation log for messages, membership, document edits and file manifests, with causal ordering, deduplication, bounded compaction and recovery after long offline periods. Ship a deterministic multi-device simulator covering partitions, reordering, malicious events, revocation and format round trips before calling real-time collaboration stable. |

## Deferred hardening findings from the 0.19.1 review

The critical and high findings were fixed in 0.19.1. The following defense-in-depth items remain scheduled. They do not replace the existing rule that TuxDrive assumes the logged-in desktop account is trusted, but they reduce persistence, corruption and abuse opportunities after another same-user process is compromised.

| Order | Hardening item | Severity | Planned control and acceptance criterion |
|---:|---|---|---|
| H1 | Symlink-safe logs and audit files | Medium | Replace pathname-based log/crash/audit creation and rotation with `openat`/`O_NOFOLLOW` regular-file and ownership checks. A pre-created symlink must never be followed or have its target mode changed. |
| H2 | Credential-backup allowlist | Medium | Refuse symlinks and non-regular files, limit file count/bytes, and include only documented identity/rclone/Tor credential paths when sensitive migration is explicitly enabled. |
| H3 | Fixed executable resolution | Medium | Prefer the verified private rclone and absolute packaged helper paths; validate owner/mode for `ssh`, NAT and QR helpers; launch with a minimal fixed `PATH`. |
| H4 | Local action authentication and throttling | Medium | Rate-limit D-Bus sync/hydration actions, validate the desktop-session caller where supported, and require confirmation for unusually large hydration requests. |
| H5 | Distribution crypto security gate | Medium | Extend system-check and CI to recognize the minimum patched Ubuntu/Debian security revision while continuing to accept vendor-backported fixes rather than comparing upstream versions alone. |
| H6 | Rolling-window ransomware detection | Medium | Aggregate callback changes across jobs and time windows, add entropy/extension heuristics and slow-change scenarios, and prove that low-rate mass encryption pauses before broad propagation. |
| H7 | Structured diagnostic redaction | Medium | Escape control characters and redact tokens, authorization material, bridge credentials and sensitive URL query fields before UI/log output; add hostile-filename fixtures. |
| H8 | User-service sandbox expansion | Medium | After the updater is fully separated, evaluate `NoNewPrivileges`, `ProtectSystem`, `RestrictSUIDSGID`, address-family and device restrictions without breaking FUSE, Secret Service, browser OAuth or notifications. |
| H9 | OAuth loopback adversarial tests | Medium | Add PKCE/state/callback-listener integration tests for every OAuth provider path, including occupied ports, stale callbacks and mismatched state. |
| H10 | Peer/drop quotas and operation telemetry | Medium | Add per-endpoint byte/file/rate quotas, immediate completed-upload session termination and device-attributed operation export. Dedicated roots already prevent workspace escape in 0.19.1. |

## Rank 20 expanded: headless and cross-platform peer agent

Rank 20 is the prerequisite for the later privacy, server and collaborative-editing work. TuxDrive should first separate the synchronization/protocol engine from GTK into a portable **TuxDrive Core**, expose it through a least-privilege local API, and run it as **`tuxdrived`**. Desktop, command-line, Android, server and MCP components then become clients of the same versioned engine instead of reimplementing synchronization and cryptography.

The preferred implementation plan is a memory-safe portable core library with stable language bindings; the final language and cryptographic libraries require an architecture decision record and security review. Existing Python/rclone behavior remains supported during migration through a compatibility adapter. GUI processes must never own long-running transfer state, and privileged service wrappers must not run the core as root/SYSTEM when a dedicated unprivileged identity is sufficient.

### Platform delivery matrix

| Platform / package | Process and user experience | Storage and background model | Supported roles | Platform-specific security and release requirements | Target phase |
|---|---|---|---|---|---|
| Ubuntu Desktop 26.04+ (`.deb`) | `tuxdrived` user service plus GTK client, tray and Nautilus extension; existing configuration migrates in place | `systemd --user`, FUSE streaming, inotify callbacks and XDG paths | Full cloud sync/streaming, peer host/client, collaboration client, local API and optional MCP | Preserve mode-`0600` secrets, user-scoped sockets and current package/update verification; GUI may stop without stopping transfers | Reference platform / 1.0 |
| Ubuntu/Debian Server (`.deb`) | Headless daemon, `tuxdrive` CLI, optional read-only web administration and no desktop dependencies | System or per-user `systemd` unit; explicit service account and configured data roots | Peer host/client, scheduled sync, mailbox, rendezvous, encrypted object cache, relay, API and MCP | No FUSE requirement by default; system service uses sandboxing, capability restrictions, private temporary paths and journald secret filtering | 1.0 |
| Debian ARM64 / Raspberry Pi (`.deb`) | Same headless CLI/daemon with an ARM64 package and reduced-resource profile | `systemd`, inotify, removable disks and optional FUSE where supported | Always-on peer, encrypted mailbox/cache, local backup target and onion endpoint | Bound memory, concurrency, cache and CRDT history; publish signed ARM64 artifacts and test sudden power/storage removal | 1.0–1.1 |
| Windows 11 (`.msi`/MSIX) | Per-user background agent, native tray/settings UI and Explorer integration | User process at sign-in for personal folders; optional Windows Service only for explicitly configured machine/server shares | Cloud sync/streaming where the backend supports it, peer client/host, collaboration, API and optional MCP | Use DPAPI/CNG-backed secrets, named-pipe ACLs, Authenticode signing and safe installer rollback; never show UI from a service session | 1.1 |
| Windows Server (`.msi`) | Non-interactive Windows Service plus PowerShell/CLI and optional web administration | Service Control Manager, dedicated low-privilege account and Event Log | Peer endpoint, mailbox, rendezvous, object cache, relay, automation API and MCP | No LocalSystem default, strict service SID/filesystem ACLs, certificate rotation, unattended upgrade/rollback and remote-admin opt-in | 1.1 |
| macOS (`.pkg`/notarized app) | Menu-bar client with per-user LaunchAgent; separate LaunchDaemon only for administrator-configured server roles | `launchd`, FSEvents and File Provider integration where feasible | Cloud/peer sync, collaboration client, peer host, local API and optional MCP | Keychain/Secure Enclave where available, hardened runtime, code signing/notarization, sandbox/file-consent compliance and XPC/Unix-socket access controls | 1.1–1.2 |
| Android (`.apk`, later trusted store builds) | Native phone/tablet client for pairing, workspace messages, selective/offline files, one-time drops, camera QR and controlled folder sync | Storage Access Framework persisted folder grants; WorkManager for deferrable work; user-visible foreground service only for active long transfers/listening permitted by Android | Peer client, collaborative editor, encrypted drop, offline cache and optional explicitly started peer host; no transparent FUSE drive | Android Keystore keys, biometric re-authorization option, network/battery policies, clear foreground notification, scoped storage, APK signing and reproducible build; never claim unrestricted continuous background service | 1.2 |
| NAS appliances | Vendor package only after a generic container is stable; browser/CLI administration | Bind-mounted approved shares, no host-root access and vendor startup integration | Always-on peer, mailbox, encrypted cache, snapshot target and onion endpoint | Separate volume/identity per instance, read-only container filesystem, explicit UID/GID mapping and tested Synology/QNAP upgrade/backup procedures | 1.2 |
| Docker/Podman/Kubernetes (OCI image) | Headless stateless control plane plus explicitly attached persistent state volumes | Rootless container preferred; health/readiness endpoints and one role per deployment | Mailbox, rendezvous, object store, relay, collaboration delivery and automation API/MCP | Signed SBOM/provenance, non-root image, seccomp/capability drop, secrets mounted rather than baked, quotas and network policies; Kubernetes is optional, not required for small installations | 1.1 |
| iOS/iPadOS | Research client after Android/core stabilization; no commitment to background folder mirroring | Document Picker/File Provider and OS-controlled background opportunities | Workspace messages, documents, downloads/uploads and collaboration client | Keychain/Secure Enclave, App Store review, strict background limitations and no promise of Android/Linux-equivalent always-on hosting | Research / post-1.2 |

### Headless daemon and server-function matrix

Each role is independently enabled. A small private installation can run peer sync only; enabling a “TuxDrive server” must not silently activate a directory, relay, object store or MCP endpoint.

| Function | Purpose and persisted state | Network exposure | Encryption / trust boundary | Administration and audit |
|---|---|---|---|---|
| Peer synchronization agent | Watches approved roots, calculates deltas, applies policy and maintains job/version state | Outbound plus an explicitly enabled peer listener | Existing pinned device/host keys; later workspace epochs encrypt operation/object keys end to end | CLI/API status, dry-run, pause, repair and per-job event stream; never expose arbitrary host paths |
| Cloud synchronization worker | Runs provider jobs, callbacks, streaming mounts and recovery without a GUI | Outbound provider APIs; loopback rclone control only | Provider OAuth remains in OS-protected local storage; vault content stays client-encrypted | Provider capability report, rate/policy controls, token-expiry health and redacted logs |
| Tor Onion endpoint controller | Creates an optional peer/server onion endpoint and manages authorized client material | Tor control interface locally; `.onion` listener through Tor | Tor client authorization adds a transport gate but does not replace TuxDrive device authentication or content encryption | Per-device issue/revoke/rotate, onion-only fail-closed policy and no onion/client key in ordinary logs |
| No-storage relay | Forwards already encrypted sessions when direct/onion routing is unavailable | Public TLS/QUIC/SSH endpoint selected by operator | Relay has no workspace/file key and no intentional content persistence; it still observes connection metadata | Bandwidth/concurrency caps, abuse response, short metadata retention and externally testable no-storage configuration |
| Encrypted mailbox | Temporarily queues opaque events/operations for offline devices | Authenticated HTTPS and optional onion endpoint | Per-device/workspace ciphertext; server cannot decrypt message, edit or filename content | Quota, expiry, acknowledgement deletion, replay protection and per-tenant abuse isolation |
| Rendezvous and device directory | Publishes signed reachability envelopes, device key packages and optional prekeys | Authenticated HTTPS/onion; federation later | Public/key-routing metadata only; key changes remain visible to verified clients and cannot bypass safety-number warnings | Append-only signed changes, equivocation detection, rate limits and privacy-preserving lookup design |
| Encrypted object/snapshot cache | Holds large immutable encrypted blocks and signed manifests while peers are offline | Authenticated HTTPS/onion object API | Client-side object encryption and opaque identifiers; service learns sizes/timing unless padding is enabled | Retention, garbage collection, integrity proof, storage quota and tenant-separated namespaces |
| Collaboration delivery service | Orders/delivers encrypted CRDT/workspace operations without deciding document truth | Authenticated streaming API and optional onion | Operations are signed and end-to-end encrypted; clients validate membership, causal context and resource limits | Backpressure, bounded histories, checkpoint availability and malicious-event quarantine |
| Local control API | Stable interface shared by GUI, CLI, service manager and tests | Unix-domain socket on Unix, ACL-protected named pipe on Windows; remote TCP disabled by default | OS peer credentials plus capability/scoped tokens; no provider-token passthrough | Full request audit for mutation, idempotency keys, schema/version negotiation and destructive-operation confirmation |
| Remote administration API | Optional automation for an owned headless server | HTTPS/mTLS or authenticated onion only; separate listener from data plane | OAuth 2.1/mTLS with audience-bound scopes; never reuse cloud-provider access tokens | Disabled by default, IP/onion policy, short tokens, administrator consent, rate limits and immutable security events |
| MCP server | Allows approved AI clients to inspect health and propose bounded actions through the local API | STDIO for same-user local clients; optional authenticated HTTP only when explicitly enabled | Read-only tools by default; contents, credentials, private keys and unrestricted path reads are not MCP resources; mutations require capability scopes and user confirmation | Tool-by-tool enablement, argument/path validation, result redaction, consent receipts, size limits and complete AI-action audit |
| Update and attestation service | Publishes signed manifests, supported protocol versions and reproducible artifacts | Public HTTPS mirrors; optional private enterprise mirror | Offline release signature verification, hashes, rollback protection and staged channels | Stable/beta channels, SBOM/provenance, minimum secure version and emergency revocation without silent downgrade |

### Versioned API and SDK surface

| Interface | Initial scope | Default transport | Security model | Compatibility rule |
|---|---|---|---|---|
| `tuxdrive` CLI | Accounts, jobs, peers, workspace membership, sync/stream control, diagnostics, backup and server-role lifecycle | Local API socket/pipe | Same-user access plus explicit elevation only for service installation | Machine-readable JSON mode is stable; human text may evolve |
| Local control API | Configuration schema, health, job lifecycle, event subscription, reviewed recovery and safe file/workspace operations | Unix socket / Windows named pipe | OS peer identity, per-client capability grant, request size/path allowlists and confirmation challenges | Versioned OpenAPI/Protocol Buffers contract with at least one prior major supported during migration |
| Remote administration API | Fleet inventory, policy deployment, server-role health, key rotation and audit export | HTTPS/mTLS or onion HTTPS | OAuth 2.1 resource/audience binding, narrow scopes, PKCE for interactive clients and separate service credentials | Opt-in endpoint; never exposes generic filesystem or shell execution |
| Event API | Sync progress, errors, membership/key changes, audit and collaboration delivery | Local stream; authenticated WebSocket/SSE remotely | Resume cursor bound to authorization context, bounded replay and redaction | Events carry schema version, stable ID, causal timestamp and sensitivity class |
| Core SDK | Embed pairing, manifests, crypto envelopes, delta planning and workspace validation in official clients | In-process FFI/language binding | Safe handles, zeroization boundaries and no raw private-key export | Conformance vectors define cross-language behavior before third-party support is claimed |
| MCP server | Resources for redacted health/capabilities/audit summaries; tools for dry-run, locate, sync proposal and explicitly approved actions | STDIO locally; Streamable HTTP only when deliberately configured | MCP authorization for HTTP, audience-bound tokens, least-privilege scopes, no token passthrough and visible consent for tools | Pin a tested MCP specification date; advertise capabilities accurately and reject unknown/unsafe arguments |

The first MCP release should expose only `health`, `list_accounts_redacted`, `list_jobs`, `job_status`, `recent_errors_redacted`, `provider_capabilities` and `sync_dry_run`. Later mutation tools such as `start_sync`, `pause_job`, `restore_version` or `share_file` require an application-generated confirmation challenge that identifies the exact job/path/recipients and expires quickly. `delete`, raw credential access, arbitrary filesystem reads, shell execution and bulk export remain unavailable through MCP.

### Rank 20 delivery gates

1. **Core extraction:** versioned configuration and protocol core passes the existing Linux suite without GTK, rclone process control is isolated, and golden invitations/manifests work across two independent implementations.
2. **Linux headless reference:** Ubuntu Server package, systemd hardening, CLI/local API, migration, backup/restore and unattended 30-day peer/cloud endurance tests.
3. **API security:** published OpenAPI/protobuf schemas, threat model, capability scopes, fuzzing, malformed-path tests, rate limits and an external review of remote/MCP authorization.
4. **Windows and macOS:** signed installers, platform key stores, native lifecycle/filesystem adapters and cross-platform conflict/delta tests against Linux.
5. **Server roles:** rootless OCI packages for mailbox/rendezvous/object/relay roles, each separately deployable with quota, retention and recovery tests.
6. **Android APK:** signed reproducible APK, persisted SAF roots, foreground/background compliance, encrypted local cache, QR pairing and offline/online convergence with desktop peers.
7. **MCP preview:** local read-only STDIO server first, opt-in authenticated HTTP second, red-team testing for prompt injection, confused-deputy behavior, data exfiltration and destructive tool chaining.
8. **Stable cross-platform declaration:** protocol compatibility matrix, upgrade/downgrade rules, recovery drills, third-party security assessment and documented feature gaps per platform.

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

Versions 0.10.0–0.13.0 delivered live Nautilus integration, per-file offline rules, transfer policies, adaptive provider controls and baseline health observability; 0.20.0 added reliable root/item hydration and per-item progress/completion badges. Next add throughput, cache accounting, retry depth and live backend capability probes.

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
- Android's [Storage Access Framework](https://developer.android.com/guide/topics/providers/document-provider) and [background/foreground service restrictions](https://developer.android.com/develop/background-work/services/fgs/restrictions-bg-start) require user-granted document trees and OS-compliant scheduled or visible work; an APK cannot honestly promise an unrestricted desktop-style daemon.
- Windows supports non-interactive long-running work through the [Service Control Manager](https://learn.microsoft.com/windows/win32/services/services), while macOS distinguishes user LaunchAgents from system LaunchDaemons under [`launchd`](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/DesigningDaemons.html); TuxDrive should run per-user unless a server role explicitly requires a separately secured service identity.
- The dated [Model Context Protocol specification](https://modelcontextprotocol.io/specification/2025-11-25) requires visible consent and careful tool handling, and its [HTTP authorization model](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization) requires resource/audience-bound access tokens and forbids token passthrough. TuxDrive's MCP adapter therefore remains a narrow client of the same control API rather than a privileged back door into files or provider credentials.
