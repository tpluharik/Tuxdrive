# TuxInDrive Server preview

TuxInDrive Server is the first functional Linux implementation of the server
and headless-agent plan. It is packaged separately as
`tuxindrive-server_VERSION_all.deb`; installing the desktop package does not
start a server. The client integration is disabled by default and becomes
available only after **Settings → Enable TuxInDrive server integration
(preview)** is selected.

This release establishes a bounded, self-hostable foundation. It is not a
public multi-tenant cloud service and does not weaken direct peer operation.
Direct LAN/SFTP synchronization continues to work without this server.

## Implemented roles

Every role is independently named in `enabled_roles`. Removing a role makes
its endpoint return `404`; it does not silently enable a substitute.

| Role | First-version behavior |
|---|---|
| `agent` | Loads the normal TuxInDrive configuration without GTK, reuses `SyncEngine`, `PeerManager`, transfer policy and the global bandwidth controller, schedules enabled non-streaming jobs, starts enabled peer listeners (including configured Tor peer services), and exposes redacted job state plus sync/dry-run/cancel actions. |
| `mailbox` | Queues opaque client-encrypted messages for offline devices with tenant isolation, expiry, acknowledgement deletion, count/byte bounds and audit events. |
| `rendezvous` | Publishes bounded opaque signed device reachability envelopes with replacement and short expiry. Clients remain responsible for signature/key-change verification. |
| `objects` | Stores content-addressed encrypted blocks/snapshots by SHA-256, with tenant isolation, deduplication, expiry and quotas. The server receives ciphertext, size and timing—not content keys or plaintext names. |
| `collaboration` | Orders and returns bounded encrypted collaboration operations per opaque workspace identifier. It does not decide document truth or decrypt operations. |
| `relay` | Implements an authenticated HTTP `CONNECT` byte relay. A destination must appear exactly in `relay_targets`; sessions are time/byte bounded and only transferred-byte totals enter audit. Nested peer encryption remains mandatory. |
| `attestation` | Returns the running server version and explicitly configured signed updater manifests. It never signs or rewrites release metadata. |
| `mcp` | Implements a read-only MCP JSON-RPC preview with `health`, `list_jobs`, and `recent_audit`. There is no delete, arbitrary filesystem, credential, shell or unconfirmed mutation tool. |

The authenticated HTTP API is also the first remote/local administration API.
The unauthenticated `/healthz` endpoint returns only `{"status":"ok"}` for a
service manager. All `/v1/` endpoints require a bearer token.

## Installation

Build and inspect the package:

```bash
sh scripts/build-server-deb.sh
dpkg-deb --info dist/tuxindrive-server_0.26.12_all.deb
dpkg-deb --contents dist/tuxindrive-server_0.26.12_all.deb
sudo apt install ./dist/tuxindrive-server_0.26.12_all.deb
```

The package creates a locked `tuxindrive-server` system account, private
configuration/state directories and a hardened systemd unit. It initializes a
random 384-bit API token once. Read and then securely remove its bootstrap copy:

```bash
sudo cat /var/lib/tuxindrive-server/bootstrap-token
sudo shred -u /var/lib/tuxindrive-server/bootstrap-token
sudo systemctl enable --now tuxindrive-server
curl http://127.0.0.1:9443/healthz
```

The service is not enabled automatically because installation must not expose a
new network service without an administrator's explicit action.

## Client setup

1. Open desktop **Settings**.
2. Select **Enable TuxInDrive server integration (preview)**.
3. Enter the server origin. Plain HTTP is accepted only for
   `localhost`, `127.0.0.1`, or `::1`; a remote origin must use HTTPS.
4. Paste the bootstrap/API token. TuxInDrive saves it in Secret Service,
   Windows Credential Manager, or macOS Keychain—not in `config.json`.
5. Optionally enter a private CA file, then select **Test server connection**.
6. Save Settings. Disabling the flag removes the live client object but does
   not delete server data or the native credential entry.

The first desktop integration checks authenticated health/capabilities and
provides the connection object to later mailbox/object/collaboration UI work.
It does not redirect existing direct or cloud jobs through the server merely
because the feature flag is enabled.

## Configuration

