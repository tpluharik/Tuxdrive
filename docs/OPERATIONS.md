# TuxInDrive operations guide

This guide covers normal administration, health checks, traffic policy,
backup, recovery, and incident response for TuxInDrive 0.26.5. User-facing
procedures are in the [user guide](USER_GUIDE.md); persisted fields and exact
paths are in [Configuration](CONFIGURATION.md).

## Healthy state

A healthy installation has connected accounts, no unexpected disabled jobs,
no unresolved mass-change preview, and recent successful status for scheduled
jobs. Streaming jobs additionally report a mounted drive. A quiet application
may still perform jittered metadata reconciliation and update checks, but those
requests share the global network controller and adaptive backoff.

Use the interface in this order:

1. Check the account status in the left pane. **Needs attention** means the
   account should be reauthenticated or reinitialized before dependent jobs.
2. Check **Active syncs**, the status below each folder, and **Activity**.
3. Open **View log** for the affected job. Use **History**, **Conflicts**, or
   **Verify** only after identifying the mapping and direction.
4. Confirm Settings network, battery, metered-network, and schedule policies.
5. For streaming, verify that the mount tool is installed and the selected
   mount point is not already owned by another process.

## Network policy

The global bandwidth value is the primary congestion control. Start with a
limit below the reliable upload capacity of the connection; saturated upload
queues can make unrelated browsing and DNS appear disconnected even when the
link is still up. Directional syntax such as `2M:10M` protects a slower upload
while allowing faster downloads.

One controller covers full/incremental synchronization, streaming, metadata
scans, verification, repair, update downloads, GitHub, Proton, and Android.
It also limits concurrent native network work and adds scan jitter. Per-job
limits remain useful for lower-priority folders but cannot override the global
ceiling upward.

For constrained links:

- disable metered-network work or set a lower global ceiling;
- select `balanced` or `low_traffic` streaming refresh;
- widen scheduled intervals instead of repeatedly pressing **Sync now**;
- keep one verification running at a time;
- avoid pinning a large streaming tree for offline use during normal work.

The Network panel reports whole-device counters. It is observational and may
include unrelated applications; it is not evidence that every displayed byte
came from TuxInDrive.

## Logs and diagnostics

`tuxindrive.log` rotates at 2 MiB with three backups. `crash.log` records Python
and thread failures. Both are private files in the platform log directory:

