<#
.SYNOPSIS
    Full build: native shell extension, both installers, and portable exe.
.DESCRIPTION
    Step 1 - Native build : compiles ccgen_shell.dll (context menu)
    Step 2 - PyInstaller  : bundles the app into dist\CC-Gen-Ultimate\
    Step 3 - Shell DLL    : copies ccgen_shell.dll into dist\CC-Gen-Ultimate\
    Step 4 - Inno Setup   : compiles system and user installers into build\installer\
    Step 5 - Portable     : builds a single-file portable exe into build\
.PARAMETER Gpu
    Which GPU the build's PyTorch targets: "cuda" (NVIDIA GTX 10 series to RTX 50, the default
    and main release), "xpu" (Intel Arc and Core Ultra; file names get an "_intel_gpu" suffix),
    or "legacy" (older NVIDIA GPUs; "_nvidia_legacy"). Piper and Kokoro voices use DirectML on
    any GPU in every build. Installs that runtime into the venv first.
.PARAMETER LegacyNvidia
    Also build the Legacy NVIDIA edition ("_nvidia_legacy"), whose PyTorch runs on older NVIDIA
    GPUs such as the GeForce 940MX and GTX 900 series. It is built first, in its own run of this
    script, so the venv ends on the -Gpu edition's PyTorch.
.NOTES
    Requirements: Python venv with pyinstaller>=6.17, Inno Setup 6, Visual Studio Build Tools
#>

param(
    [ValidateSet("cuda", "xpu", "legacy")] [string]$Gpu = "cuda",
    [switch]$LegacyNvidia
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── Configuration ─────────────────────────────────────────────────────────────

$IssFiles = @(
    "installer\ccgenultimate_system_installer.iss",
    "installer\ccgenultimate_user_installer.iss"
)
$IsccPaths = @(
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
)

# ── Helpers ───────────────────────────────────────────────────────────────────

function Write-Step([string]$Msg) {
    Write-Host ""
    Write-Host ">> $Msg" -ForegroundColor Cyan
}

function Fail([string]$Msg) {
    Write-Host ""
    Write-Host "ERROR: $Msg" -ForegroundColor Red
    exit 1
}

function Invoke-Iscc([string]$IssPath) {
    # Compiles an ISS file, injecting all app metadata as ISCC /D definitions.
    Write-Host "   Compiling : $IssPath" -ForegroundColor DarkGray
    & $Iscc `
        "/DMyAppName=$($Meta.AppName)" `
        "/DMyAppVersion=$($Meta.Version)" `
        "/DMyAppPublisher=$($Meta.Publisher)" `
        "/DMyAppURL=$($Meta.Url)" `
        "/DMyGpuSuffix=$Suffix" `
        $IssPath
    if ($LASTEXITCODE -ne 0) {
        Fail "Inno Setup failed for '$IssPath' (exit $LASTEXITCODE)."
    }
}

function Format-Elapsed([TimeSpan]$ts) {
    # $ts.Minutes/.Seconds are sub-hour remainders (0-59) - the hours branch must
    # come first, or any run past 60 minutes silently drops its hour component.
    if ($ts.TotalHours -ge 1)   { return "{0}h {1:D2}m {2:D2}s" -f [math]::Floor($ts.TotalHours), $ts.Minutes, $ts.Seconds }
    if ($ts.TotalMinutes -ge 1) { return "{0}m {1:D2}s" -f [int]$ts.Minutes, $ts.Seconds }
    return "{0}s" -f [int]$ts.TotalSeconds
}

# ── Working directory ─────────────────────────────────────────────────────────

$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Definition
$ProjectRoot = Split-Path -Parent $ScriptDir
$BuildStart  = Get-Date
Set-Location $ProjectRoot

# ── Legacy NVIDIA edition ─────────────────────────────────────────────────────

if ($LegacyNvidia -and $Gpu -ne "legacy") {
    Write-Step "Building the Legacy NVIDIA edition first"
    & $PSCommandPath -Gpu legacy
    if ($LASTEXITCODE -ne 0) {
        Fail "The Legacy NVIDIA edition build failed (exit $LASTEXITCODE). Check output above."
    }
}

# ── App metadata ──────────────────────────────────────────────────────────────

. "$ScriptDir\app_meta.ps1"
. "$ScriptDir\bundle.ps1"
$Meta    = Get-AppMeta
$AppName = $Meta.AppName
$Version = $Meta.Version
$DistDir = "dist\$AppName"
$Suffix  = $GpuSuffix[$Gpu]

# ── Native context-menu shell extension ───────────────────────────────────────

Write-Step "Building native context-menu shell extension (ccgen_shell.dll)"

& "$ScriptDir\build_native.ps1"
if ($LASTEXITCODE -ne 0) {
    Fail "build_native.ps1 failed (exit $LASTEXITCODE). Check output above."
}

# ── Virtual environment ───────────────────────────────────────────────────────

Write-Step "Activating virtual environment"

$VenvScripts = @(".venv\Scripts\Activate.ps1", "venv\Scripts\Activate.ps1")
$VenvFound   = $false
foreach ($v in $VenvScripts) {
    if (Test-Path $v) {
        . $v
        $VenvFound = $true
        Write-Host "   Activated: $v" -ForegroundColor DarkGray
        break
    }
}
if (-not $VenvFound) {
    Write-Host "   No venv found - using system Python" -ForegroundColor Yellow
}

# ── Prerequisites ─────────────────────────────────────────────────────────────

Write-Step "Checking prerequisites"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Fail "python not found in PATH"
}
if (-not (Get-Command pyinstaller -ErrorAction SilentlyContinue)) {
    Fail "pyinstaller not found. Install it with: pip install 'pyinstaller>=6.17'"
}

