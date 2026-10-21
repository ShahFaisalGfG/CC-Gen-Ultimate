<#
.SYNOPSIS
    Build the CC-Gen-Ultimate portable single-file executable.
.DESCRIPTION
    Bundles the app into one self-contained exe: build\CC-Gen-Ultimate_<version>_portable.exe
    No installer is produced - the exe runs directly without installation.
    Note: the Explorer context-menu integration is installer-only (it needs registry
    entries), so the portable build does not include ccgen_shell.dll.
.PARAMETER Gpu
    Which GPU the build's PyTorch targets: "cuda" (NVIDIA, the default), "xpu" (Intel Arc and
    Core Ultra; file names get an "_intel_gpu" suffix), or "legacy" (older NVIDIA GPUs;
    "_nvidia_legacy"). See scripts/bundle.ps1.
.PARAMETER LegacyNvidia
    Also build the Legacy NVIDIA edition ("_nvidia_legacy"), whose PyTorch runs on older NVIDIA
    GPUs such as the GeForce 940MX and GTX 900 series. It is built first, in its own run of this
    script, so the venv ends on the -Gpu edition's PyTorch.
.NOTES
    Requirements: Python venv with pyinstaller>=6.17
#>

param(
    [ValidateSet("cuda", "xpu", "legacy")] [string]$Gpu = "cuda",
    [switch]$LegacyNvidia
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

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
$Meta         = Get-AppMeta
$AppName      = $Meta.AppName
$Version      = $Meta.Version
$PortableName = "${AppName}_${Version}$($GpuSuffix[$Gpu])_portable"
$OutputExe    = "build\${PortableName}.exe"

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

Write-Step "Installing the $Gpu GPU runtime (PyTorch $($TorchPin[$Gpu]) and DirectML)"

Install-GpuRuntime -Gpu $Gpu

Write-Host "   Python      : $(python --version)"      -ForegroundColor DarkGray
Write-Host "   PyInstaller : $(pyinstaller --version)" -ForegroundColor DarkGray

# ── Clean ─────────────────────────────────────────────────────────────────────

Write-Step "Cleaning previous build artifacts"

foreach ($path in @("build\pyinstaller", "${PortableName}.spec", $OutputExe)) {
    if (Test-Path $path) {
        Remove-Item $path -Recurse -Force
        Write-Host "   Removed $path" -ForegroundColor DarkGray
    }
}

New-Item -ItemType Directory -Path "build" -Force | Out-Null

# ── PyInstaller ───────────────────────────────────────────────────────────────

Write-Step "Running PyInstaller  (this may take several minutes)"

$PyArgs = Get-PyInstallerArgs -Name $PortableName -Mode onefile -DistPath "build"

pyinstaller @PyArgs

if ($LASTEXITCODE -ne 0) {
    Fail "PyInstaller failed (exit $LASTEXITCODE). Check output above."
}

if (-not (Test-Path $OutputExe)) {
    Fail "Expected portable executable not found: $OutputExe"
}

# ── Bundle self-test ──────────────────────────────────────────────────────────

Write-Step "Verifying the bundle can load every engine, library, and QML module"

if (-not (Test-Bundle $OutputExe)) {
    Fail "Bundle self-test failed - a module, DLL, or data file is missing from the build. See the report above."
}

# ── Done ──────────────────────────────────────────────────────────────────────

$Mb = [math]::Round((Get-Item $OutputExe).Length / 1MB, 1)
Write-Host ""
Write-Host "Build complete in $(Format-Elapsed ((Get-Date) - $BuildStart))." -ForegroundColor Green
Write-Host "Portable  : $OutputExe  ($Mb MB)" -ForegroundColor Green
