; Wraps PyInstaller's dist\analyser\ into a setup.exe.
;
; Version is passed in so pyproject.toml stays the single source of truth:
;   iscc /DAppVersion=0.3.0 packaging\windows\analyser.iss
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

#define AppName "Analyser"
#define AppExe "analyser.exe"

[Setup]
; Never change AppId — it is how Windows recognises an existing install to upgrade.
AppId={{52F698D2-940B-454B-AD50-A7032786B37C}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=goncamateus
AppPublisherURL=https://github.com/goncamateus/goncanalyser
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
UninstallDisplayIcon={app}\{#AppExe}
OutputDir=..\..\dist
OutputBaseFilename=goncanalyser-{#AppVersion}-setup
SetupIconFile=..\icon.ico
Compression=lzma2
SolidCompression=yes
; The bundle carries 64-bit binary wheels, so refuse to install where they cannot run.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; No admin rights needed: per-user install keeps this out of UAC prompts entirely.
PrivilegesRequired=lowest
WizardStyle=modern

[Files]
Source: "..\..\dist\analyser\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
