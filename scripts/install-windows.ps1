param(
    [string]$PackageRoot = (Split-Path -Parent $MyInvocation.MyCommand.Path)
)

$ErrorActionPreference = "Stop"
$ConfigDir = Join-Path $env:LOCALAPPDATA "VibeStick"
$BinDir = Join-Path $ConfigDir "bin"
$BridgeSource = Join-Path $PackageRoot "VibeStickBridge.exe"
$HudSource = Join-Path $PackageRoot "VibeStickHUD.exe"
$BridgeTarget = Join-Path $BinDir "VibeStickBridge.exe"
$HudTarget = Join-Path $BinDir "VibeStickHUD.exe"
$EnvPath = Join-Path $ConfigDir ".env"
$StartupDir = [Environment]::GetFolderPath("Startup")
$StartupCmd = Join-Path $StartupDir "VibeStick.cmd"

if (-not (Test-Path $BridgeSource) -or -not (Test-Path $HudSource)) {
    throw "Windows package is incomplete. VibeStickBridge.exe and VibeStickHUD.exe are required."
}

New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
$CurrentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
& icacls.exe $ConfigDir /inheritance:r /grant:r "${CurrentIdentity}:(OI)(CI)F" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Could not restrict the VibeStick configuration directory to the current Windows user."
}
if ([IO.Path]::GetFullPath($BridgeSource) -ne [IO.Path]::GetFullPath($BridgeTarget)) {
    Copy-Item -Force $BridgeSource $BridgeTarget
}
if ([IO.Path]::GetFullPath($HudSource) -ne [IO.Path]::GetFullPath($HudTarget)) {
    Copy-Item -Force $HudSource $HudTarget
}

if (-not (Test-Path $EnvPath)) {
    $bytes = New-Object byte[] 32
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    $generator.GetBytes($bytes)
    $generator.Dispose()
    $token = -join ($bytes | ForEach-Object { $_.ToString("x2") })
    $envContent = @"
VIBE_STICK_BRIDGE_TOKEN=$token
VIBE_STICK_ASR_PROVIDER=openai-compatible
VIBE_STICK_ASR_BASE_URL=https://api.siliconflow.cn/v1
VIBE_STICK_ASR_API_KEY=
VIBE_STICK_ASR_MODEL=FunAudioLLM/SenseVoiceSmall
VIBE_STICK_ASR_LANGUAGE=zh
VIBE_STICK_RETAIN_RECORDINGS=0
VIBE_STICK_RECORDING_USE_MAC_MIC=0
VIBE_STICK_AUTO_ENTER=0
"@
    [IO.File]::WriteAllText($EnvPath, $envContent, (New-Object Text.UTF8Encoding($false)))
}

@"
@echo off
start "VibeStick Bridge" /min "$BridgeTarget" --host 0.0.0.0 --port 8765
start "VibeStick HUD" /min "$HudTarget"
"@ | Set-Content -Encoding ASCII $StartupCmd

Start-Process -FilePath $BridgeTarget -ArgumentList "--host", "0.0.0.0", "--port", "8765" -WindowStyle Hidden
Start-Process -FilePath $HudTarget -WindowStyle Hidden
Start-Sleep -Milliseconds 700
Start-Process "http://127.0.0.1:8765/setup/voice"

Write-Host "VibeStick Bridge installed."
Write-Host "Configuration: $ConfigDir"
Write-Host "Voice settings: http://127.0.0.1:8765/setup/voice"
Write-Host "If Windows Firewall asks, allow access only on private networks."
