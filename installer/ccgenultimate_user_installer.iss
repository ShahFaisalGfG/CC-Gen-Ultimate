; =======================================================
; CC-Gen-Ultimate Windows Installer
; Inno Setup Script
; Version: 1.0.0
; =======================================================
; CC-Gen-Ultimate per-user installer (non-admin)
; Use this script to create a per-user installer that does not require elevated privileges

#ifndef MyAppName
  #define MyAppName "CC-Gen-Ultimate"
#endif
#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif
#ifndef MyAppPublisher
  #define MyAppPublisher "gfgRoyal"
#endif
#ifndef MyAppURL
  #define MyAppURL "https://shahfaisalgfg.github.io/shahfaisal/"
#endif
#ifndef MyGpuSuffix
  ; Set by the build scripts for GPU-specific builds (e.g. "_intel_gpu"); empty for the main build.
  #define MyGpuSuffix ""
#endif
#ifndef MyAppExeName
  #define MyAppExeName "CC-Gen-Ultimate.exe"
#endif
#define SourceDir "..\dist\CC-Gen-Ultimate"
#define IconsDir "..\ccgen\assets\icons"

[Setup]
AppId={{7BFA27A3-AF1F-45DD-9F5F-CBCF2A9CEB81}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}

; Install per-user (no admin privileges required)
PrivilegesRequired=lowest

