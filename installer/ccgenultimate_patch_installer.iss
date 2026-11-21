; =======================================================
; CC-Gen-Ultimate patch installer (Inno Setup)
; Replaces only the app layer of an installed copy (the exe,
; _internal\ccgen, the licence texts, build.ini) when its bundled
; runtime (PyTorch, CUDA, Qt, and the other libraries) is the same
; as this release's, so an update is tens of megabytes instead of
; the whole edition. scripts\runtime_id.py defines both layers.
; The in-app updater runs it silently with /ALLUSERS (a system
; install) or /CURRENTUSER and /DIR=<install folder>; it refuses a
; copy whose runtime differs, which needs the full installer.
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
  #define MyGpuSuffix ""
#endif
#ifndef MyAppExeName
  #define MyAppExeName "CC-Gen-Ultimate.exe"
#endif
#define SourceDir "..\dist\CC-Gen-Ultimate"
#define IconsDir "..\ccgen\assets\icons"
; The runtime this patch fits, from the bundle's build.ini (scripts\bundle.ps1 Write-BuildInfo).
#define RuntimeId ReadIni(SourcePath + SourceDir + "\build.ini", "build", "runtime_id", "")
#if RuntimeId == ""
  #error dist\CC-Gen-Ultimate\build.ini is missing: run Write-BuildInfo before building the patch
#endif

[Setup]
; The same AppId as the full installers: the patch updates their install and uninstall entry.
AppId={{7BFA27A3-AF1F-45DD-9F5F-CBCF2A9CEB81}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
; One patch serves both install kinds: /ALLUSERS asks for administrator rights like the system
; installer, /CURRENTUSER doesn't, like the user installer.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline
DefaultDirName={autopf}\{#MyAppName}
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
CreateAppDir=yes
OutputDir=..\build\installer
OutputBaseFilename={#MyAppName}_{#MyAppVersion}{#MyGpuSuffix}_patch_installer
SetupIconFile={#IconsDir}\CCGenUltimate.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; Keep in step with APP_LAYER_* in scripts\runtime_id.py.
Source: "{#SourceDir}\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\build.ini"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\_internal\ccgen\*"; DestDir: "{app}\_internal\ccgen"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#SourceDir}\_internal\LICENSE"; DestDir: "{app}\_internal"; Flags: ignoreversion
Source: "{#SourceDir}\_internal\THIRD_PARTY_NOTICES.md"; DestDir: "{app}\_internal"; Flags: ignoreversion

[InstallDelete]
; The app's QML and assets are replaced as a whole, so files this version no longer ships go.
Type: filesandordirs; Name: "{app}\_internal\ccgen"

[Registry]
; The version the system installer records for all users
Root: HKLM; Subkey: "SOFTWARE\{#MyAppPublisher}\{#MyAppName}"; ValueType: string; ValueName: "Version"; ValueData: "{#MyAppVersion}"; Check: IsAdminInstallMode

#include "shared.iss"

[Code]
// A patch fits only a copy of this edition with the same runtime; anything else needs the full
// installer, so Setup stops before changing a file.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Installed: String;
begin
  Result := '';
  if not FileExists(ExpandConstant('{app}\{#MyAppExeName}')) then
    Result := '{#MyAppName} is not installed in ' + ExpandConstant('{app}') + '. Use the full installer instead.'
  else
  begin
    Installed := GetIniString('build', 'runtime_id', '', ExpandConstant('{app}\build.ini'));
    if CompareText(Installed, '{#RuntimeId}') <> 0 then
      Result := 'This update needs the full {#MyAppName} installer: the installed copy has a different runtime.';
  end;
  if Result <> '' then
    Log(Result);
end;
