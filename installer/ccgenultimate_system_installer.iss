; =======================================================
; CC-Gen-Ultimate Windows Installer
; Inno Setup Script
; Version: 1.0.0
; =======================================================

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
; App identification
AppId={{7BFA27A3-AF1F-45DD-9F5F-CBCF2A9CEB81}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}

; Installation settings
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=..\build\installer
OutputBaseFilename={#MyAppName}_{#MyAppVersion}{#MyGpuSuffix}_system_installer
SetupIconFile={#IconsDir}\CCGenUltimate.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
WizardSizePercent=110,120

; Privileges - require admin (force system-wide install)
PrivilegesRequired=admin

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
; Main application files (compiled executable and dependencies)
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Shell extension DLL - restartreplace schedules replacement on reboot if Explorer holds a lock
Source: "{#SourceDir}\ccgen_shell.dll"; DestDir: "{app}"; Flags: ignoreversion restartreplace uninsrestartdelete
; Icon for the application
Source: "{#IconsDir}\CCGenUltimate.ico"; DestDir: "{app}\icons"; Flags: ignoreversion
; Documentation
Source: "..\requirements.txt"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "{#IconsDir}\Square150x150Logo.scale-100.png"; DestDir: "{app}\docs\icons"; Flags: ignoreversion

[InstallDelete]
; Remove the previous version's bundled runtime before copying the new one. Files a newer
; build no longer ships (old package metadata, dropped libraries) would otherwise stay behind
; and can break imports at startup - e.g. a leftover Pillow fragment made transformers fail.
; Only bundled program files live in _internal; settings, logs, and models are kept.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
; Start Menu
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\icons\CCGenUltimate.ico"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"

; Desktop
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\icons\CCGenUltimate.ico"; Tasks: desktopicon

[Registry]
; =============================================================================
; IExplorerCommand CLSID registration (Windows 11 first-level context menu)
; =============================================================================
Root: HKCR; Subkey: "CLSID\{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}"; ValueType: string; ValueName: ""; ValueData: "CC-Gen-Ultimate Subtitle Shell Extension"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "CLSID\{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}\InprocServer32"; ValueType: string; ValueName: ""; ValueData: "{app}\ccgen_shell.dll"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "CLSID\{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}\InprocServer32"; ValueType: string; ValueName: "ThreadingModel"; ValueData: "Apartment"; Flags: uninsdeletekey; Tasks: contextmenu

; =============================================================================
; Context menu: "Generate Subtitles with CC-Gen-Ultimate"
; Registered per supported extension under SystemFileAssociations so it never
; touches (or overrides) the user's actual default "open with" association.
; =============================================================================
Root: HKCR; Subkey: "SystemFileAssociations\.mp4\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: ""; ValueData: "Generate Subtitles with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.mp4\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.mp4\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.mp4\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}"; Flags: uninsdeletekey; Tasks: contextmenu

Root: HKCR; Subkey: "SystemFileAssociations\.mkv\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: ""; ValueData: "Generate Subtitles with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.mkv\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.mkv\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.mkv\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}"; Flags: uninsdeletekey; Tasks: contextmenu

Root: HKCR; Subkey: "SystemFileAssociations\.avi\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: ""; ValueData: "Generate Subtitles with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.avi\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.avi\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.avi\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}"; Flags: uninsdeletekey; Tasks: contextmenu

Root: HKCR; Subkey: "SystemFileAssociations\.mov\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: ""; ValueData: "Generate Subtitles with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.mov\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.mov\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.mov\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}"; Flags: uninsdeletekey; Tasks: contextmenu

Root: HKCR; Subkey: "SystemFileAssociations\.webm\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: ""; ValueData: "Generate Subtitles with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.webm\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.webm\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.webm\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}"; Flags: uninsdeletekey; Tasks: contextmenu

Root: HKCR; Subkey: "SystemFileAssociations\.flv\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: ""; ValueData: "Generate Subtitles with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.flv\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.flv\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.flv\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}"; Flags: uninsdeletekey; Tasks: contextmenu

Root: HKCR; Subkey: "SystemFileAssociations\.wmv\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: ""; ValueData: "Generate Subtitles with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.wmv\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.wmv\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.wmv\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}"; Flags: uninsdeletekey; Tasks: contextmenu

Root: HKCR; Subkey: "SystemFileAssociations\.ts\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: ""; ValueData: "Generate Subtitles with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.ts\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.ts\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.ts\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}"; Flags: uninsdeletekey; Tasks: contextmenu

Root: HKCR; Subkey: "SystemFileAssociations\.m2ts\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: ""; ValueData: "Generate Subtitles with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.m2ts\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.m2ts\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.m2ts\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}"; Flags: uninsdeletekey; Tasks: contextmenu

Root: HKCR; Subkey: "SystemFileAssociations\.mp3\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: ""; ValueData: "Generate Subtitles with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.mp3\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.mp3\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.mp3\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}"; Flags: uninsdeletekey; Tasks: contextmenu

Root: HKCR; Subkey: "SystemFileAssociations\.wav\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: ""; ValueData: "Generate Subtitles with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.wav\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.wav\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.wav\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}"; Flags: uninsdeletekey; Tasks: contextmenu

Root: HKCR; Subkey: "SystemFileAssociations\.m4a\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: ""; ValueData: "Generate Subtitles with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.m4a\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.m4a\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.m4a\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}"; Flags: uninsdeletekey; Tasks: contextmenu

Root: HKCR; Subkey: "SystemFileAssociations\.flac\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: ""; ValueData: "Generate Subtitles with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.flac\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.flac\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.flac\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}"; Flags: uninsdeletekey; Tasks: contextmenu

