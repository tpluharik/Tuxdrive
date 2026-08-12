$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot
$Version = (Select-String -Path "src\tuxindrive\__init__.py" -Pattern '__version__ = "([^"]+)"').Matches.Groups[1].Value
$Bash = "C:\msys64\usr\bin\bash.exe"
if (-not (Test-Path $Bash)) { throw "MSYS2 is required at C:\msys64" }
$MsysProjectRoot = (& $Bash -lc "cygpath -u '$ProjectRoot'").Trim()
& $Bash -lc @"
set -euo pipefail
export PATH=/ucrt64/bin:/usr/bin
cd '$MsysProjectRoot'
rm -rf build/windows
mkdir -p build/windows dist
python -m PyInstaller --noconfirm --clean --windowed --onedir --name TuxInDrive \
  --distpath build/windows --workpath build/pyinstaller-windows --specpath build \
  --collect-all gi --hidden-import=keyring.backends.Windows \
  --add-data '$MsysProjectRoot/branding/tuxindrive-logo.png:branding' packaging/desktop-entry.py
python -m PyInstaller --noconfirm --clean --console --onefile \
  --name tuxindrive-rclone-password --distpath build/windows/TuxInDrive \
  --workpath build/pyinstaller-password-windows --specpath build \
  --hidden-import=keyring.backends.Windows src/tuxindrive/password_helper.py
cp README.md LICENSE build/windows/TuxInDrive/
"@
$Iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $Iscc)) { throw "Inno Setup 6 is required" }
& $Iscc "/DAppVersion=$Version" "packaging\windows\TuxInDrive.iss"
Compress-Archive -Path "build\windows\TuxInDrive\*" -DestinationPath "dist\TuxInDrive-$Version-windows-x64-portable.zip" -Force
if (-not (Test-Path "dist\TuxInDrive-$Version-windows-x64-setup.exe")) { throw "Windows installer was not created" }
if (-not (Test-Path "dist\TuxInDrive-$Version-windows-x64-portable.zip")) { throw "Windows portable archive was not created" }
Write-Host "Windows packages written to dist\"
