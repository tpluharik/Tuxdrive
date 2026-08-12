# Platform support and adaptive installation

TuxInDrive 0.25.0 uses one Debian package across supported Debian-family GNOME desktops. Git is required for the GitHub backend; repository authentication remains in the user's SSH agent or system Git credential helper. The installer keeps the secure graphical core mandatory and treats desktop/file-manager, streaming, peer-network and privacy transports as optional capabilities. A missing optional integration no longer makes the package uninstallable or disables unrelated synchronization. TuxInDrive does not publish a macOS package.

## Compatibility matrix

The supported design baseline is Ubuntu 24.04/26.04 and Debian 12/13 on amd64 or arm64. Automated clean-package core installation covers Ubuntu 24.04 and Debian 12/13; Ubuntu 26.04 remains the primary GNOME desktop target and requires the release VM gate described below. Ubuntu derivatives can run the core application when they provide Python 3.10+, PyGObject/GTK 3, Python cryptography, `defusedxml`, Secret Service and XDG utilities. Only amd64 and arm64 can use TuxInDrive's verified rclone bootstrap; other architectures are reported as unsupported before a cloud job starts.

| Distribution / desktop | Core cloud sync | Streaming | File-manager status/actions | Support level and limitations |
| --- | --- | --- | --- | --- |
| Ubuntu 26.04 GNOME | Expected | Expected with FUSE 3 | Nautilus 4.1 design target | Primary target; complete GNOME/Wayland VM release test required. |
| Ubuntu 24.04 LTS GNOME | CI-installed | Expected with FUSE 3 | Nautilus 4.x | Supported; verify AppIndicator extension and unlocked GNOME Keyring in the user session. |
| Debian 13 GNOME | CI-installed | Expected with FUSE 3 | Nautilus 4.x | Supported core; integration package versions come from Debian repositories. |
| Debian 12 GNOME | CI-installed | Expected with FUSE 3 | Nautilus 4.x | Supported core; use Debian security updates/backports and complete the manual Secret Service/FUSE gate. |
| Ubuntu 22.04 GNOME | Best effort | Best effort | Older python-nautilus generation | Not a supported security baseline; older Python/cryptography and Nautilus bindings require separate validation. |
| Linux Mint with Cinnamon/Nemo | Expected core only | Expected with FUSE 3 | Not available in Nemo | TuxInDrive runs as a GTK application, but the packaged extension is Nautilus-only. A Nemo adapter is not yet shipped. |
| Pop!_OS GNOME-based releases | Expected core only | Expected with FUSE 3 | Best effort when Nautilus is used | Tray/shell behavior depends on the installed GNOME extensions; COSMIC sessions are not a GNOME integration target. |
| Zorin OS | Expected core only on a compatible Ubuntu base | Expected with FUSE 3 | Best effort | Run the system check; support follows the base Ubuntu Python, GTK and Nautilus versions rather than the Zorin version label. |
| Ubuntu flavors using Xfce, MATE, LXQt or KDE | Expected core only | Expected with FUSE 3 | No native Thunar/Caja/Dolphin integration | Cloud and peer functions can run, but Nautilus badges/actions and GNOME tray assumptions do not apply. |
| elementary OS / Pantheon Files | Expected core only | Expected with FUSE 3 | Not available | Pantheon Files is not supported by the Nautilus extension. |
| Kali Linux rolling | Best effort | Best effort | Best effort if Nautilus is installed | Rolling dependency changes are outside the release matrix; do not treat it as a stable production target. |
| MX Linux / antiX family | Best effort | Best effort | No native file-manager integration | Non-systemd or Xfce configurations may require manual autostart and lack the packaged user service. |
| Devuan | Best effort | Best effort | Best effort if Nautilus is installed | The systemd user unit is unavailable; desktop autostart and session services must be supplied separately. |
| Raspberry Pi OS 64-bit | Best effort | Hardware/kernel dependent | No native default file-manager integration | arm64 rclone is supported, but the default desktop is outside the GNOME/Nautilus matrix. 32-bit ARM is unsupported. |
| Other Debian derivatives | Unverified | Unverified | Unverified | Requires Python 3.10+, GTK 3/PyGObject, Secret Service and supported amd64/arm64 runtime; run `tuxindrive --system-check`. |

“CI-installed” means the package was built and installed with mandatory dependencies in the repository's container matrix. It does not replace a graphical VM test. “Expected” and “best effort” describe code/dependency compatibility, not a completed release certification.

## Checks performed

`postinst` writes a machine-level snapshot to `/var/lib/tuxindrive/install-capabilities.json`. Because package installation runs as root outside the graphical login, run the user-session check after installation:

```bash
tuxindrive --system-check
# machine-readable output
tuxindrive --system-check --json
```

The session check reports the distribution, CPU, desktop/session and availability of Secret Service, URL opening, FUSE, Nautilus, PolicyKit, notifications, NetworkManager policies, Tor/obfs4, NAT traversal and QR pairing. Required failures return exit status 1. Optional failures return an actionable installation hint and disable only the affected feature.

## Package model

- Required: Python 3.10+, PyGObject, GTK 3, Python cryptography, `defusedxml`, Secret Service tools, XDG utilities and CA certificates. `defusedxml` is mandatory for hostile-input-safe collaborative ODT/ODS parsing.
- Recommended: Nautilus integration, AppIndicator, FUSE streaming, peer SSH, Tor transports, NAT traversal, NetworkManager policies, QR tools, notifications and PolicyKit updates.
- Suggested: Snowflake transport.

APT normally installs recommendations. Minimal systems may use `--no-install-recommends`; TuxInDrive will then start with the available core and report which optional functions are disabled. Linux Mint/Nemo, Caja and non-Nautilus file managers can run TuxInDrive but do not currently receive badges or context actions.

## Limits

The `.deb` is adaptive, not a hermetic container: authentication needs a working user Secret Service, streaming needs kernel FUSE access, tray visibility depends on the GNOME shell indicator extension, and Nautilus integration is host-loaded code. These boundaries cannot safely be bundled or activated from a root maintainer script. Clean GNOME VM tests remain required for each distribution release.

## Release VM gate

Before marking a distribution as fully verified, install the `.deb` on a clean amd64 or arm64 image and test login autostart, Wayland and X11 startup where offered, Secret Service lock/unlock, Google/OneDrive OAuth, a two-way move/delete cycle, FUSE reconnect after logout and suspend, Nautilus badges/actions, tray visibility, notifications, PolicyKit update installation and uninstall/reinstall with preserved encrypted configuration. Record the exact distribution image, package versions and result in the release notes.
