#define AppName "VibeStick Bridge"
#define AppVersion GetEnv("VIBE_STICK_PACKAGE_VERSION")
#define BuildRoot GetEnv("VIBE_STICK_WINDOWS_BUILD_ROOT")

[Setup]
AppId={{8E5911E3-ABF4-49C4-9CE1-A94274DBE11A}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=VibeStick
DefaultDirName={localappdata}\VibeStick\bin
DefaultGroupName=VibeStick
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#BuildRoot}\installer
OutputBaseFilename=VibeStick-Bridge-Windows-v{#AppVersion}-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName=VibeStick Bridge

[Files]
Source: "{#BuildRoot}\app\VibeStickBridge.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#BuildRoot}\app\VibeStickHUD.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#BuildRoot}\app\install-windows.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#BuildRoot}\app\uninstall-windows.ps1"; DestDir: "{app}"; Flags: ignoreversion

[Run]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\install-windows.ps1"" -PackageRoot ""{app}"""; Flags: runhidden waituntilterminated

[UninstallRun]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\uninstall-windows.ps1"""; Flags: runhidden waituntilterminated; RunOnceId: "VibeStickCleanup"