; Install to per-user AppData (Roaming) for current user
DefaultDirName={userappdata}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=..\build\installer
OutputBaseFilename={#MyAppName}_{#MyAppVersion}{#MyGpuSuffix}_user_installer
SetupIconFile={#IconsDir}\CCGenUltimate.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
WizardSizePercent=110,120

; Architectures
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
english.EnableContextMenu=Add "Generate Subtitles with CC-Gen-Ultimate" to the right-click menu for video/audio/subtitle files
english.ContextMenu=Explorer integration:

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "contextmenu"; Description: "{cm:EnableContextMenu}"; GroupDescription: "{cm:ContextMenu}"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Shell extension DLL - no restartreplace/uninsrestartdelete here: those need
; MOVEFILE_DELAY_UNTIL_REBOOT, which Windows restricts to admin processes, and
; this is the no-admin user installer. If Explorer has the DLL locked at
; uninstall time it's simply left behind as a harmless orphan (its registry
; entries are already removed via uninsdeletekey).
Source: "{#SourceDir}\ccgen_shell.dll"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#IconsDir}\CCGenUltimate.ico"; DestDir: "{app}\icons"; Flags: ignoreversion
Source: "..\requirements.txt"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "{#IconsDir}\Square150x150Logo.scale-100.png"; DestDir: "{app}\docs\icons"; Flags: ignoreversion

[InstallDelete]
; Remove the previous version's bundled runtime before copying the new one. Files a newer
; build no longer ships (old package metadata, dropped libraries) would otherwise stay behind
; and can break imports at startup - e.g. a leftover Pillow fragment made transformers fail.
; Only bundled program files live in _internal; settings, logs, and models are kept.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{userprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\icons\CCGenUltimate.ico"
Name: "{userprograms}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"

Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\icons\CCGenUltimate.ico"; Tasks: desktopicon

[Registry]
; =============================================================================
; IExplorerCommand CLSID registration - per-user (HKCU, no admin required)
; =============================================================================
Root: HKCU; Subkey: "Software\Classes\CLSID\{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}"; ValueType: string; ValueName: ""; ValueData: "CC-Gen-Ultimate Subtitle Shell Extension"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\CLSID\{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}\InprocServer32"; ValueType: string; ValueName: ""; ValueData: "{app}\ccgen_shell.dll"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\CLSID\{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}\InprocServer32"; ValueType: string; ValueName: "ThreadingModel"; ValueData: "Apartment"; Flags: uninsdeletekey; Tasks: contextmenu

; =============================================================================
; Context menu: "Generate Subtitles with CC-Gen-Ultimate" - per-user
; Registered per supported extension under SystemFileAssociations so it never
; touches (or overrides) the user's actual default "open with" association.
; =============================================================================
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.mp4\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: ""; ValueData: "Generate Subtitles with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.mp4\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.mp4\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.mp4\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}"; Flags: uninsdeletekey; Tasks: contextmenu

Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.mkv\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: ""; ValueData: "Generate Subtitles with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.mkv\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.mkv\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.mkv\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}"; Flags: uninsdeletekey; Tasks: contextmenu

Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.avi\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: ""; ValueData: "Generate Subtitles with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.avi\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.avi\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.avi\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}"; Flags: uninsdeletekey; Tasks: contextmenu

Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.mov\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: ""; ValueData: "Generate Subtitles with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.mov\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.mov\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.mov\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}"; Flags: uninsdeletekey; Tasks: contextmenu

Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.webm\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: ""; ValueData: "Generate Subtitles with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.webm\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.webm\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.webm\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}"; Flags: uninsdeletekey; Tasks: contextmenu

Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.flv\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: ""; ValueData: "Generate Subtitles with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.flv\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.flv\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.flv\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}"; Flags: uninsdeletekey; Tasks: contextmenu

Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.wmv\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: ""; ValueData: "Generate Subtitles with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.wmv\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.wmv\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.wmv\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}"; Flags: uninsdeletekey; Tasks: contextmenu

Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.ts\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: ""; ValueData: "Generate Subtitles with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.ts\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.ts\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.ts\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}"; Flags: uninsdeletekey; Tasks: contextmenu

Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.m2ts\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: ""; ValueData: "Generate Subtitles with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.m2ts\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.m2ts\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.m2ts\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}"; Flags: uninsdeletekey; Tasks: contextmenu

Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.mp3\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: ""; ValueData: "Generate Subtitles with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.mp3\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.mp3\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.mp3\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}"; Flags: uninsdeletekey; Tasks: contextmenu

Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.wav\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: ""; ValueData: "Generate Subtitles with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.wav\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.wav\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.wav\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}"; Flags: uninsdeletekey; Tasks: contextmenu

Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.m4a\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: ""; ValueData: "Generate Subtitles with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.m4a\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.m4a\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.m4a\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}"; Flags: uninsdeletekey; Tasks: contextmenu

Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.flac\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: ""; ValueData: "Generate Subtitles with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.flac\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.flac\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.flac\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}"; Flags: uninsdeletekey; Tasks: contextmenu

Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.aac\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: ""; ValueData: "Generate Subtitles with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.aac\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.aac\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.aac\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}"; Flags: uninsdeletekey; Tasks: contextmenu

Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.ogg\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: ""; ValueData: "Generate Subtitles with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.ogg\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.ogg\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.ogg\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}"; Flags: uninsdeletekey; Tasks: contextmenu

Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.wma\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: ""; ValueData: "Generate Subtitles with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.wma\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.wma\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.wma\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}"; Flags: uninsdeletekey; Tasks: contextmenu

Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.srt\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: ""; ValueData: "Generate Subtitles with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.srt\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.srt\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.srt\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}"; Flags: uninsdeletekey; Tasks: contextmenu

Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.vtt\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: ""; ValueData: "Generate Subtitles with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.vtt\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.vtt\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.vtt\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}"; Flags: uninsdeletekey; Tasks: contextmenu

Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.lrc\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: ""; ValueData: "Generate Subtitles with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.lrc\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.lrc\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.lrc\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}"; Flags: uninsdeletekey; Tasks: contextmenu

Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.ass\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: ""; ValueData: "Generate Subtitles with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.ass\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.ass\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.ass\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}"; Flags: uninsdeletekey; Tasks: contextmenu

Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.ssa\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: ""; ValueData: "Generate Subtitles with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.ssa\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.ssa\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.ssa\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}"; Flags: uninsdeletekey; Tasks: contextmenu

Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.sbv\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: ""; ValueData: "Generate Subtitles with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.sbv\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.sbv\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.sbv\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}"; Flags: uninsdeletekey; Tasks: contextmenu

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
Filename: "https://github.com/ShahFaisalGfG/CC-Gen-Ultimate"; Description: "View README on GitHub"; Flags: shellexec nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM {#MyAppExeName}"; Flags: runhidden; RunOnceId: "KillCcGenUltimate"
Filename: "{sys}\regsvr32.exe"; Parameters: "/s /u ""{app}\ccgen_shell.dll"""; Flags: runhidden; RunOnceId: "UnregShellExt"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
function SystemInstallExists(): Boolean;
var S: String;
begin
  Result := RegQueryStringValue(HKLM, 'SOFTWARE\gfgRoyal\CC-Gen-Ultimate', 'InstallPath', S);
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  if SystemInstallExists() then
  begin
    MsgBox(
      'A system-wide installation of CC-Gen-Ultimate is already present.' + #13#10#13#10 +
      'Please use the system installer to update it.',
      mbError, MB_OK);
    Result := False;
  end;
end;

procedure InitializeWizard();
begin
  WizardForm.WelcomeLabel2.Caption :=
    'This wizard will guide you through the installation of {#MyAppName}.'#13#13 +
    'CC-Gen-Ultimate transcribes, translates, and transliterates video and audio files into subtitles - entirely offline.'#13#13 +
    'It is recommended that you close all other applications before continuing.';
end;

procedure RemoveStaleSystemRegistryEntries();
begin
  // Clean up system-wide CLSID entries left by older system installs (best-effort).
  RegDeleteKeyIncludingSubkeys(HKCR, 'CLSID\{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}');
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  DllPath: String;
  ResultCode: Integer;
begin
  if CurStep = ssInstall then
  begin
    DllPath := ExpandConstant('{app}\ccgen_shell.dll');
    if FileExists(DllPath) then
      Exec(ExpandConstant('{sys}\regsvr32.exe'), '/s /u "' + DllPath + '"',
           '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    RemoveStaleSystemRegistryEntries();
  end;
end;
