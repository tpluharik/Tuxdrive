#!/bin/sh
set -eu

if [ "$(uname -s)" != "Darwin" ]; then
  echo "The macOS .pkg must be built on macOS (GitHub Actions can build it)." >&2
  exit 2
fi

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
version=0.16.0
arch=$(uname -m)
work="$root/build/macos-$arch"
payload="$work/payload"
app="$payload/Applications/TuxDrive.app"
resources="$app/Contents/Resources"
output="$root/dist/tuxdrive_${version}_experimental_macos_${arch}.pkg"

rm -rf -- "$work"
mkdir -p "$app/Contents/MacOS" "$resources/app" "$resources/python" "$root/dist"
cp "$root/packaging/macos/Info.plist" "$app/Contents/Info.plist"
cp "$root/packaging/macos/tuxdrive-launcher" "$app/Contents/MacOS/tuxdrive"
cp "$root/packaging/macos/rclone_password.py" "$resources/rclone-password"
cp -R "$root/src/tuxdrive" "$resources/app/tuxdrive"
find "$resources/app" -type d -name __pycache__ -prune -exec rm -rf -- {} +
chmod 0755 "$app/Contents/MacOS/tuxdrive" "$resources/rclone-password"

python3 -m pip install --only-binary=:all: --target "$resources/python" "cryptography>=50,<51"

iconset="$work/TuxDrive.iconset"
mkdir -p "$iconset"
for size in 16 32 128 256 512; do
  sips -z "$size" "$size" "$root/branding/tuxdrive-logo.png" --out "$iconset/icon_${size}x${size}.png" >/dev/null
  double=$((size * 2))
  sips -z "$double" "$double" "$root/branding/tuxdrive-logo.png" --out "$iconset/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$iconset" -o "$resources/TuxDrive.icns"

# Ad-hoc signing protects bundle integrity for test installations. Production
# distribution still requires a Developer ID signature and Apple notarization.
codesign --force --deep --sign - "$app"
pkgbuild --root "$payload" --identifier io.github.tuxdrive.TuxDrive.experimental \
  --version "$version" --install-location / "$output"
echo "$output"
