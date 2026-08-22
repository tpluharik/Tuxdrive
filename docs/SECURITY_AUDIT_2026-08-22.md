# TuxInDrive source security audit — 2026-08-22

## Executive summary

This review covered the TuxInDrive 0.26.19 client, optional server, Android
application, packaging, update path, CI workflows, and security-relevant tests.
It found **one high-severity issue, two medium-severity issues, and three
lower-severity hardening opportunities**. No known vulnerable Python dependency,
committed private key, common GitHub/AWS token pattern, or high-severity Bandit
finding was detected.

The highest-risk issue is in the optional Linux server package. The service
account owns `/etc/tuxindrive-server`, while the privileged configuration helper
writes a predictable `server.json.tmp` file without no-follow/exclusive-open
protection. A compromised server process could prepare a symlink and cause a
later administrator save to truncate a root-owned file. **Do not expose the
0.26.19 server preview to untrusted networks or treat its GUI configuration
boundary as hardened until TID-2026-01 is fixed.** The desktop client and its
signed update path do not use this server configuration helper.

The findings below describe the audited 0.26.19 snapshot. The following status
section records which remediations subsequently landed in 0.26.20.

## Remediation status in 0.26.20

- **TID-2026-01 fixed:** configuration is root-owned/read-only to the service;
  privileged writes use randomized descriptor-relative `O_EXCL|O_NOFOLLOW`
  replacement and the service no longer has an `/etc` write path.
- **TID-2026-02 fixed:** request workers and per-source admission are bounded;
  connections have deadlines; relays are bounded globally/per tenant, expire
  when idle, use both bandwidth clocks, and run under systemd resource ceilings.
- **TID-2026-04 addressed:** every product path generates 48-byte random tokens;
  documentation rejects human-selected tokens and retains rotation guidance.
- **TID-2026-05 fixed:** Android explicitly validates redirects/final origins,
  disables cleartext, bounds advertised/received bytes, durably replaces the
  package, and scopes install permission to the sideload flavor.
- **TID-2026-06 fixed:** configured sensitive files reject symlinks, unsafe
  ownership and writable/public modes before use.
- **TID-2026-03 partially fixed:** Python build tools are exact-versioned,
  automatic MSYS2/Homebrew updates are disabled, a release environment and SBOM
  are present. Native package identities, signed provenance and fully immutable
  Windows/macOS package-manager snapshots require external certificates and
  release infrastructure and remain open.

## Scope and method

The review examined approximately 26,000 lines of tracked Python, Kotlin,
shell, and workflow code, with focused manual analysis of authentication,
network listeners, update verification, subprocess boundaries, credential
storage, filesystem confinement, mobile import/update flows, server packaging,
and release publication.

Checks performed:

- recursive Bandit 1.9.4 analysis of `src/`, `scripts/`, and `packaging/`;
- `pip-audit` 2.10.1 against `requirements-security.txt`;
- tracked-source searches for private keys and common AWS/GitHub token formats;
- Python source compilation;
- manual review of all medium Bandit results and security-sensitive low results;
- manual review of Android manifest/update/profile-import boundaries;
- manual review of GitHub Actions dependency and artifact publication paths;
- manual review of server authentication, request parsing, relay, SQLite,
  PolicyKit helper, systemd unit, and Debian maintainer scripts.

The review did not include live cloud-provider accounts, Windows/macOS runtime
instrumentation, a hostile multi-host peer lab, Android device testing, fuzzing,
or a full historical-secret scan of every unreachable Git object. Those remain
release-assurance gaps rather than evidence of safety.

## Findings

### TID-2026-01 — High — server configuration crosses the root boundary unsafely

**Affected code:** `packaging/server/DEBIAN/postinst`,
`packaging/server/tuxindrive-server.service`, `src/tuxindrive/server.py`, and
`src/tuxindrive/server_admin.py`.

