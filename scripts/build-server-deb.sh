#!/bin/sh
set -eu

PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
VERSION=$(sed -n 's/^__version__ = "\([^"]*\)"/\1/p' "$PROJECT_ROOT/src/tuxindrive/__init__.py")
test -n "$VERSION"
PACKAGE_ROOT="$PROJECT_ROOT/build/tuxindrive-server_${VERSION}_all"
OUTPUT="$PROJECT_ROOT/dist/tuxindrive-server_${VERSION}_all.deb"

rm -rf -- "$PACKAGE_ROOT"
mkdir -p "$PACKAGE_ROOT/DEBIAN" "$PACKAGE_ROOT/usr/bin" \
  "$PACKAGE_ROOT/usr/lib/tuxindrive-server/tuxindrive" "$PACKAGE_ROOT/usr/lib/systemd/system" \
  "$PACKAGE_ROOT/usr/share/doc/tuxindrive-server" "$PROJECT_ROOT/dist"
cp "$PROJECT_ROOT/packaging/server/DEBIAN/control" "$PACKAGE_ROOT/DEBIAN/control"
cp "$PROJECT_ROOT/packaging/server/DEBIAN/postinst" "$PACKAGE_ROOT/DEBIAN/postinst"
cp "$PROJECT_ROOT/packaging/server/tuxindrive-server" "$PACKAGE_ROOT/usr/bin/tuxindrive-server"
cp "$PROJECT_ROOT/packaging/server/tuxindrive-server.service" "$PACKAGE_ROOT/usr/lib/systemd/system/tuxindrive-server.service"
cp -R "$PROJECT_ROOT/src/tuxindrive/." "$PACKAGE_ROOT/usr/lib/tuxindrive-server/tuxindrive/"
find "$PACKAGE_ROOT/usr/lib/tuxindrive-server" -type d -name __pycache__ -prune -exec rm -rf -- {} +
cp "$PROJECT_ROOT/docs/SERVER.md" "$PACKAGE_ROOT/usr/share/doc/tuxindrive-server/SERVER.md"
cp "$PROJECT_ROOT/docs/SECURITY_HARDENING.md" "$PACKAGE_ROOT/usr/share/doc/tuxindrive-server/SECURITY_HARDENING.md"
cp "$PROJECT_ROOT/LICENSE" "$PACKAGE_ROOT/usr/share/doc/tuxindrive-server/copyright"
sed -i "s/^Version: .*/Version: $VERSION/" "$PACKAGE_ROOT/DEBIAN/control"
find "$PACKAGE_ROOT" -type d -exec chmod 0755 {} +
find "$PACKAGE_ROOT" -type f -exec chmod 0644 {} +
chmod 0755 "$PACKAGE_ROOT/DEBIAN/postinst" "$PACKAGE_ROOT/usr/bin/tuxindrive-server"
PYTHONPATH="$PACKAGE_ROOT/usr/lib/tuxindrive-server" /usr/bin/python3 -c \
  'import importlib.util,tuxindrive; assert importlib.util.find_spec("tuxindrive.server"); assert importlib.util.find_spec("tuxindrive.server_store"); assert importlib.util.find_spec("tuxindrive.server_client")'
find "$PACKAGE_ROOT/usr/lib/tuxindrive-server" -type d -name __pycache__ -prune -exec rm -rf -- {} +
dpkg-deb --root-owner-group --build "$PACKAGE_ROOT" "$OUTPUT"
printf '%s\n' "$OUTPUT"
