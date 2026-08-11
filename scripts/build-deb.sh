#!/bin/sh
set -eu

PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PACKAGE_ROOT="$PROJECT_ROOT/build/tuxdrive_0.20.6_all"
OUTPUT="$PROJECT_ROOT/dist/tuxdrive_0.20.6_all.deb"

rm -rf -- "$PACKAGE_ROOT"
mkdir -p \
  "$PACKAGE_ROOT/DEBIAN" \
  "$PACKAGE_ROOT/usr/bin" \
  "$PACKAGE_ROOT/usr/lib/tuxdrive" \
  "$PACKAGE_ROOT/usr/share/applications" \
  "$PACKAGE_ROOT/usr/share/doc/tuxdrive" \
  "$PACKAGE_ROOT/usr/share/doc/tuxdrive/assets" \
  "$PACKAGE_ROOT/usr/share/nautilus-python/extensions" \
  "$PACKAGE_ROOT/usr/share/icons/hicolor/scalable/apps" \
  "$PACKAGE_ROOT/usr/share/icons/hicolor/scalable/emblems" \
  "$PACKAGE_ROOT/usr/lib/systemd/user" \
  "$PROJECT_ROOT/dist"

cp "$PROJECT_ROOT/packaging/DEBIAN/control" "$PACKAGE_ROOT/DEBIAN/control"
cp "$PROJECT_ROOT/packaging/DEBIAN/postinst" "$PACKAGE_ROOT/DEBIAN/postinst"
cp "$PROJECT_ROOT/packaging/tuxdrive-launcher" "$PACKAGE_ROOT/usr/bin/tuxdrive"
ln -s tuxdrive "$PACKAGE_ROOT/usr/bin/tuxdrive-doctor"
cp "$PROJECT_ROOT/packaging/tuxdrive-rclone-password" "$PACKAGE_ROOT/usr/lib/tuxdrive/rclone-password"
cp "$PROJECT_ROOT/packaging/tuxdrive-update-helper" "$PACKAGE_ROOT/usr/lib/tuxdrive/update-helper"
cp -R "$PROJECT_ROOT/src/tuxdrive/." "$PACKAGE_ROOT/usr/lib/tuxdrive/"
find "$PACKAGE_ROOT/usr/lib/tuxdrive" -type d -name __pycache__ -prune -exec rm -rf -- {} +
cp "$PROJECT_ROOT/packaging/io.github.tuxdrive.TuxDrive.desktop" \
  "$PACKAGE_ROOT/usr/share/applications/io.github.tuxdrive.TuxDrive.desktop"
cp "$PROJECT_ROOT/packaging/tuxdrive.svg" \
  "$PACKAGE_ROOT/usr/share/icons/hicolor/scalable/apps/tuxdrive.svg"
cp "$PROJECT_ROOT/packaging/tuxdrive-sync.svg" \
  "$PACKAGE_ROOT/usr/share/icons/hicolor/scalable/apps/tuxdrive-sync.svg"
cp "$PROJECT_ROOT/packaging/tuxdrive-error.svg" \
  "$PACKAGE_ROOT/usr/share/icons/hicolor/scalable/apps/tuxdrive-error.svg"
for STATE in synced syncing streaming paused pending error; do
  cp "$PROJECT_ROOT/packaging/emblem-tuxdrive-${STATE}.svg" \
    "$PACKAGE_ROOT/usr/share/icons/hicolor/scalable/emblems/emblem-tuxdrive-${STATE}.svg"
done
cp "$PROJECT_ROOT/packaging/tuxdrive-google-drive.svg" \
  "$PACKAGE_ROOT/usr/share/icons/hicolor/scalable/apps/tuxdrive-google-drive.svg"
cp "$PROJECT_ROOT/packaging/tuxdrive-onedrive.svg" \
  "$PACKAGE_ROOT/usr/share/icons/hicolor/scalable/apps/tuxdrive-onedrive.svg"
for PROVIDER in dropbox box pcloud mega proton-drive nextcloud github; do
  cp "$PROJECT_ROOT/packaging/tuxdrive-${PROVIDER}.svg" \
    "$PACKAGE_ROOT/usr/share/icons/hicolor/scalable/apps/tuxdrive-${PROVIDER}.svg"
