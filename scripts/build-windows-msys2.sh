#!/bin/sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_root"
rm -rf build/windows build/pyinstaller-windows build/pyinstaller-password-windows
mkdir -p build/windows dist
python -m PyInstaller --noconfirm --clean --windowed --onedir --name TuxInDrive \
  --distpath build/windows --workpath build/pyinstaller-windows --specpath build \
  --collect-all gi --hidden-import=keyring.backends.Windows \
  --add-data "$project_root/branding/tuxindrive-logo.png:branding" packaging/desktop-entry.py
python -m PyInstaller --noconfirm --clean --console --onefile \
  --name tuxindrive-rclone-password --distpath build/windows/TuxInDrive \
  --workpath build/pyinstaller-password-windows --specpath build \
  --hidden-import=keyring.backends.Windows src/tuxindrive/password_helper.py
cp README.md LICENSE build/windows/TuxInDrive/
test -s build/windows/TuxInDrive/TuxInDrive.exe
test -s build/windows/TuxInDrive/tuxindrive-rclone-password.exe
