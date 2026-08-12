param([switch]$PackageOnly)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot
$Version = (Select-String -Path "src\tuxindrive\__init__.py" -Pattern '__version__ = "([^"]+)"').Matches.Groups[1].Value
if (-not $PackageOnly) {
    $Bash = "C:\msys64\usr\bin\bash.exe"
    if (-not (Test-Path $Bash)) { throw "MSYS2 is required at C:\msys64" }
    $Drive = $ProjectRoot.Substring(0, 1).ToLowerInvariant()
    $MsysProjectRoot = "/$Drive" + $ProjectRoot.Substring(2).Replace('\', '/')
    & $Bash -lc "export PATH=/ucrt64/bin:/usr/bin; sh '$MsysProjectRoot/scripts/build-windows-msys2.sh'"
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
}
if (-not (Test-Path "build\windows\TuxInDrive\TuxInDrive.exe")) { throw "Frozen Windows application was not created" }
$Iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $Iscc)) { throw "Inno Setup 6 is required" }
& $Iscc "/DAppVersion=$Version" "packaging\windows\TuxInDrive.iss"
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
Compress-Archive -Path "build\windows\TuxInDrive\*" -DestinationPath "dist\TuxInDrive-$Version-windows-x64-portable.zip" -Force
if (-not (Test-Path "dist\TuxInDrive-$Version-windows-x64-setup.exe")) { throw "Windows installer was not created" }
if (-not (Test-Path "dist\TuxInDrive-$Version-windows-x64-portable.zip")) { throw "Windows portable archive was not created" }
Write-Host "Windows packages written to dist\"