The package makes `/etc/tuxindrive-server` owned and writable by the
`tuxindrive-server` service account. The systemd sandbox explicitly grants the
service write access to that directory. The root PolicyKit helper later saves
configuration through `_private_write()`, which opens the fixed sibling name
`server.json.tmp` with `O_CREAT|O_TRUNC`, follows symlinks, and then replaces the
real configuration. It also changes the completed file back to service-account
ownership.

**Impact:** after compromising the unprivileged server service, an attacker can
modify trusted server policy directly. More seriously, the attacker can prepare
the fixed temporary name as a symlink; the next administrator save can truncate
a root-writable target. Exploitation requires local control of the service
account and an administrator configuration save, but it violates the intended
privilege boundary and can cause root-level file destruction.

**Required fix:**

1. Make `/etc/tuxindrive-server` root-owned and non-writable by the service;
   make `server.json` `root:tuxindrive-server` mode `0640`.
2. Initialize and migrate configuration as root. Keep only runtime state under
   `/var/lib/tuxindrive-server` owned by the service account.
3. Remove `/etc/tuxindrive-server` from the unit's `ReadWritePaths`.
4. Replace `_private_write()` at this boundary with a directory-descriptor
   operation using a randomized temporary name, `O_CREAT|O_EXCL|O_NOFOLLOW`,
   file and directory `fsync`, verified parent ownership/mode, and `renameat`.
5. Add package upgrade migration that repairs existing ownership safely without
   following links.
6. Add regression tests for a pre-created symlink, hostile directory ownership,
   installed package modes, and the effective systemd write set.

**Release gate:** block remote server publication until the package and
privileged-helper tests pass in an isolated Debian/Ubuntu VM.

### TID-2026-02 — Medium — authenticated slow clients can exhaust server resources

**Affected code:** `src/tuxindrive/server.py`.

The preview server uses an unbounded `ThreadingHTTPServer`. An authenticated
request body is read in full according to `Content-Length` with no per-connection
read deadline. Relay `CONNECT` sessions also consume one thread for up to one
hour, with no global or per-tenant concurrent-connection limit. The existing
request rate limiter and payload ceilings are useful but do not limit blocked
threads, slow uploads, aggregate in-memory bodies, or simultaneous relay
sessions. Relay bytes are not governed by the application's global bandwidth
controller.

**Impact:** a tenant with a valid, stolen, or intentionally shared token can
degrade or exhaust the server's threads, memory, descriptors, and bandwidth.
The default loopback binding reduces exposure, but remote server deployments are
affected.

**Required fix:** use a bounded worker pool or admission semaphore with global,
per-tenant, and per-source limits; enforce header, body, write, idle, and total
request deadlines; reject unsupported transfer encodings; decode large payloads
incrementally into bounded private temporary storage; limit concurrent relay
sessions and relay bytes/time per tenant; route relay traffic through the global
bandwidth controller; and set `TasksMax`, `LimitNOFILE`, `MemoryMax`, and shutdown
deadlines in the systemd unit. Add slow-body, disconnect, concurrency, and relay
quota integration tests.

### TID-2026-03 — Medium — release inputs and platform binaries are not fully pinned

**Affected code:** `.github/workflows/build.yml` and
`.github/workflows/platform-packages.yml`.

GitHub Actions are commit-SHA pinned, and the Android rclone source is checked
against an expected commit. However, Windows updates MSYS2 and installs packages
without immutable versions; macOS installs current Homebrew formulae; PyInstaller
and its transitive Python dependencies are resolved at build time; and the
security tools are installed without a lock. Release artifacts from these jobs
can be published automatically. Windows packages are not Authenticode signed,
and macOS currently uses ad-hoc signing rather than Developer ID signing and
notarization.

**Impact:** a compromised or unexpectedly changed upstream package can alter a
published installer despite the repository source being unchanged. Signed
TuxInDrive update metadata protects transport and selection, but it faithfully
delivers whatever binary the release job produced.

