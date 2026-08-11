# TuxDrive security policy

## Supported release

TuxDrive 0.19.2 is the supported security baseline. Older packages retained for historical reference must not be installed on production systems.

Report suspected vulnerabilities privately through GitHub's **Security → Report a vulnerability** workflow. Do not place credentials, peer invitations, Onion authorization material, private keys, or personal filenames in a public issue.

## Security boundaries in 0.19.2

- Update metadata is signed by the offline Ed25519 release key, expires, and binds the version, URL, package digest and release notes. A fixed privileged helper independently verifies that manifest, copies the package to a root-only staging directory, and checks the immutable copy before APT installation.
- Provider credentials are held in rclone's encrypted configuration. A random configuration password is stored in GNOME Secret Service. Independently encrypted rclone configurations are not overwritten.
- Untrusted relative paths are confined beneath their configured root. Security-sensitive atomic installs use no-follow directory descriptors to resist symlink replacement races.
- Tor-only and no-public-IP shares bind locally; invitations carry allowed transports and do not contain forbidden relay fallback.
- Delta transactions are signed by an authorized Ed25519 peer identity, resource bounded, hash verified, and atomically installed.
- Python-package installations require `cryptography` 50.0.0 or newer after four advisories affected the former 46.x floor. Ubuntu packages consume Canonical-maintained security backports through APT.

The detailed control inventory, credential locations, upgrade checklist, dependency response, verification procedure, and operator guidance are maintained in [docs/SECURITY_HARDENING.md](docs/SECURITY_HARDENING.md).

## Known limitation intentionally retained

TuxDrive 0.19.2 retains the separate listener and one-key authorization file introduced for every enabled peer in 0.19.1. Read-only/receive-only listeners are server read-only; send-only and one-time-drop listeners are rooted in dedicated inboxes. This prevents a modified generic SFTP client from using a role-limited key to browse the containing workspace. One-time-drop byte/file quotas and immediate completed-upload session termination remain defense-in-depth roadmap work.

Do not grant a peer key to an untrusted person under the assumption that the current role label is a hostile-client sandbox. Per-device roots and server-side authorization are assigned to the future headless/peer server layer.

## Release-key operation

Only the public update key is committed. Keep the private key offline or in a protected release environment. Create manifests with `scripts/sign-update.py`; never print the private key in CI logs. Compromise requires a reviewed application release which embeds a replacement public key.

## Release gates

Every release must pass unit tests, source compilation, high-severity Bandit checks, `pip-audit`, Debian installed-layout inspection, signed-manifest verification, and SBOM generation. Security-sensitive path, update, credential, Tor, peer, and recovery changes require regression tests.

Dependency findings must be fixed or explicitly documented with applicability, compensating controls, owner, and expiry. CI ignores are not a substitute for analysis. Ubuntu backported fixes must be verified against Ubuntu package security records rather than guessed from the upstream version alone.
