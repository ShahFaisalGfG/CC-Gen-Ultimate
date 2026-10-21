<#
.SYNOPSIS
    Build the ccgen_shell COM shell extension (.dll) for the context menu.
.DESCRIPTION
    Step 1 - Find and activate MSVC via vcvarsall.bat
    Step 2 - CMake configure (release-x64-msvc preset)
    Step 3 - CMake build (Release)
    Step 4 - Verify ccgen_shell.dll landed in build\shell\
.NOTES
    Requirements: Visual Studio 2022 or newer Build Tools (MSVC, x64)
    No vcpkg/third-party dependencies - the shell extension is pure Win32/COM.
#>

param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Definition
$ProjectRoot = Split-Path -Parent $ScriptDir
$NativeDir   = Join-Path $ProjectRoot "native"
$BuildDir    = Join-Path $NativeDir "build"
$ShellDll    = Join-Path $ProjectRoot "build\shell\ccgen_shell.dll"

# --- Helpers -----------------------------------------------------------------

function Write-Step([string]$Msg) {
    Write-Host "`n>> $Msg" -ForegroundColor Cyan
}

function Fail([string]$Msg) {
    Write-Host "`nERROR: $Msg" -ForegroundColor Red
    exit 1
}

function Invoke-VcVars([string]$VcVarsPath) {
    Write-Host "   Sourcing: $VcVarsPath" -ForegroundColor DarkGray
    $dump = cmd /c "`"$VcVarsPath`" x64 2>&1 && set"
    foreach ($line in $dump) {
        if ($line -match "^([^=]+)=(.*)$") {
            [System.Environment]::SetEnvironmentVariable($Matches[1], $Matches[2], "Process")
        }
    }
}

# --- Working directory -------------------------------------------------------

Set-Location $ProjectRoot

# --- MSVC environment --------------------------------------------------------

Write-Step "Locating MSVC (vcvarsall.bat)"

$VsWhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$VcVarsAll = $null

if (Test-Path $VsWhere) {
    $VsInstallPath = & $VsWhere -latest -products * -property installationPath 2>$null
    if ($VsInstallPath) {
        $Candidate = Join-Path $VsInstallPath "VC\Auxiliary\Build\vcvarsall.bat"
        if (Test-Path $Candidate) { $VcVarsAll = $Candidate }
    }
}

if (-not $VcVarsAll) {
    $SearchRoots = @(
        "${env:ProgramFiles(x86)}\Microsoft Visual Studio",
        "${env:ProgramFiles}\Microsoft Visual Studio"
    )
    foreach ($Root in $SearchRoots) {
        $Found = Get-ChildItem "$Root\*\*\VC\Auxiliary\Build\vcvarsall.bat" -ErrorAction SilentlyContinue |
                 Sort-Object FullName -Descending | Select-Object -First 1
        if ($Found) { $VcVarsAll = $Found.FullName; break }
    }
}

if (-not $VcVarsAll) {
    Fail "Could not find vcvarsall.bat. Install Visual Studio Build Tools with the C++ workload."
}

Invoke-VcVars $VcVarsAll

# --- CMake configure ---------------------------------------------------------

Write-Step "CMake configure"

$Preset = "release-x64-msvc"
Write-Host "   Preset : $Preset" -ForegroundColor DarkGray

# --fresh drops the cached compiler path, which otherwise outlives a Visual Studio upgrade and
# pairs the old compiler with the new toolset's headers (error STL1001).
cmake --preset $Preset -S $NativeDir -B $BuildDir --fresh
if ($LASTEXITCODE -ne 0) { Fail "CMake configure failed (exit $LASTEXITCODE)." }

# --- CMake build -------------------------------------------------------------

Write-Step "CMake build (Release)"
cmake --build $BuildDir --config Release
if ($LASTEXITCODE -ne 0) { Fail "CMake build failed (exit $LASTEXITCODE)." }

# --- Verify output -----------------------------------------------------------

Write-Step "Verifying output"

if (-not (Test-Path $ShellDll)) {
    Fail "Expected ccgen_shell.dll not found at: $ShellDll"
}

$DllKb = [math]::Round((Get-Item $ShellDll).Length / 1KB, 1)
Write-Host ""
Write-Host "Shell extension ready : $ShellDll  ($DllKb KB)" -ForegroundColor Green