done
for SIZE in 16 24 32 48 64 128 256; do
  mkdir -p "$PACKAGE_ROOT/usr/share/icons/hicolor/${SIZE}x${SIZE}/apps"
  cp "$PROJECT_ROOT/packaging/icons/hicolor/${SIZE}x${SIZE}/apps/tuxdrive.png" \
    "$PACKAGE_ROOT/usr/share/icons/hicolor/${SIZE}x${SIZE}/apps/tuxdrive.png"
done
cp "$PROJECT_ROOT/packaging/tuxdrive.service" \
  "$PACKAGE_ROOT/usr/lib/systemd/user/tuxdrive.service"
cp "$PROJECT_ROOT/packaging/nautilus-extension-tuxdrive.py" \
  "$PACKAGE_ROOT/usr/share/nautilus-python/extensions/tuxdrive.py"
cp "$PROJECT_ROOT/README.md" "$PACKAGE_ROOT/usr/share/doc/tuxdrive/README.md"
cp "$PROJECT_ROOT/docs/USER_GUIDE.md" "$PACKAGE_ROOT/usr/share/doc/tuxdrive/USER_GUIDE.md"
cp "$PROJECT_ROOT/docs/TESTING.md" "$PACKAGE_ROOT/usr/share/doc/tuxdrive/TESTING.md"
cp "$PROJECT_ROOT/docs/ROADMAP.md" "$PACKAGE_ROOT/usr/share/doc/tuxdrive/ROADMAP.md"
cp "$PROJECT_ROOT/CHANGELOG.md" "$PACKAGE_ROOT/usr/share/doc/tuxdrive/CHANGELOG.md"
cp -R "$PROJECT_ROOT/docs/assets/." "$PACKAGE_ROOT/usr/share/doc/tuxdrive/assets/"
cp "$PROJECT_ROOT/branding/tuxdrive-logo.png" "$PACKAGE_ROOT/usr/share/doc/tuxdrive/tuxdrive-logo.png"
cp "$PROJECT_ROOT/LICENSE" "$PACKAGE_ROOT/usr/share/doc/tuxdrive/copyright"
chmod 0755 "$PACKAGE_ROOT/usr/bin/tuxdrive"
chmod 0755 "$PACKAGE_ROOT/usr/lib/tuxdrive/rclone-password"
chmod 0755 "$PACKAGE_ROOT/usr/lib/tuxdrive/update-helper"
chmod 0755 "$PACKAGE_ROOT/DEBIAN/postinst"
chmod 0644 "$PACKAGE_ROOT/DEBIAN/control"
chmod 0644 "$PACKAGE_ROOT/usr/share/nautilus-python/extensions/tuxdrive.py"

# Verify the exact installed layout used by /usr/bin/tuxdrive. This catches
# PYTHONPATH/package-placement regressions before a .deb can be published.
PYTHONPATH="$PACKAGE_ROOT/usr/lib" /usr/bin/python3 -c \
  'import importlib.util, tuxdrive; assert tuxdrive.__version__ == "0.20.6"; assert importlib.util.find_spec("tuxdrive.app"); assert importlib.util.find_spec("tuxdrive.i18n"); assert importlib.util.find_spec("tuxdrive.help_content"); assert importlib.util.find_spec("tuxdrive.collaboration"); assert importlib.util.find_spec("tuxdrive.platform_support"); assert importlib.util.find_spec("tuxdrive.updater"); assert importlib.util.find_spec("tuxdrive.update_helper"); assert importlib.util.find_spec("tuxdrive.peer"); assert importlib.util.find_spec("tuxdrive.tor"); assert importlib.util.find_spec("tuxdrive.recovery"); assert importlib.util.find_spec("tuxdrive.delta"); assert importlib.util.find_spec("tuxdrive.policies"); assert importlib.util.find_spec("tuxdrive.audit"); assert importlib.util.find_spec("tuxdrive.capabilities"); assert importlib.util.find_spec("tuxdrive.migration"); assert importlib.util.find_spec("tuxdrive.security"); assert importlib.util.find_spec("tuxdrive.github_sync"); assert importlib.util.find_spec("tuxdrive.nautilus_support")'

dpkg-deb --root-owner-group --build "$PACKAGE_ROOT" "$OUTPUT"
printf '%s\n' "$OUTPUT"
