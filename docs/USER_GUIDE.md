# TuxDrive User Guide

<p align="center"><img src="../branding/tuxdrive-logo.png" width="150" alt="TuxDrive penguin head logo"></p>

This guide covers TuxDrive 0.7.0 on Ubuntu 26.04: installation, provider authorization, direct encrypted peer sharing, cloud locations, selective synchronization, real-time callbacks, exceptions, streaming drives, tray controls, updates, logs, and recovery.

> The screenshots use sample names and paths. They do not contain real account information.

## 1. Install and start

Download the current Debian package and install it with one command:

```bash
sudo apt install ./tuxdrive_0.7.0_all.deb
```

Launch **TuxDrive** from Ubuntu's application menu. TuxDrive remains active in the system tray when its window is closed. On first start it verifies or installs its private cloud transfer engine.

![Main window overview](assets/01-main-window.svg)

The main window contains:

1. **Add account** (`+`) — connect Google Drive or Microsoft OneDrive.
2. **Cloud accounts** — connection and aggregate activity state.
3. **Account menu** — open online, reconnect OAuth, or remove an unused account.
4. **Add folder** — create a synchronized or streaming job.
5. **Job status icon** — connected, synchronizing, paused, or error.
6. **Job controls** — sync/mount, stop, open, share, edit, log, and remove.
7. **Enable switch** — pause or resume an individual job.
8. **Live activity log** — current application and transfer activity.
9. **Settings** — startup, notification, and minimized-start preferences.

The black-and-white penguin identifies TuxDrive itself. Each cloud service uses its provider icon while connected and in the account chooser; blue sync and red error badges show changing activity.

### Update TuxDrive

Open **Settings** and select **Check for updates**. A progress window shows repository checking, the available-version result, download percentage, package verification, system installation, and the final success or failure. If a newer version is available, choose **Download and install**. TuxDrive verifies the package checksum before Ubuntu displays its system authorization prompt. When installation completes, restart TuxDrive. If any stage fails, the existing installation remains unchanged and the result stays visible until you close it.

### Rename an item in TuxDrive

Select **Rename** on a synchronized or streaming job and enter the preferred display title. This changes only the label shown inside TuxDrive; it does not rename or move the local folder or its cloud folder.

## 2. Connect a cloud account

Select `+` or **Connect account**, then choose Google Drive, Microsoft OneDrive, Dropbox, Box, pCloud, MEGA, Proton Drive, or Nextcloud.

![OAuth account connection](assets/02-oauth.svg)

- **Account key** is TuxDrive's local identifier. Use letters, numbers, dot, dash, or underscore.
- **Display name** is the friendly name shown in the sidebar.
- **OAuth client ID/secret** are optional for personal testing. A dedicated provider application is recommended for regular or organizational use.
- Google Drive, OneDrive, Dropbox, Box, and pCloud normally open browser OAuth. Sign in on the provider's page and approve access; TuxDrive does not receive the cloud password.
- MEGA and Proton Drive use explicit provider credential fields. Nextcloud asks for the server URL, username, and preferably an app password. Secret values are protected before rclone stores them in its private configuration; they are never stored in TuxDrive's account JSON.
- Every provider exposes the same lazy-loading folder tree, multi-folder selection, two-way/one-way modes, and streaming-drive option after connection.
- Proton Drive support follows rclone's beta backend. TuxDrive disables that backend's metadata cache so changes made by another client can be discovered, but provider protocol changes may still require a future TuxDrive/rclone update.
- If the browser callback port is busy, cancel the old authorization window and retry. TuxDrive stops stale OAuth callback processes before opening a new session.

### Proton Drive authentication

Enter the Proton account email and password. If Proton reports that two-factor authentication is required, TuxDrive opens a separate dialog for the current code and retries verification. You may instead provide the account's OTP secret key during setup when recurring automatic authentication is appropriate. Enter a mailbox password only for older Proton accounts configured in two-password mode. TuxDrive tests a root-folder listing before it accepts the account, so an incomplete remote is no longer displayed as **Connected**.