The default configuration is `/etc/tuxindrive-server/server.json`:

```json
{
  "schema": 1,
  "bind": "127.0.0.1",
  "port": 9443,
  "tls_certificate": "",
  "tls_private_key": "",
  "database": "/var/lib/tuxindrive-server/server.sqlite3",
  "client_config": "",
  "enabled_roles": ["agent", "mailbox", "rendezvous", "objects", "collaboration", "relay", "attestation", "mcp"],
  "token_hashes": {"SHA256_OF_TOKEN": "owner"},
  "quota_mib_per_tenant": 512,
  "default_ttl_seconds": 86400,
  "global_bandwidth_limit": "10M",
  "relay_targets": [],
  "update_manifests": []
}
```

`token_hashes` maps token SHA-256 digests to tenant IDs. The bootstrap mapping
uses the reserved tenant ID `owner`; only that token may list or start/cancel
headless synchronization jobs. Other tenant tokens can access only their own
storage, coordination, statistics and audit rows. The raw token is never
stored in the server JSON or database. To add a tenant, generate a strong random
token, place its SHA-256 digest in the map, deliver the raw token through a
separate trusted channel and restart the service. A production reverse proxy
must not log `Authorization` headers.

Set `client_config` only when the system service should run preconfigured cloud
or peer jobs. Copy a deliberately prepared configuration into a directory
readable by the service account; do not point the system service at an ordinary
desktop user's home. Provider credentials must separately exist in the service
account's rclone/Proton credential context.

For a non-loopback bind, both TLS files are mandatory and startup fails closed
without them. Keep port `9443` behind a host firewall. Use a separately
authenticated Tor reverse proxy if the API itself should be reachable through
an Onion Service; configured peer Onion Services remain managed by the existing
per-share Tor implementation.

Validate after editing:

```bash
sudo -u tuxindrive-server tuxindrive-server check \
  --config /etc/tuxindrive-server/server.json
sudo systemctl restart tuxindrive-server
```

## API outline

- `GET /v1/health`, `GET /v1/capabilities`, `GET /v1/stats`
- `GET /v1/jobs`, `POST /v1/jobs/ID/sync|dry-run|cancel`
- `POST|GET /v1/mailbox`, `DELETE /v1/mailbox/ID?recipient=DEVICE`
- `POST /v1/objects`, `GET /v1/objects/SHA256`
- `POST /v1/rendezvous`, `GET /v1/rendezvous/DEVICE`
- `POST|GET /v1/collaboration?workspace=ID`
- `CONNECT HOST:PORT` for exact configured relay targets
- `GET /v1/attestation`, `GET /v1/audit`, `POST /v1/mcp`

Opaque payload fields use strict base64 and are limited to 12 MiB per request.
JSON bodies are limited to 16 MiB, list results are capped, TTLs are bounded,
per-tenant storage quotas are atomic inside SQLite transactions, expired rows
are removed before access, and source requests are rate-limited. SQLite uses
WAL plus full synchronous durability and private permissions.

## Security and present limits

- The server authenticates transport/API access; end-to-end encryption and
  signatures remain client responsibilities. Uploading plaintext to an opaque
  endpoint does not make it encrypted.
- The server observes tenant, recipient/workspace opaque identifiers, sizes,
  timing, IP addresses and relay destinations. It cannot promise anonymity.
- Token hashing protects the stored verifier but is not a substitute for a
  high-entropy token. A stolen bearer token authorizes that tenant until it is
  removed and the service restarted.
- The first release uses one process and SQLite. It is suited to a personal or
  small trusted deployment, not an unreviewed internet-scale service.
- Federation, hardware-backed service identity, web administration, OCI/NAS
  appliances, push notification adapters and mutating MCP tools remain future
  compatibility layers. The role interfaces are deliberately versioned so
  they can be added without changing ciphertext or silently widening access.
- A formal external protocol/security review and long-duration fault-injection
  test remain required before removing the **preview** label.

See [Security hardening](SECURITY_HARDENING.md), [Architecture](ARCHITECTURE.md),
[Configuration](CONFIGURATION.md), [Operations](OPERATIONS.md), and
[Roadmap](ROADMAP.md) for the surrounding client trust boundaries.