Root: HKCR; Subkey: "SystemFileAssociations\.aac\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: ""; ValueData: "Generate Subtitles with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.aac\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.aac\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.aac\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}"; Flags: uninsdeletekey; Tasks: contextmenu

Root: HKCR; Subkey: "SystemFileAssociations\.ogg\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: ""; ValueData: "Generate Subtitles with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.ogg\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.ogg\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.ogg\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}"; Flags: uninsdeletekey; Tasks: contextmenu

Root: HKCR; Subkey: "SystemFileAssociations\.wma\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: ""; ValueData: "Generate Subtitles with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.wma\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.wma\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.wma\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}"; Flags: uninsdeletekey; Tasks: contextmenu

Root: HKCR; Subkey: "SystemFileAssociations\.srt\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: ""; ValueData: "Generate Subtitles with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.srt\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.srt\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.srt\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}"; Flags: uninsdeletekey; Tasks: contextmenu

Root: HKCR; Subkey: "SystemFileAssociations\.vtt\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: ""; ValueData: "Generate Subtitles with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.vtt\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.vtt\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.vtt\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}"; Flags: uninsdeletekey; Tasks: contextmenu

Root: HKCR; Subkey: "SystemFileAssociations\.lrc\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: ""; ValueData: "Generate Subtitles with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.lrc\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.lrc\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.lrc\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}"; Flags: uninsdeletekey; Tasks: contextmenu

Root: HKCR; Subkey: "SystemFileAssociations\.ass\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: ""; ValueData: "Generate Subtitles with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.ass\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.ass\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.ass\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}"; Flags: uninsdeletekey; Tasks: contextmenu

Root: HKCR; Subkey: "SystemFileAssociations\.ssa\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: ""; ValueData: "Generate Subtitles with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.ssa\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.ssa\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.ssa\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}"; Flags: uninsdeletekey; Tasks: contextmenu

Root: HKCR; Subkey: "SystemFileAssociations\.sbv\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: ""; ValueData: "Generate Subtitles with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.sbv\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.sbv\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.sbv\shell\CCGenUltimateSubtitles"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}"; Flags: uninsdeletekey; Tasks: contextmenu

; =============================================================================
; Optional: Store installation info (useful for future updates/uninstallers)
; =============================================================================
Root: HKLM; Subkey: "SOFTWARE\{#MyAppPublisher}\{#MyAppName}"; ValueType: string; ValueName: "InstallPath"; ValueData: "{app}"; Flags: uninsdeletekey
Root: HKLM; Subkey: "SOFTWARE\{#MyAppPublisher}\{#MyAppName}"; ValueType: string; ValueName: "Version"; ValueData: "{#MyAppVersion}"; Flags: uninsdeletekey
Root: HKLM; Subkey: "SOFTWARE\{#MyAppPublisher}\{#MyAppName}"; ValueType: string; ValueName: "ExePath"; ValueData: "{app}\{#MyAppExeName}"; Flags: uninsdeletekey

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
Filename: "https://github.com/ShahFaisalGfG/CC-Gen-Ultimate"; Description: "View README on GitHub"; Flags: shellexec nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM {#MyAppExeName}"; Flags: runhidden; RunOnceId: "KillCcGenUltimate"
Filename: "{sys}\regsvr32.exe"; Parameters: "/s /u ""{app}\ccgen_shell.dll"""; Flags: runhidden; RunOnceId: "UnregShellExt"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
function UserInstallExists(): Boolean;
var S: String;
begin
  Result :=
    RegQueryStringValue(HKCU,
      'Software\Microsoft\Windows\CurrentVersion\Uninstall\' +
      '{7BFA27A3-AF1F-45DD-9F5F-CBCF2A9CEB81}_is1', 'InstallLocation', S);
end;

function GetUserUninstallStr(out UninstStr: String): Boolean;
begin
  Result :=
    RegQueryStringValue(HKCU,
      'Software\Microsoft\Windows\CurrentVersion\Uninstall\' +
      '{7BFA27A3-AF1F-45DD-9F5F-CBCF2A9CEB81}_is1', 'UninstallString', UninstStr);
end;

function InitializeSetup(): Boolean;
var
  UninstStr: String;
  ResultCode: Integer;
begin
  Result := True;
  if UserInstallExists() then
  begin
    if MsgBox(
      'A per-user installation of CC-Gen-Ultimate was found.' + #13#10#13#10 +
      'Click Yes to remove it and continue with the system-wide installation.' + #13#10 +
      'Click No to cancel - then use the per-user installer to update instead.',
      mbConfirmation, MB_YESNO) = IDNO then
    begin
      Result := False;
      Exit;
    end;
    if GetUserUninstallStr(UninstStr) then
      Exec(RemoveQuotes(UninstStr), '/VERYSILENT /NORESTART', '',
           SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
end;

procedure InitializeWizard();
begin
  WizardForm.WelcomeLabel2.Caption :=
    'This wizard will guide you through the installation of {#MyAppName}.'#13#13 +
    'CC-Gen-Ultimate transcribes, translates, and transliterates video and audio files into subtitles - entirely offline.'#13#13 +
    'It is recommended that you close all other applications before continuing.';
end;

procedure RemoveStaleUserRegistryEntries();
begin
  // Clean up per-user CLSID and context-menu entries left by older per-user installs.
  RegDeleteKeyIncludingSubkeys(HKCU, 'Software\Classes\CLSID\{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}');
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
    RemoveStaleUserRegistryEntries();
  end;
end;