If Proton Drive was added with TuxDrive 0.6.0 or 0.6.1 and folder browsing says that a username and password are required, open the account's menu and choose **Reconnect / refresh credentials**. Fill in the Proton fields; synchronized-job definitions do not need to be recreated.

Proton Drive support uses rclone's beta backend. Proton protocol changes may require an updated TuxDrive transfer engine, and Proton may apply additional authentication checks to some accounts.

The account menu provides:

- **Open online** — opens the provider website.
- **Reconnect OAuth** — refreshes authorization without deleting jobs.
- **Remove account** — available after all jobs using that account are removed.

### Google cloud locations

TuxDrive lists these separately:

- **My Drive**
- **Shared with me**
- every available **Shared Drive**

Changing the cloud location refreshes the visual folder tree. This prevents a remote preconfigured for one Shared Drive from hiding My Drive or other shared locations.

## 3. Direct encrypted peer sharing

Select the network icon in the title bar or open **Settings → Peer-to-peer sharing**. This mode synchronizes a folder directly between two computers running TuxDrive. The sharing computer runs an authenticated SFTP endpoint backed by its selected local folder; the connecting computer uses an ordinary TuxDrive two-way synchronization job. File data travels only between the two endpoints and is not stored by TuxDrive, GitHub, or a cloud provider.

![Direct peer sharing setup](assets/05-peer-sharing.svg)

### Exchange identities

Each installation creates a private Ed25519 identity under its private TuxDrive configuration directory. Select **This computer's public identity key → Copy public key** on both computers and exchange only the public lines through a trusted channel. Never send either file without the `.pub` suffix and never paste a private key into chat or email.

### On the computer sharing the folder

1. Open **Share a folder** and select the local folder.
2. Enter the current LAN/public IP address or DNS name that the other computer will use.
3. Choose an unprivileged TCP port, such as `22022`.
4. Paste the connecting computer's public identity key into **Allowed peer public key**.
5. Select **Save and start**, then **Copy invitation**.
6. Send the invitation to the other user through a trusted channel.

The IP/DNS address, port, local folder, and allowed public key remain editable. Saving restarts the endpoint with the new settings. Stopping or deleting a share never deletes files.

### On the computer connecting to the folder

1. Open **Connect to a peer**, paste the invitation, and select **Load invitation**.
2. Review the displayed IP/DNS address, port, and host public key with the sharing user.
3. Select a local folder and choose **Save and connect**.
4. TuxDrive first creates a temporary connection, pins and verifies the host key, and lists the peer folder. Only after that succeeds does it save the connection and start two-way synchronization.

The saved peer entry lets you continuously edit a changing IP/DNS address or port. Changes are verified before replacing the working endpoint. The same move, deletion, conflict, callback, exception, and logging rules used by cloud two-way synchronization apply.

### Network and security limitations

- The sharing computer must remain running and TuxDrive must remain active.
- For internet access behind NAT, forward the selected TCP port to the sharing computer. Carrier-grade NAT may require a VPN with peer-reachable addresses instead.
- Permit only the selected port in the host firewall. Restrict it to the other peer's source IP where practical.
- The connecting public key authenticates the guest; the invitation's pinned host public key authenticates the server. If either key changes unexpectedly, stop and verify with the other user instead of bypassing validation.
- This is direct encrypted transport, not anonymous communication. Endpoint IP addresses are visible to each peer and to intervening network operators.
- Keep backups of important collaborative data: two-way synchronization intentionally propagates allowed changes and deletions.

## 4. Add synchronized folders

Select **Add folder**. Choose the account, drive/location, and one or more cloud folders in the tree.

![Selective synchronization dialog](assets/03-sync-setup.svg)

### Folder tree