**Required fix:** use hash-locked Python requirements, immutable MSYS2 snapshots
or exact package versions, pinned Homebrew bottles/formula commits or a versioned
build image, and verified tool downloads. Produce per-platform SBOMs and signed
provenance attestations, require an approved release environment before publish,
add reproducibility comparison where feasible, Authenticode-sign Windows
installers, and Developer-ID-sign/notarize macOS artifacts. Correct documentation
that previously described all release dependencies as pinned.

### TID-2026-04 — Low — server token policy relies on generated-token entropy

The GUI/bootstrap path generates a 48-byte random bearer token and stores only
its SHA-256 digest, which is appropriate for such high-entropy tokens. The
configuration format itself accepts precomputed digests, so a manually created
low-entropy token remains vulnerable to offline guessing after configuration
theft.

Document generated tokens as mandatory, reject or migrate manual weak-token
paths, support rotation and token identifiers, and consider a keyed or
password-hard verifier only if human-selected tokens remain supported.

### TID-2026-05 — Low — Android sideload updater needs tighter network policy

The Android updater verifies the Ed25519 manifest and package SHA-256 and uses a
non-exported `FileProvider`, preventing a redirected download from substituting
code without the release key. It nevertheless follows HTTP redirects without
revalidating the final HTTPS origin and requests `REQUEST_INSTALL_PACKAGES` in
the common manifest.

Revalidate every redirect/final origin, enforce expected response length and a
Network Security Config, and keep package-install permission only in the
sideload distribution flavor. Retain digest, signature, size, and atomic-file
checks.

### TID-2026-06 — Low — server TLS/key paths need stronger file validation

Server TLS, database, and client-configuration paths are validated mainly as
existing files. After fixing configuration ownership, validate canonical
allowlisted roots where practical, open sensitive files without following
symlinks, and reject private keys with unsafe owner or mode. Add tests for
symlink and replacement races.

## Confirmed controls and reviewed scanner findings

- Update manifests bind version, platform, architecture, filename, origin,
  expiry, size, digest, and Ed25519 signature; the Linux privileged helper
  independently re-verifies a root-only staged copy.
- Remote client URLs require HTTPS except for loopback HTTP and reject userinfo,
  query, fragment, and unexpected paths.
- Server bearer tokens use constant-time digest comparison; SQLite values are
  parameterized and the few dynamic table names are fixed internal constants.
- Profile transfer uses bounded authenticated encryption and validates QR frame
  sequence and digest before state replacement.
- Android backup is disabled; its update `FileProvider` is not exported.
- GitHub repository and branch input is constrained to GitHub and validated
  before network or process use.
- rclone is invoked with argument arrays, credential configuration is private
  and encrypted, and sensitive OAuth child processes disable same-user process
  dumping on Linux.
- The reviewed Bandit medium findings for fixed or validated `urlopen` calls,
  fixed internal SQL table names, executable permissions, and root-only update
  staging were not independently exploitable in their current call paths.

## Automated results

| Check | Result |
|---|---|
| Bandit 1.9.4 (`src scripts packaging`) | 0 high, 11 medium, 99 low; medium findings manually triaged |
| pip-audit 2.10.1 (`requirements-security.txt`) | No known vulnerabilities found |
| Common tracked secret patterns | No private key, GitHub token, or AWS access-key match |
| Python compilation | Passed |

Static analysis is not proof of absence. Results are a dated snapshot and must
be repeated whenever code, dependencies, build images, or platform toolchains
change.

## Remediation order

1. **P0:** fix TID-2026-01 and publish a patched server package; advise current
   server users to keep it loopback-only or stopped meanwhile.
2. **P1:** implement bounded/deadline-aware server networking (TID-2026-02).
3. **P1:** make release inputs immutable and add native signing/provenance
   (TID-2026-03).
4. **P2:** complete token, Android updater, and sensitive-path hardening.
5. Repeat dependency/static checks, run the full unit suite and Android JVM
   tests, then execute the privileged package and hostile-network matrices before
   describing the findings as closed.
