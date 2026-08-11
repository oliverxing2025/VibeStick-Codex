$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Version = (Select-String -Path (Join-Path $Root "bridge\src\vibe_stick\__init__.py") `
    -Pattern '__version__\s*=\s*"([^"]+)"').Matches.Groups[1].Value
$Output = Join-Path $Root "dist\windows-build"
$AppOutput = Join-Path $Output "app"
$Work = Join-Path $env:TEMP "vibestick-pyinstaller"

python -m pip install --disable-pip-version-check pyinstaller
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $Output, $Work
New-Item -ItemType Directory -Force -Path $AppOutput, $Work | Out-Null

python -m PyInstaller --noconfirm --clean --onefile --name VibeStickBridge `
    --paths (Join-Path $Root "bridge\src") `
    --distpath $AppOutput --workpath (Join-Path $Work "bridge") `
    --specpath (Join-Path $Work "spec") `
    (Join-Path $Root "bridge\src\vibe_stick\__main__.py")

python -m PyInstaller --noconfirm --clean --onefile --windowed --name VibeStickHUD `
    --distpath $AppOutput --workpath (Join-Path $Work "hud") `
    --specpath (Join-Path $Work "spec") `
    (Join-Path $Root "app\windows\VibeStickHUD.py")

Copy-Item (Join-Path $Root "scripts\install-windows.ps1") $AppOutput
Copy-Item (Join-Path $Root "scripts\uninstall-windows.ps1") $AppOutput

$Iscc = Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"
if (-not (Test-Path $Iscc)) {
    throw "Inno Setup 6 is required to build the Windows installer."
}
$env:VIBE_STICK_PACKAGE_VERSION = $Version
$env:VIBE_STICK_WINDOWS_BUILD_ROOT = $Output
& $Iscc (Join-Path $Root "packaging\windows\VibeStickBridge.iss")
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup failed with exit code $LASTEXITCODE."
}

$Installer = Join-Path $Output "installer\VibeStick-Bridge-Windows-v$Version-Setup.exe"
$FinalInstaller = Join-Path $Root "dist\VibeStick-Bridge-Windows-v$Version-Setup.exe"
Copy-Item -Force $Installer $FinalInstaller
$Hash = (Get-FileHash -Algorithm SHA256 $FinalInstaller).Hash.ToLowerInvariant()
Set-Content -Encoding ASCII -NoNewline `
    -Path "$FinalInstaller.sha256" `
    -Value "$Hash  $(Split-Path -Leaf $FinalInstaller)`n"
Write-Host $FinalInstaller
Write-Host "$FinalInstaller.sha256"