- Linux: `~/.local/state/tuxindrive/` (or `$XDG_STATE_HOME`)
- Windows: `%LOCALAPPDATA%\Logs\tuxindrive\`
- macOS: `~/Library/Logs/tuxindrive/`

Legacy `tuxdrive` directories remain authoritative if they predate the branded
directory. Individual job logs are linked from **View log**. Logs are designed
to redact credentials, but review them for filenames, account names, hostnames,
and local paths before sharing.

Record these facts with an incident: application/platform version, provider,
job mode and direction, first failure time, account status, current network
policy, exact UI error, and whether manual provider access works. Do not send
passwords, OAuth tokens, private keys, encrypted rclone configuration, update
signing keys, or profile passphrases.

## Authentication recovery

An authentication failure stops the affected job instead of repeatedly
hammering the provider. From the account menu, reauthenticate/reconnect; the
application validates the replacement remote before resuming. If an rclone
remote exists but is unusable, automatic reinitialization rebuilds the provider
configuration only after the account flow supplies valid authorization.

For Proton, use the official CLI browser login and ensure Secret Service is
available. For GitHub, test the configured SSH agent or system Git credential
helper; TuxInDrive does not store a token in its configuration. For peer jobs,
check the pinned SSH host key before accepting any changed identity.

Do not delete the account as a first response. Removing it can orphan mappings
and obscures whether the fault is credentials, provider availability, clock,
DNS, proxy, or local policy.

## Synchronization recovery

### Safety preview blocks a run

Review the proposed count and direction. Confirm that the local and cloud
roots still contain the expected data. Restore missing source data before
accepting changes. Raise deletion thresholds only for a known intentional bulk
operation, then restore the safer value.

### Two-way baseline is damaged

Use the application's reinitialize/resync action. It creates a deliberate
merge baseline instead of treating one side as disposable. Review conflicts
after completion. Never remove bisync state while another run is active.

### Interrupted incremental job

Wait for the reserved job to finish or fail. Incremental work reserves its job
atomically before waiting for network admission, so starting another run will
not repair it and may only queue more intent. When idle, run a normal sync and
then Verify if the prior failure involved staged content.

### Streaming drive is unavailable

Disconnect through TuxInDrive, close processes using the mount, and reconnect.
Do not manually delete dirty cache content. If free space is low, remove
offline pins or adjust cache limits; the cache manager protects open, dirty,
pinned, and recently used objects.

### Integrity or conflict problem

Run **Verify** before **Repair**. Preserve both sides and version history until
the report is understood. Conflict copies and recovery archives exist so that
repair does not silently choose an unsafe winner.

## Backup and restore

Create an encrypted profile backup from Settings and select whether credentials
are included. The visible cloud object is
`TuxInDrive/TuxInDrive-Profile.tdx`. Keep the passphrase separately; it cannot
be recovered. A restore validates the envelope and model, then saves the old
desktop configuration as `config.json.before-migration`.

A profile is not a backup of synchronized user files. Maintain provider
versions or an independent backup for irreplaceable data. Peer private keys
and rclone credentials are included only when explicitly requested.

For Android, create a new credential-enabled profile after upgrading. Either
select `TuxInDrive/TuxInDrive-Profile.tdx` in Android's document picker or
choose **Show mobile transfer QR** on the desktop, enter/confirm the same
14-character-or-longer profile passphrase, and scan every numbered frame with
**Accounts → Scan encrypted profile QR**. A successful import reports the
number of unlocked, verified cloud accounts. A message that an older profile
lacks the mobile unlock key means the old file cannot complete migration;
create a fresh backup on the source desktop. Do not confuse the profile
passphrase with the separate raw-rclone password field.

Before a manual configuration repair:

1. Stop TuxInDrive and confirm no transfer/mount process remains.
2. Copy the entire configuration and data roots to protected storage.
3. Preserve `.invalid`, `.before-migration`, recovery, peer, and bisync state.
4. Make the smallest change, restart, and validate one non-destructive job.

## Updates and release channels

The updater trusts only a valid, unexpired Ed25519-signed platform manifest,
approved GitHub origin, version-bound filename, maximum size, and SHA-256.
If **Download and install** is disabled, the installed version is already the
latest trusted manifest version or the channel could not be validated. Check
the log and the platform's `releases/<platform>/latest-v2.json`; do not bypass
signature checks or download an installer from an untrusted mirror.

Platform packages live as durable assets on the matching GitHub Release. The
repository folders contain signed channel manifests and package-location
documentation, not large installer binaries. See [Release process](RELEASES.md).

## Incident response

If TuxInDrive appears to disrupt connectivity:

1. Press **Stop** on active jobs and disconnect streaming drives.
2. Confirm whether the connection recovers and whether another device is also
   affected; preserve logs and timestamps.
3. Lower the directional global limit, disable metered work, and retry one
   small job.
4. Check for simultaneous verification, offline hydration, GitHub/Proton jobs,
   or external cloud clients using the same connection.
5. If the link still disconnects with all jobs stopped, investigate the router,
   VPN, DNS, Wi-Fi driver, ISP, and provider independently.

TuxInDrive cannot reset a network interface or router through its normal
transfer paths. It can, however, fill a weak link if limits are disabled or too
high. Keep the global controller enabled while diagnosing.

For suspected credential exposure, stop jobs, revoke the provider session or
peer key, preserve evidence, reconnect with new credentials, and follow the
private reporting instructions in [SECURITY.md](../SECURITY.md).

## Safe maintenance checklist

- Confirm a recent encrypted profile backup and independent file backup.
- Apply only signed releases from the platform channel.
- Keep rclone, Git, Proton CLI, FUSE/mount helpers, OS keyring, and the operating
  system supported and patched.
- Review disabled accounts, expired one-time drops, authorized peer keys,
  relay/Tor policy, old recovery versions, and unused offline pins.
- Test restore and one two-way safety preview after major platform changes.
