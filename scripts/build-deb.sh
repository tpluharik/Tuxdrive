#!/bin/sh
set -eu

PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PACKAGE_ROOT="$PROJECT_ROOT/build/tuxdrive_0.2.4_all"
OUTPUT="$PROJECT_ROOT/dist/tuxdrive_0.2.4_all.deb"

rm -rf -- "$PACKAGE_ROOT"
mkdir -p \
  "$PACKAGE_ROOT/DEBIAN" \
  "$PACKAGE_ROOT/usr/bin" \
  "$PACKAGE_ROOT/usr/lib/tuxdrive" \
  "$PACKAGE_ROOT/usr/share/applications" \
  "$PACKAGE_ROOT/usr/share/doc/tuxdrive" \
  "$PACKAGE_ROOT/usr/share/icons/hicolor/scalable/apps" \
  "$PACKAGE_ROOT/usr/lib/systemd/user" \
  "$PROJECT_ROOT/dist"

cp "$PROJECT_ROOT/packaging/DEBIAN/control" "$PACKAGE_ROOT/DEBIAN/control"
cp "$PROJECT_ROOT/packaging/DEBIAN/postinst" "$PACKAGE_ROOT/DEBIAN/postinst"
cp "$PROJECT_ROOT/packaging/tuxdrive-launcher" "$PACKAGE_ROOT/usr/bin/tuxdrive"
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
cp "$PROJECT_ROOT/packaging/tuxdrive.service" \
  "$PACKAGE_ROOT/usr/lib/systemd/user/tuxdrive.service"
cp "$PROJECT_ROOT/README.md" "$PACKAGE_ROOT/usr/share/doc/tuxdrive/README.md"
cp "$PROJECT_ROOT/LICENSE" "$PACKAGE_ROOT/usr/share/doc/tuxdrive/copyright"
chmod 0755 "$PACKAGE_ROOT/usr/bin/tuxdrive"
chmod 0755 "$PACKAGE_ROOT/DEBIAN/postinst"
chmod 0644 "$PACKAGE_ROOT/DEBIAN/control"

# Verify the exact installed layout used by /usr/bin/tuxdrive. This catches
# PYTHONPATH/package-placement regressions before a .deb can be published.
PYTHONPATH="$PACKAGE_ROOT/usr/lib" /usr/bin/python3 -c \
  'import importlib.util, tuxdrive; assert tuxdrive.__version__ == "0.2.4"; assert importlib.util.find_spec("tuxdrive.app")'

dpkg-deb --root-owner-group --build "$PACKAGE_ROOT" "$OUTPUT"
printf '%s\n' "$OUTPUT"
