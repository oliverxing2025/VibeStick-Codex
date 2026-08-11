$ErrorActionPreference = "Stop"
$ConfigDir = Join-Path $env:LOCALAPPDATA "VibeStick"
$StartupCmd = Join-Path ([Environment]::GetFolderPath("Startup")) "VibeStick.cmd"

Get-Process VibeStickBridge, VibeStickHUD -ErrorAction SilentlyContinue | Stop-Process -Force
Remove-Item -Force -ErrorAction SilentlyContinue $StartupCmd

Write-Host "VibeStick Windows preview autostart and running processes were removed."
Write-Host "Private configuration was preserved at: $ConfigDir"
