# TuxDrive User Guide

<p align="center"><img src="../branding/tuxdrive-logo.png" width="150" alt="TuxDrive penguin head logo"></p>

This guide covers TuxDrive 0.5.1 on Ubuntu 26.04: installation, browser OAuth, cloud locations, selective synchronization, real-time callbacks, exceptions, streaming drives, tray controls, updates, logs, and recovery.

> The screenshots use sample names and paths. They do not contain real account information.

## 1. Install and start

Download the current Debian package and install it with one command:

```bash
sudo apt install ./tuxdrive_0.5.1_all.deb
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

The black-and-white penguin identifies TuxDrive itself. Google Drive and OneDrive use their provider icons while connected and in the account chooser; blue sync and red error badges show changing activity.

### Update TuxDrive

Open **Settings** and select **Check for updates**. If a newer version is listed in this repository, choose **Download and install**. TuxDrive verifies the package checksum before Ubuntu displays its system authorization prompt. When installation completes, restart TuxDrive. If the check fails, the existing installation remains unchanged and the error is shown in the app.

## 2. Connect an account with OAuth

Select `+` or **Connect account**, then choose Google Drive or Microsoft OneDrive.

![OAuth account connection](assets/02-oauth.svg)

- **Account key** is TuxDrive's local identifier. Use letters, numbers, dot, dash, or underscore.
- **Display name** is the friendly name shown in the sidebar.
- **OAuth client ID/secret** are optional for personal testing. A dedicated provider application is recommended for regular or organizational use.
- Select **Open browser and connect**. Sign in on the provider's page and approve access. TuxDrive never receives the cloud password.
- If the browser callback port is busy, cancel the old authorization window and retry. TuxDrive stops stale OAuth callback processes before opening a new session.

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

## 3. Add synchronized folders

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

## 4. Operate a synchronization job

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

## 5. Incremental synchronization

When **Sync saved file changes immediately** is enabled:

1. TuxDrive debounces editor save sequences.
2. It compares local and cloud snapshots.
3. Only created, changed, moved, or deleted paths are transferred.
4. Echo events created by TuxDrive's own transfer are absorbed to avoid loops.
5. If the same path changed on both sides, TuxDrive runs the normal reconciliation path.

LibreOffice/Microsoft Office lock files, editor swap files, browser partial downloads, and `.part` files are ignored automatically. A temporary file that disappears during transfer is treated as a harmless skipped event.

## 6. Streaming files on demand

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

## 7. Exceptions and blocked files

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

## 8. Tray and settings

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

## 9. Logs and diagnostics

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

## 10. Troubleshooting

### Streaming folder is empty

1. Confirm the job button says **Open drive**, not **Start streaming**.
2. The mount folder must be empty before connection.
3. If nested, it must be a child—not the parent—of a normal sync job.
4. Open **View log** and look for FUSE, mount, authentication, or unsupported-flag errors.
5. Disconnect and select **Start streaming** again.

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

Reinstall the current package with `sudo apt install ./tuxdrive_0.5.1_all.deb`.

## 11. Data safety

- Back up important data before introducing any bidirectional synchronization tool.
- Review conflict and maximum-deletion settings before the first run.
- Keep unsafe Google flagged-file access disabled unless the content is trusted.
- Do not point multiple normal jobs at overlapping local folders.
- Removing a TuxDrive job does not delete its local or cloud files.
