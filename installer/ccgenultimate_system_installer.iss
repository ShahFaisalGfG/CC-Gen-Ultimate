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
  #define MyAppURL "https://shahfaisalgfg.github.io/"
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
; The PATH the "Add the ccgen command to PATH" task changes (shared.iss NeedsAddPath, RemoveFromPath)
#define PathRoot "HKLM"
#define PathKey "SYSTEM\CurrentControlSet\Control\Session Manager\Environment"

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
; The PATH task changes the environment, so running terminals are told about it.
ChangesEnvironment=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
english.EnableContextMenu=Add CC-Gen-Ultimate to the right-click menu of video, audio, and subtitle files (Generate Subtitles, Translate, Transliterate)
english.ContextMenu=Explorer integration:

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "contextmenu"; Description: "{cm:EnableContextMenu}"; GroupDescription: "{cm:ContextMenu}"
Name: "addtopath"; Description: "Add the ccgen command to PATH (make, translate, and dub subtitles from any terminal)"; GroupDescription: "Command line:"; Flags: unchecked

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
; The ccgen command on PATH (taken off again at uninstall, shared.iss RemoveFromPath)
Root: {#PathRoot}; Subkey: "{#PathKey}"; ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}"; Tasks: addtopath; Check: NeedsAddPath(ExpandConstant('{app}'))
; =============================================================================
; IExplorerCommand CLSID registration (Windows 11 first-level context menu)
; One CLSID per menu entry; they match native/src/shell_extension.cpp.
; =============================================================================
Root: HKCR; Subkey: "CLSID\{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}"; ValueType: string; ValueName: ""; ValueData: "CC-Gen-Ultimate Subtitle Shell Extension"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "CLSID\{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}\InprocServer32"; ValueType: string; ValueName: ""; ValueData: "{app}\ccgen_shell.dll"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "CLSID\{{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}\InprocServer32"; ValueType: string; ValueName: "ThreadingModel"; ValueData: "Apartment"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "CLSID\{{00B71345-AC5E-4B8C-B19B-4B7A583417F9}"; ValueType: string; ValueName: ""; ValueData: "CC-Gen-Ultimate Translate Shell Extension"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "CLSID\{{00B71345-AC5E-4B8C-B19B-4B7A583417F9}\InprocServer32"; ValueType: string; ValueName: ""; ValueData: "{app}\ccgen_shell.dll"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "CLSID\{{00B71345-AC5E-4B8C-B19B-4B7A583417F9}\InprocServer32"; ValueType: string; ValueName: "ThreadingModel"; ValueData: "Apartment"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "CLSID\{{3382A0C2-1398-4A61-B731-53C435DEF132}"; ValueType: string; ValueName: ""; ValueData: "CC-Gen-Ultimate Transliterate Shell Extension"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "CLSID\{{3382A0C2-1398-4A61-B731-53C435DEF132}\InprocServer32"; ValueType: string; ValueName: ""; ValueData: "{app}\ccgen_shell.dll"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "CLSID\{{3382A0C2-1398-4A61-B731-53C435DEF132}\InprocServer32"; ValueType: string; ValueName: "ThreadingModel"; ValueData: "Apartment"; Flags: uninsdeletekey; Tasks: contextmenu

; =============================================================================
; Context menu: "Generate Subtitles with CC-Gen-Ultimate" on video and audio files
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

; =============================================================================
; Context menu: "Translate with CC-Gen-Ultimate" and "Transliterate with CC-Gen-Ultimate"
; on subtitle files
; Older versions put "Generate Subtitles" on subtitle files (CCGenUltimateSubtitles); it is
; removed first.
; =============================================================================
Root: HKCR; Subkey: "SystemFileAssociations\.srt\shell\CCGenUltimateSubtitles"; ValueType: none; Flags: deletekey
Root: HKCR; Subkey: "SystemFileAssociations\.srt\shell\CCGenUltimateTranslate"; ValueType: string; ValueName: ""; ValueData: "Translate with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.srt\shell\CCGenUltimateTranslate"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.srt\shell\CCGenUltimateTranslate"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.srt\shell\CCGenUltimateTranslate"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{00B71345-AC5E-4B8C-B19B-4B7A583417F9}"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.srt\shell\CCGenUltimateTransliterate"; ValueType: string; ValueName: ""; ValueData: "Transliterate with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.srt\shell\CCGenUltimateTransliterate"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.srt\shell\CCGenUltimateTransliterate"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.srt\shell\CCGenUltimateTransliterate"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{3382A0C2-1398-4A61-B731-53C435DEF132}"; Flags: uninsdeletekey; Tasks: contextmenu

Root: HKCR; Subkey: "SystemFileAssociations\.vtt\shell\CCGenUltimateSubtitles"; ValueType: none; Flags: deletekey
Root: HKCR; Subkey: "SystemFileAssociations\.vtt\shell\CCGenUltimateTranslate"; ValueType: string; ValueName: ""; ValueData: "Translate with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.vtt\shell\CCGenUltimateTranslate"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.vtt\shell\CCGenUltimateTranslate"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.vtt\shell\CCGenUltimateTranslate"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{00B71345-AC5E-4B8C-B19B-4B7A583417F9}"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.vtt\shell\CCGenUltimateTransliterate"; ValueType: string; ValueName: ""; ValueData: "Transliterate with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.vtt\shell\CCGenUltimateTransliterate"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.vtt\shell\CCGenUltimateTransliterate"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.vtt\shell\CCGenUltimateTransliterate"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{3382A0C2-1398-4A61-B731-53C435DEF132}"; Flags: uninsdeletekey; Tasks: contextmenu

Root: HKCR; Subkey: "SystemFileAssociations\.lrc\shell\CCGenUltimateSubtitles"; ValueType: none; Flags: deletekey
Root: HKCR; Subkey: "SystemFileAssociations\.lrc\shell\CCGenUltimateTranslate"; ValueType: string; ValueName: ""; ValueData: "Translate with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.lrc\shell\CCGenUltimateTranslate"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.lrc\shell\CCGenUltimateTranslate"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.lrc\shell\CCGenUltimateTranslate"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{00B71345-AC5E-4B8C-B19B-4B7A583417F9}"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.lrc\shell\CCGenUltimateTransliterate"; ValueType: string; ValueName: ""; ValueData: "Transliterate with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.lrc\shell\CCGenUltimateTransliterate"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.lrc\shell\CCGenUltimateTransliterate"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.lrc\shell\CCGenUltimateTransliterate"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{3382A0C2-1398-4A61-B731-53C435DEF132}"; Flags: uninsdeletekey; Tasks: contextmenu

Root: HKCR; Subkey: "SystemFileAssociations\.ass\shell\CCGenUltimateSubtitles"; ValueType: none; Flags: deletekey
Root: HKCR; Subkey: "SystemFileAssociations\.ass\shell\CCGenUltimateTranslate"; ValueType: string; ValueName: ""; ValueData: "Translate with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.ass\shell\CCGenUltimateTranslate"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.ass\shell\CCGenUltimateTranslate"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.ass\shell\CCGenUltimateTranslate"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{00B71345-AC5E-4B8C-B19B-4B7A583417F9}"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.ass\shell\CCGenUltimateTransliterate"; ValueType: string; ValueName: ""; ValueData: "Transliterate with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.ass\shell\CCGenUltimateTransliterate"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.ass\shell\CCGenUltimateTransliterate"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.ass\shell\CCGenUltimateTransliterate"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{3382A0C2-1398-4A61-B731-53C435DEF132}"; Flags: uninsdeletekey; Tasks: contextmenu

Root: HKCR; Subkey: "SystemFileAssociations\.ssa\shell\CCGenUltimateSubtitles"; ValueType: none; Flags: deletekey
Root: HKCR; Subkey: "SystemFileAssociations\.ssa\shell\CCGenUltimateTranslate"; ValueType: string; ValueName: ""; ValueData: "Translate with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.ssa\shell\CCGenUltimateTranslate"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.ssa\shell\CCGenUltimateTranslate"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.ssa\shell\CCGenUltimateTranslate"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{00B71345-AC5E-4B8C-B19B-4B7A583417F9}"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.ssa\shell\CCGenUltimateTransliterate"; ValueType: string; ValueName: ""; ValueData: "Transliterate with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.ssa\shell\CCGenUltimateTransliterate"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.ssa\shell\CCGenUltimateTransliterate"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.ssa\shell\CCGenUltimateTransliterate"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{3382A0C2-1398-4A61-B731-53C435DEF132}"; Flags: uninsdeletekey; Tasks: contextmenu

Root: HKCR; Subkey: "SystemFileAssociations\.sbv\shell\CCGenUltimateSubtitles"; ValueType: none; Flags: deletekey
Root: HKCR; Subkey: "SystemFileAssociations\.sbv\shell\CCGenUltimateTranslate"; ValueType: string; ValueName: ""; ValueData: "Translate with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.sbv\shell\CCGenUltimateTranslate"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.sbv\shell\CCGenUltimateTranslate"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.sbv\shell\CCGenUltimateTranslate"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{00B71345-AC5E-4B8C-B19B-4B7A583417F9}"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.sbv\shell\CCGenUltimateTransliterate"; ValueType: string; ValueName: ""; ValueData: "Transliterate with CC-Gen-Ultimate"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.sbv\shell\CCGenUltimateTransliterate"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\icons\CCGenUltimate.ico"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.sbv\shell\CCGenUltimateTransliterate"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCR; Subkey: "SystemFileAssociations\.sbv\shell\CCGenUltimateTransliterate"; ValueType: string; ValueName: "ExplorerCommandHandler"; ValueData: "{{3382A0C2-1398-4A61-B731-53C435DEF132}"; Flags: uninsdeletekey; Tasks: contextmenu

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
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM ccgen.exe"; Flags: runhidden; RunOnceId: "KillCcgen"
Filename: "{sys}\regsvr32.exe"; Parameters: "/s /u ""{app}\ccgen_shell.dll"""; Flags: runhidden; RunOnceId: "UnregShellExt"

[UninstallDelete]
; Installed files are removed by the uninstaller itself. The folder goes only when it is empty, so
; installing into a folder that already held other files can never cost those files. Each user's
; settings, logs, and models live in their own profile and are kept for a reinstall.
Type: dirifempty; Name: "{app}"

#include "shared.iss"

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

var
  UserDataMoved: Boolean;

// This user's data folders, which the copy installed for all users reads too: Roaming holds the
// settings, workflows, and logs, Local the translation models and voices.
function RoamingDir(): String;
begin
  Result := ExpandConstant('{userappdata}\{#MyAppName}');
end;

function LocalDir(): String;
begin
  Result := ExpandConstant('{localappdata}\{#MyAppName}');
end;

// Where a folder's items wait while the per-user copy is removed.
function KeptDir(const Dir: String): String;
begin
  Result := Dir + ' (kept by Setup)';
end;

// Moves the file or folder Name from FromDir to ToDir; True when it moved.
function MoveDataItem(const Name, FromDir, ToDir: String): Boolean;
var
  Source, Target: String;
begin
  Result := False;
  Source := AddBackslash(FromDir) + Name;
  Target := AddBackslash(ToDir) + Name;
  if not FileExists(Source) and not DirExists(Source) then
    Exit;
  if FileExists(Target) or DirExists(Target) then
    Log('Left ' + Source + ' where it is: ' + Target + ' already exists')
  else if not ForceDirectories(ToDir) then
    Log('Could not create ' + ToDir)
  else
  begin
    Result := RenameFile(Source, Target);
    if not Result then
      Log('Could not move ' + Source + ' to ' + Target);
  end;
end;

// The per-user uninstaller deletes this user's data, so it moves aside until that copy is gone.
// That copy's update state (updates.json) and downloaded updates go with it. Keep in step with
// the user installer's [UninstallDelete].
procedure KeepUserData();
begin
  if MoveDataItem('settings.json', RoamingDir(), KeptDir(RoamingDir())) then
    UserDataMoved := True;
  if MoveDataItem('workflows.json', RoamingDir(), KeptDir(RoamingDir())) then
    UserDataMoved := True;
  if MoveDataItem('logs', RoamingDir(), KeptDir(RoamingDir())) then
    UserDataMoved := True;
  if MoveDataItem('translation', LocalDir(), KeptDir(LocalDir())) then
    UserDataMoved := True;
  if MoveDataItem('voices', LocalDir(), KeptDir(LocalDir())) then
    UserDataMoved := True;
end;

// Puts back what KeepUserData moved; a later call does nothing.
procedure RestoreUserData();
begin
  if not UserDataMoved then
    Exit;
  MoveDataItem('settings.json', KeptDir(RoamingDir()), RoamingDir());
  MoveDataItem('workflows.json', KeptDir(RoamingDir()), RoamingDir());
  MoveDataItem('logs', KeptDir(RoamingDir()), RoamingDir());
  RemoveDir(KeptDir(RoamingDir()));
  MoveDataItem('translation', KeptDir(LocalDir()), LocalDir());
  MoveDataItem('voices', KeptDir(LocalDir()), LocalDir());
  RemoveDir(KeptDir(LocalDir()));
  UserDataMoved := False;
end;

function InitializeSetup(): Boolean;
var
  UninstStr: String;
  ResultCode: Integer;
begin
  Result := True;
  if UserInstallExists() then
  begin
    if SuppressibleMsgBox(
      'A per-user installation of CC-Gen-Ultimate was found.' + #13#10#13#10 +
      'Click Yes to remove it and continue with the system-wide installation. Your settings, workflows, logs, and downloaded models are kept.' + #13#10 +
      'Click No to cancel - then use the per-user installer to update instead.',
      mbConfirmation, MB_YESNO, IDNO) = IDNO then
    begin
      Result := False;
      Exit;
    end;
    if GetUserUninstallStr(UninstStr) then
    begin
      KeepUserData();
      Exec(RemoveQuotes(UninstStr), '/VERYSILENT /NORESTART', '',
           SW_HIDE, ewWaitUntilTerminated, ResultCode);
    end;
  end;
end;

procedure DeinitializeSetup();
begin
  RestoreUserData();
end;

procedure InitializeWizard();
begin
  WizardForm.WelcomeLabel2.Caption :=
    'This wizard will guide you through the installation of {#MyAppName}.'#13#13 +
    'CC-Gen-Ultimate transcribes, translates, and transliterates video and audio files into subtitles on this PC; your media never leaves it.'#13#13 +
    'It is recommended that you close all other applications before continuing.';
end;

procedure RemoveStaleUserRegistryEntries();
begin
  // Clean up per-user CLSID and context-menu entries left by older per-user installs.
  RegDeleteKeyIncludingSubkeys(HKCU, 'Software\Classes\CLSID\{5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182}');
  RegDeleteKeyIncludingSubkeys(HKCU, 'Software\Classes\CLSID\{00B71345-AC5E-4B8C-B19B-4B7A583417F9}');
  RegDeleteKeyIncludingSubkeys(HKCU, 'Software\Classes\CLSID\{3382A0C2-1398-4A61-B731-53C435DEF132}');
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
    MoveShellDllAside();
    RemoveStaleUserRegistryEntries();
  end
  else if CurStep = ssPostInstall then
    RestoreUserData();
end;