$Iscc = $null
foreach ($p in $IsccPaths) {
    if (Test-Path $p) { $Iscc = $p; break }
}
if (-not $Iscc) {
    Fail "Inno Setup 6 not found. Download from: https://jrsoftware.org/isinfo.php"
}

Write-Step "Installing the $Gpu GPU runtime (PyTorch $($TorchPin[$Gpu]) and DirectML)"

Install-GpuRuntime -Gpu $Gpu

Write-Host "   Python      : $(python --version)"         -ForegroundColor DarkGray
Write-Host "   PyInstaller : $(pyinstaller --version)"    -ForegroundColor DarkGray
Write-Host "   ISCC        : $Iscc"                       -ForegroundColor DarkGray

# ── Clean ─────────────────────────────────────────────────────────────────────

Write-Step "Cleaning previous build artifacts"

foreach ($path in @($DistDir, "build\pyinstaller", "build\$AppName", "$AppName.spec")) {
    if (Test-Path $path) {
        Remove-Item $path -Recurse -Force
        Write-Host "   Removed $path" -ForegroundColor DarkGray
    }
}

New-Item -ItemType Directory -Path "build\installer" -Force | Out-Null

# ── PyInstaller ───────────────────────────────────────────────────────────────

Write-Step "Running PyInstaller  (this may take several minutes)"

$PyArgs = Get-PyInstallerArgs -Name $AppName -Mode onedir -DistPath "dist"

pyinstaller @PyArgs

if ($LASTEXITCODE -ne 0) {
    Fail "PyInstaller failed (exit $LASTEXITCODE). Check output above."
}

$ExePath = "$DistDir\$AppName.exe"
if (-not (Test-Path $ExePath)) {
    Fail "Expected executable not found: $ExePath"
}

$BundleMb = [math]::Round((Get-ChildItem $DistDir -Recurse | Measure-Object Length -Sum).Sum / 1MB, 1)
Write-Host "   Bundle ready : $DistDir  ($BundleMb MB)" -ForegroundColor DarkGray

# ── Bundle self-test ──────────────────────────────────────────────────────────

Write-Step "Verifying the bundle can load every engine, library, and QML module"

if (-not (Test-Bundle $ExePath)) {
    Fail "Bundle self-test failed - a module, DLL, or data file is missing from the build. See the report above."
}

# ── Shell extension DLL ───────────────────────────────────────────────────────

Write-Step "Copying ccgen_shell.dll to dist"

$ShellDll = Join-Path $ProjectRoot "build\shell\ccgen_shell.dll"
if (-not (Test-Path $ShellDll)) {
    Fail "ccgen_shell.dll not found at: $ShellDll - did build_native.ps1 succeed?"
}
Copy-Item $ShellDll (Join-Path $ProjectRoot "dist\$AppName\ccgen_shell.dll") -Force
Write-Host "   Copied ccgen_shell.dll to dist\$AppName\" -ForegroundColor DarkGray

# ── Inno Setup ────────────────────────────────────────────────────────────────

Write-Step "Compiling installers with Inno Setup"

$IsccElapsed = @()
foreach ($iss in $IssFiles) {
    $t = Get-Date
    Invoke-Iscc $iss
    $IsccElapsed += (Get-Date) - $t
}

# ── Portable Exe ──────────────────────────────────────────────────────────────

Write-Step "Building portable executable"

$PortableName = "${AppName}_${Version}${Suffix}_portable"
$PortableExe  = "build\${PortableName}.exe"

foreach ($path in @("${PortableName}.spec", $PortableExe)) {
    if (Test-Path $path) {
        Remove-Item $path -Recurse -Force
        Write-Host "   Removed $path" -ForegroundColor DarkGray
    }
}

$PortableArgs = Get-PyInstallerArgs -Name $PortableName -Mode onefile -DistPath "build"

$PortableStart = Get-Date
pyinstaller @PortableArgs

if ($LASTEXITCODE -ne 0) {
    Fail "PyInstaller (portable) failed (exit $LASTEXITCODE). Check output above."
}
if (-not (Test-Path $PortableExe)) {
    Fail "Expected portable executable not found: $PortableExe"
}
if (-not (Test-Bundle $PortableExe)) {
    Fail "Portable self-test failed - a module, DLL, or data file is missing from the build. See the report above."
}
$PortableElapsed = (Get-Date) - $PortableStart

# ── Done ──────────────────────────────────────────────────────────────────────

$Outputs = @(
    "build\installer\${AppName}_${Version}${Suffix}_system_installer.exe",
    "build\installer\${AppName}_${Version}${Suffix}_user_installer.exe"
)

Write-Host ""
Write-Host "Build complete in $(Format-Elapsed ((Get-Date) - $BuildStart))." -ForegroundColor Green

for ($i = 0; $i -lt $Outputs.Count; $i++) {
    $out = $Outputs[$i]
    if (Test-Path $out) {
        $Mb = [math]::Round((Get-Item $out).Length / 1MB, 1)
        $elapsed = if ($i -lt $IsccElapsed.Count) { "  ($(Format-Elapsed $IsccElapsed[$i]))" } else { "" }
        Write-Host "Installer    : $out  ($Mb MB)$elapsed" -ForegroundColor Green
    } else {
        Write-Host "Missing      : $out" -ForegroundColor Yellow
    }
}

if (Test-Path $PortableExe) {
    $PortableMb = [math]::Round((Get-Item $PortableExe).Length / 1MB, 1)
    Write-Host "Portable Exe : $PortableExe  ($PortableMb MB)  ($(Format-Elapsed $PortableElapsed))" -ForegroundColor Green
} else {
    Write-Host "Missing      : $PortableExe" -ForegroundColor Yellow
}