- Expand arrows to load child folders on demand.
- Select **Entire cloud drive** for the full selected location.
- Select multiple folders to create one job and local folder per selection.
- The local folder chooser determines where downloaded data is stored.

### Synchronization modes

| Mode | Behaviour |
|---|---|
| **Two-way sync** | Changes, moves, and allowed deletions propagate in both directions. |
| **Download mirror** | Cloud is authoritative; local content mirrors it. |
| **Upload mirror** | Local content is authoritative; cloud content mirrors it. |
| **Streaming drive (files on demand)** | The cloud tree is mounted through FUSE; contents download only when opened. |

### Job options

- **Sync interval** — periodic complete reconciliation. It remains active as a safety net.
- **Real-time callbacks** — watches local saves (about two seconds) and polls cloud changes (about 30 seconds), transferring only changed paths.
- **Conflict handling** — keep both, newer wins, local wins, or cloud wins.
- **Maximum deletions** — safety ceiling for one synchronization run.
- **Bandwidth limit** — rclone notation such as `10M`.
- **Google security warning** — unsafe opt-in for files Google marks as malware/spam. Leave disabled unless the file is trusted.
- **Synchronization exceptions** — clickable rules; add a pattern or remove it with the minus button.

## 5. Operate a synchronization job

Each job offers:

- **Sync now** — start a complete reconciliation immediately.
- **Stop** — cancel the active transfer.
- **Open folder** — open the local folder in Files.
- **Share link** — create a provider link and copy it to the clipboard.
- **Edit** — change the mode, paths, selection, interval, conflict handling, and rules.
- **View log** — open the directory containing transfer logs.
- **Trash button** — remove the job configuration without deleting local or cloud files.
- **Switch** — enable or pause automatic operation.

Status icons and labels change for idle/connected, synchronizing, paused, and error states. The account icon summarizes all jobs belonging to that account.

## 6. Incremental synchronization

When **Sync saved file changes immediately** is enabled:

1. TuxDrive debounces editor save sequences.
2. It compares local and cloud snapshots.
3. Only created, changed, moved, or deleted paths are transferred.
4. Echo events created by TuxDrive's own transfer are absorbed to avoid loops.
5. If the same path changed on both sides, TuxDrive runs the normal reconciliation path.

LibreOffice/Microsoft Office lock files, editor swap files, browser partial downloads, and `.part` files are ignored automatically. A temporary file that disappears during transfer is treated as a harmless skipped event.

## 7. Streaming files on demand

A streaming drive exposes real file names, folders, sizes, and modification times without downloading file bodies. Opening a file reads it in chunks and places accessed content in a bounded cache (10 GB by default). Writes are uploaded after the write-back delay.

![Streaming and hybrid folder layout](assets/04-streaming.svg)

### Standalone streaming drive

Choose an empty mount folder such as:

```text
~/TuxDriveStreaming/GoogleDrive
```

Select **Start streaming**. TuxDrive reports connected only after Linux confirms the FUSE mount. **Open drive** opens the mounted tree; **Disconnect** unmounts it.

### Hybrid downloaded + streamed layout

A streaming folder may be an empty child of a normal synchronized tree:

```text
~/Tuxdrive/GoogleDrive/
├── Finance/       downloaded/two-way
├── Projects/      downloaded/two-way
└── Online/        streaming/files on demand
```

TuxDrive automatically excludes `/Online` and `/Online/**` from the parent job's complete sync and incremental watcher. This prevents recursive transfer of mounted cloud files.

Safety rules:

- the streaming mount folder must be empty before connection;
- a streaming folder may be a **child** of a normal job;
- a streaming folder cannot be the **parent** of another sync job;
- two normal jobs and two streaming jobs cannot overlap.

If the mount exits unexpectedly, TuxDrive updates the status and retries up to three times in five minutes.

## 8. Exceptions and blocked files

![Exceptions and interactive recovery](assets/05-exceptions-recovery.svg)

Exception rules use rclone filter syntax. Common examples:

| Rule | Result |
|---|---|
| `/Archive/private.zip` | Excludes one exact path. |
| `*.tmp` | Excludes temporary files at any level. |
| `/Cache/**` | Excludes a directory subtree. |
| `*.iso` | Excludes all ISO images. |

When Google blocks a file as suspected malware or spam, TuxDrive shows an interactive decision:

- **Exclude file and retry** — recommended; adds an exact clickable exception rule.
- **Allow unsafe download and retry** — explicitly accepts the provider warning for that job.
- **Cancel** — leaves the job stopped for manual review.

To remove an exception, choose **Edit**, find **Synchronization exceptions**, and click the minus button beside the rule.

## 9. Tray and settings

![Tray controls, settings, and logs](assets/06-tray-logs.svg)

The tray menu contains:

- **Open TuxDrive**
- **Synchronize all now**
- **Pause all synchronization**
- **Open diagnostic logs**
- **Quit**

Settings control:

- automatic start after sign-in;
- desktop notifications;
- starting minimized.

Closing the main window hides it; synchronization continues in the tray. Use **Quit** to stop the application and unmount streaming drives.

## 10. Logs and diagnostics

| Location | Purpose |
|---|---|
| `~/.local/state/tuxdrive/startup.log` | Launcher and missing-runtime failures. |
| `~/.local/state/tuxdrive/tuxdrive.log` | Application lifecycle and job state. |
| `~/.local/state/tuxdrive/crash.log` | Uncaught Python/thread and native crash details. |
| `~/.cache/tuxdrive/logs/` | Individual synchronization and mount logs. |

Print diagnostic paths with:

```bash
tuxdrive --diagnostics
```

The expandable **Live activity log** shows recent application and transfer messages directly in the UI.

## 11. Troubleshooting

### Streaming folder is empty

1. Confirm the job button says **Open drive**, not **Start streaming**.
2. The mount folder must be empty before connection.
3. If nested, it must be a child—not the parent—of a normal sync job.
4. Open **View log** and look for FUSE, mount, authentication, or unsupported-flag errors.
5. Disconnect and select **Start streaming** again.

Version 0.7.0 writes a streaming preflight block containing the TuxDrive version, remote, mount point, rclone path, `/dev/fuse` availability, and `fusermount3` location. It automatically detaches an orphaned FUSE mount left by a crash and waits up to 45 seconds for large cloud trees. The app displays the most relevant mount failure directly while the full command activity remains in the job log.

### Proton Drive says username and password are required

The account was created without the Proton backend credentials. Open its menu, choose **Reconnect / refresh credentials**, enter the required Proton email and password (plus 2FA/OTP information when applicable), and wait for **Verifying cloud access** to complete. TuxDrive retains the existing sync jobs and validates the repaired remote before returning it to the connected state.

### Job reports recovery sync required

TuxDrive pauses automatic operation after a critical bisync abort to avoid repeated destructive resyncs. Review the log, resolve the cause, enable the job, and select **Sync now**.

### Google shows only part of the account

Edit/add the job and select the correct location: My Drive, Shared with me, or the intended Shared Drive. Then browse that location's tree.

### Google shared client warning

For continued organizational use, register a Google desktop OAuth client and reconnect the account with its client ID/secret. Do not commit credentials or OAuth tokens.

### Application does not start

Run:

```bash
tuxdrive --diagnostics
cat ~/.local/state/tuxdrive/startup.log
cat ~/.local/state/tuxdrive/crash.log
```

Reinstall the current package with `sudo apt install ./tuxdrive_0.7.0_all.deb`.

## 12. Data safety

- Back up important data before introducing any bidirectional synchronization tool.
- Review conflict and maximum-deletion settings before the first run.
- Keep unsafe Google flagged-file access disabled unless the content is trusted.
- Do not point multiple normal jobs at overlapping local folders.
- Removing a TuxDrive job does not delete its local or cloud files.
