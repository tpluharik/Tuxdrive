# TuxDrive security policy

## Supported release

TuxDrive 0.15.1 is the supported security baseline. Older packages retained for historical reference must not be installed on production systems.

Report suspected vulnerabilities privately through GitHub's **Security → Report a vulnerability** workflow. Do not place credentials, peer invitations, Onion authorization material, private keys, or personal filenames in a public issue.

## Security boundaries in 0.15.1

- Update metadata is signed by the offline Ed25519 release key, expires, and binds the version, URL, package digest and release notes. The updater additionally checks the Debian package name/version before PolicyKit installation.
- Provider credentials are held in rclone's encrypted configuration. A random configuration password is stored in GNOME Secret Service. Independently encrypted rclone configurations are not overwritten.
- Untrusted relative paths are confined beneath their configured root. Security-sensitive atomic installs use no-follow directory descriptors to resist symlink replacement races.
- Tor-only and no-public-IP shares bind locally; invitations carry allowed transports and do not contain forbidden relay fallback.
- Delta transactions are signed by an authorized Ed25519 peer identity, resource bounded, hash verified, and atomically installed.

## Known limitation intentionally retained

TuxDrive currently uses rclone's shared SFTP endpoint for peer folders. Directional roles are enforced by TuxDrive transfer jobs, and an all-read-only endpoint becomes server-wide read-only, but a hostile generic SFTP client in a mixed-role share does not yet receive per-key filesystem authorization. One-time drops terminate/restart the endpoint after first consumption but do not yet have a separately chrooted per-key server.

Do not grant a peer key to an untrusted person under the assumption that the current role label is a hostile-client sandbox. Per-device roots and server-side authorization are assigned to the future headless/peer server layer.

## Release-key operation

Only the public update key is committed. Keep the private key offline or in a protected release environment. Create manifests with `scripts/sign-update.py`; never print the private key in CI logs. Compromise requires a reviewed application release which embeds a replacement public key.

## Release gates

Every release must pass unit tests, source compilation, high-severity Bandit checks, `pip-audit`, Debian installed-layout inspection, signed-manifest verification, and SBOM generation. Security-sensitive path, update, credential, Tor, peer, and recovery changes require regression tests.
