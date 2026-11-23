; =======================================================
; CC-Gen-Ultimate installers - the parts all three share
; Included by the system, user, and patch installers before
; their [Code] section (comment lines inside [Code] are Pascal).
; =======================================================

; Held by CC-Gen-Ultimate while it runs (ccgen\utils\app_mutex.py APP_MUTEXES)
#define AppMutexes "CCGenUltimateAppMutex,Global\CCGenUltimateAppMutex"

[Setup]
; The setup exe's version details: the app's name and version, as code signing requires.
VersionInfoVersion={#MyAppVersion}
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} Setup
VersionInfoCopyright=Copyright (c) 2026 Shah Faisal
; Setup asks the user to close CC-Gen-Ultimate (an update waits for it to exit) instead of
; replacing a running copy's files.
AppMutex={#AppMutexes}
; Only a running CC-Gen-Ultimate.exe can hold a file Setup replaces. Explorer keeps the shell DLL
; loaded; it is moved aside (MoveShellDllAside), so Setup never closes Explorer.
CloseApplicationsFilter=*.exe
#ifdef SplitInstaller
; GitHub refuses release files of 2 GiB or more, so a larger installer becomes a small exe and
; data parts (<name>-1.bin, -2.bin, ...) that must sit next to it (scripts\bundle.ps1).
DiskSpanning=yes
DiskSliceSize=2000000000
#endif

[UninstallDelete]
; Shell DLLs moved aside by an update (MoveShellDllAside) once nothing holds them any more
Type: files; Name: "{app}\ccgen_shell.*.old"

#include "update_support.iss"

[Code]
#ifdef PathRoot
// True when Folder is not already on PATH (compared without case and trailing backslashes).
function NeedsAddPath(Folder: String): Boolean;
var
  Paths: String;
begin
  if not RegQueryStringValue({#PathRoot}, '{#PathKey}', 'Path', Paths) then
  begin
    Result := True;
    Exit;
  end;
  Result := Pos(';' + Uppercase(RemoveBackslashUnlessRoot(Folder)) + ';', ';' + Uppercase(Paths) + ';') = 0;
end;

// Takes the install folder back off PATH when the app is uninstalled.
procedure RemoveFromPath(Folder: String);
var
  Paths, Entry, Kept: String;
  Separator: Integer;
begin
  if not RegQueryStringValue({#PathRoot}, '{#PathKey}', 'Path', Paths) then
    Exit;
  Kept := '';
  Paths := Paths + ';';
  while Length(Paths) > 0 do
  begin
    Separator := Pos(';', Paths);
    Entry := Copy(Paths, 1, Separator - 1);
    Delete(Paths, 1, Separator);
    if (Entry <> '') and (CompareText(RemoveBackslashUnlessRoot(Entry), RemoveBackslashUnlessRoot(Folder)) <> 0) then
    begin
      if Kept <> '' then
        Kept := Kept + ';';
      Kept := Kept + Entry;
    end;
  end;
  RegWriteExpandStringValue({#PathRoot}, '{#PathKey}', 'Path', Kept);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    RemoveFromPath(ExpandConstant('{app}'));
end;
#endif

// Explorer keeps ccgen_shell.dll loaded, so it can't be overwritten, but a loaded DLL can be
// renamed. The old copy moves aside as ccgen_shell.<n>.old and the new one is copied as usual, so
// a silent update never stops on a file in use; .old files nothing holds any more are deleted
// here and at uninstall.
procedure MoveShellDllAside();
var
  Dir, OldName: String;
  FindRec: TFindRec;
  N: Integer;
begin
  Dir := ExpandConstant('{app}\');
  if FindFirst(Dir + 'ccgen_shell.*.old', FindRec) then
  try
    repeat
      DeleteFile(Dir + FindRec.Name);
    until not FindNext(FindRec);
  finally
    FindClose(FindRec);
  end;
  if not FileExists(Dir + 'ccgen_shell.dll') then
    Exit;
  N := 0;
  repeat
    N := N + 1;
    OldName := Dir + 'ccgen_shell.' + IntToStr(N) + '.old';
  until not FileExists(OldName);
  if RenameFile(Dir + 'ccgen_shell.dll', OldName) then
    Log('Moved the previous shell extension aside: ' + OldName)
  else
    Log('Could not move the previous shell extension aside');
end;
