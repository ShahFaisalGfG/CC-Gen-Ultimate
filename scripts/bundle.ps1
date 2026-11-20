# bundle.ps1 - PyInstaller arguments and the bundle self-test, shared by every build script and
# the release workflow so local and CI builds package and verify exactly the same files.
# Dot-source it from the project root: . "$PSScriptRoot\bundle.ps1"

$SelfTestTimeoutSec = 300
# GitHub refuses release files of 2 GiB or more, so a larger installer is split into parts and a
# larger portable archive into volumes, each at most this size.
$ReleaseFileLimit = 2000000000

# One installer can carry only one PyTorch build, and each GPU family needs its own, so every
# build targets one:
#   cuda   - NVIDIA, the main release. 2.8.0 on CUDA 12.8 carries code for sm_61 to sm_120:
#            GeForce GTX 10 series cards up to RTX 50.
#   legacy - older NVIDIA GPUs. 2.7.1 on CUDA 12.6 is the newest PyTorch that still carries
#            Maxwell code (sm_50 to sm_90): GTX 750 and 900 series and GeForce 940MX cards, up
#            to RTX 40, but not RTX 50. PyTorch 2.8 removed Maxwell from every CUDA build.
#   xpu    - Intel Arc and Core Ultra graphics.
# Speech recognition and voice cloning use PyTorch; Piper and Kokoro voices run through
# DirectML in every build, which reaches any DirectX 12 GPU (NVIDIA, AMD, or Intel).
# Every version stays within the torch<2.9 pin in requirements.txt.
#
# Each pin carries its local version label. That matters: pip treats any installed wheel of a
# version as satisfying "torch==<version>" and only swaps it for a label that sorts higher, so
# an NVIDIA build made after an Intel build would otherwise keep the +xpu wheel.
$TorchPin = @{
    cuda   = "2.8.0+cu128"
    legacy = "2.7.1+cu126"
    xpu    = "2.8.0+xpu"
}
$TorchIndex = @{
    cuda   = "https://download.pytorch.org/whl/cu128"
    legacy = "https://download.pytorch.org/whl/cu126"
    xpu    = "https://download.pytorch.org/whl/xpu"
}
# Appended to installer and portable file names; the main NVIDIA build keeps the plain names.
$GpuSuffix = @{
    cuda   = ""
    legacy = "_nvidia_legacy"
    xpu    = "_intel_gpu"
}

function Install-GpuRuntime {
    <#
    .SYNOPSIS
        Installs the PyTorch build for one GPU family and the DirectML build of ONNX Runtime.
    .DESCRIPTION
        Run after `pip install -r requirements.txt`. onnxruntime-directml ships the same
        `onnxruntime` module as the CPU package that faster-whisper and kokoro-onnx depend on, so
        the CPU package is removed first and DirectML installed without dependencies.
    #>
    param([Parameter(Mandatory)] [ValidateSet("cuda", "xpu", "legacy")] [string]$Gpu)

    $Pin = $TorchPin[$Gpu]
    python -m pip install --upgrade "torch==$Pin" "torchaudio==$Pin" --index-url $TorchIndex[$Gpu]
    if ($LASTEXITCODE -ne 0) { throw "Installing the $Gpu build of PyTorch failed (exit $LASTEXITCODE)" }
    python -m pip uninstall --yes onnxruntime
    python -m pip install --no-deps "onnxruntime-directml>=1.20"
    if ($LASTEXITCODE -ne 0) { throw "Installing onnxruntime-directml failed (exit $LASTEXITCODE)" }
}

function New-VersionFile {
    <#
    .SYNOPSIS
        Writes an exe's version details for PyInstaller and returns the file's path.
    .DESCRIPTION
        Every exe the build makes carries the app's name as its product name and the version from
        pyproject.toml (read_meta.py writes them), which code signing requires; the description
        names the exe in Task Manager and in its Properties (the app's name unless given). It needs
        nothing but this file, as the release workflow loads only bundle.ps1.
    #>
    param(
        [Parameter(Mandatory)] [string]$Exe,
        [string]$Description = ""
    )
    $root = Split-Path -Parent $PSScriptRoot
    $path = "$root\build\pyinstaller\$Exe.version.txt"
    $describe = if ($Description) { @("--description", $Description) } else { @() }
    python (Join-Path $PSScriptRoot "read_meta.py") --version-file $path --exe $Exe @describe
    if ($LASTEXITCODE -ne 0) { throw "Could not write the version details of $Exe.exe (exit $LASTEXITCODE)" }
    return $path
}

function Get-PyInstallerArgs {
    <#
    .SYNOPSIS
        Returns the PyInstaller arguments for a onedir (installer) or onefile (portable) build.
    #>
    param(
        [Parameter(Mandatory)] [string]$Name,
        [Parameter(Mandatory)] [ValidateSet("onedir", "onefile")] [string]$Mode,
        [Parameter(Mandatory)] [string]$DistPath
    )
    $root = Split-Path -Parent $PSScriptRoot
    return @(
        "--name",      $Name,
        "--windowed",
        "--$Mode",
        "--icon",      "$root\ccgen\assets\icons\CCGenUltimate.ico",
        "--version-file", (New-VersionFile -Exe $Name),
        # hooks\hook-PySide6.QtQml.py leaves out Qt WebEngine (about 200 MB the app never uses);
        # hooks\hook-TTS.py ships coqui-tts with its source files, which TorchScript reads.
        "--additional-hooks-dir", "$root\hooks",
        "--add-data",  "$root\ccgen\qml;ccgen\qml",
        "--add-data",  "$root\ccgen\assets;ccgen\assets",
        # The licence texts travel with the app, as the bundled GPL components require.
        "--add-data",  "$root\LICENSE;.",
        "--add-data",  "$root\THIRD_PARTY_NOTICES.md;.",
        # Non-code data files these packages read via relative paths at runtime -
        # PyInstaller only traces Python imports, so these need to be listed explicitly.
        "--collect-data", "indic_transliteration",
        "--collect-data", "faster_whisper",
        # Hy-MT2 translation: llama.cpp's DLLs, which llama_cpp loads by path.
        "--collect-all",  "llama_cpp",
        # Dubbing: Piper's and Kokoro's eSpeak libraries and phoneme data, and the dictionaries
        # XTTS reads Japanese, Chinese, and Korean text with (hooks\hook-TTS.py collects XTTS).
        "--collect-all",  "piper",
        "--collect-all",  "kokoro_onnx",
        "--collect-all",  "espeakng_loader",
        "--collect-all",  "fugashi",
        "--collect-all",  "mecab_ko",
        "--collect-data", "unidic_lite",
        "--collect-data", "mecab_ko_dic",
        "--collect-data", "cutlet",
        "--collect-data", "pypinyin",
        "--collect-data", "spacy_pkuseg",
        "--collect-data", "ko_speech_tools",
        # coqui-tts and transformers check these packages' installed versions at import time.
        "--copy-metadata", "coqui-tts",
        "--copy-metadata", "torch",
        "--copy-metadata", "torchaudio",
        "--distpath",  $DistPath,
        "--workpath",  "build\pyinstaller",
        "--specpath",  ".",
        "--noconfirm",
        "--clean",
        "$root\app.py"
    )
}

function Write-BuildInfo {
    <#
    .SYNOPSIS
        Writes build.ini (GPU edition and runtime fingerprint) next to the bundle's exe.
    .DESCRIPTION
        Run after ccgen_shell.dll is copied in, since the DLL is part of the runtime. The in-app
        updater reads build.ini to pick its edition's files and, when the runtime matches, the
        small patch installer. See scripts\runtime_id.py.
    #>
    param(
        [Parameter(Mandatory)] [string]$BundleDir,
        [Parameter(Mandatory)] [ValidateSet("cuda", "xpu", "legacy")] [string]$Gpu,
        [string]$ExeName = "CC-Gen-Ultimate.exe"
    )
    python "$PSScriptRoot\runtime_id.py" $BundleDir --edition $Gpu --exe $ExeName
    if ($LASTEXITCODE -ne 0) { throw "runtime_id.py failed (exit $LASTEXITCODE)" }
}

function Invoke-InstallerBuild {
    <#
    .SYNOPSIS
        Compiles an installer script and returns its files: the exe, then any -N.bin parts in order.
    .DESCRIPTION
        An installer at or above $ReleaseFileLimit is compiled again with Inno Setup's disk
        spanning (SplitInstaller), which leaves a small exe and data parts under the limit; the
        parts must sit next to the exe when it runs. The app metadata comes from pyproject.toml.
    #>
    param(
        [Parameter(Mandatory)] [string]$Iscc,
        [Parameter(Mandatory)] [string]$IssFile,
        [Parameter(Mandatory)] [psobject]$Meta,
        [string]$Suffix = "",
        [string]$OutputDir = "build\installer"
    )
    $OutputDir = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputDir)
    $defines = @(
        "/DMyAppName=$($Meta.AppName)",
        "/DMyAppVersion=$($Meta.Version)",
        "/DMyAppPublisher=$($Meta.Publisher)",
        "/DMyAppURL=$($Meta.Url)",
        "/DMyGpuSuffix=$Suffix",
        "/O$OutputDir"
    )
    $script = [IO.Path]::GetFileNameWithoutExtension($IssFile) -replace '^ccgenultimate_', ''
    $base = Join-Path $OutputDir "$($Meta.AppName)_$($Meta.Version)${Suffix}_$script"
    Get-ChildItem "$base-*.bin" -ErrorAction SilentlyContinue | Remove-Item -Force
    Write-Host "   Compiling : $IssFile" -ForegroundColor DarkGray
    & $Iscc @defines $IssFile | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed for '$IssFile' (exit $LASTEXITCODE)" }
    if ((Get-Item "$base.exe").Length -ge $ReleaseFileLimit) {
        Write-Host "   Over the release file limit; compiling again in parts" -ForegroundColor DarkGray
        & $Iscc @defines "/DSplitInstaller=1" $IssFile | Out-Host
        if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed for '$IssFile' in parts (exit $LASTEXITCODE)" }
    }
    $parts = Get-ChildItem "$base-*.bin" -ErrorAction SilentlyContinue |
        Sort-Object { [int]($_.BaseName -replace '^.*-(\d+)$', '$1') } | ForEach-Object { $_.FullName }
    return @((Resolve-Path "$base.exe").Path) + @($parts)
}

function Split-ReleaseFile {
    <#
    .SYNOPSIS
        Splits a file at or above $ReleaseFileLimit into <name>.001, .002, ... and returns the files.
    .DESCRIPTION
        A .7z split this way is a multi-volume archive: 7-Zip opens <name>.7z.001 with the rest
        beside it. A smaller file is returned as it is.
    #>
    param([Parameter(Mandatory)] [string]$Path)
    $file = Get-Item $Path
    if ($file.Length -lt $ReleaseFileLimit) { return @($file.FullName) }
    $volumes = @()
    $buffer = New-Object byte[] (16MB)
    $source = [IO.File]::OpenRead($file.FullName)
    try {
        $index = 0
        while ($source.Position -lt $source.Length) {
            $index++
            $volume = "{0}.{1:D3}" -f $file.FullName, $index
            $target = [IO.File]::Create($volume)
            try {
                $written = 0L
                while ($written -lt $ReleaseFileLimit) {
                    $read = $source.Read($buffer, 0, [math]::Min($buffer.Length, $ReleaseFileLimit - $written))
                    if ($read -le 0) { break }
                    $target.Write($buffer, 0, $read)
                    $written += $read
                }
            } finally {
                $target.Dispose()
            }
            $volumes += $volume
        }
    } finally {
        $source.Dispose()
    }
    Remove-Item $file.FullName -Force
    return $volumes
}

function Test-Bundle {
    <#
    .SYNOPSIS
        Runs a built exe with --self-test, prints its report, and returns $true when every check passed.
    .DESCRIPTION
        The exe is a --windowed build with no console, so the report is read from a file. A build
        that hangs (for example on a startup error dialog) is stopped after $SelfTestTimeoutSec.
    #>
    param([Parameter(Mandatory)] [string]$ExePath)

    $report = Join-Path ([IO.Path]::GetTempPath()) "ccgen_self_test_$PID.txt"
    Remove-Item $report -Force -ErrorAction SilentlyContinue
    $proc = Start-Process -FilePath $ExePath -ArgumentList "--self-test", "`"$report`"" -PassThru
    $null = $proc.Handle  # cache the handle so ExitCode is available after WaitForExit
    if (-not $proc.WaitForExit($SelfTestTimeoutSec * 1000)) {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        Write-Host "   Self-test did not finish within $SelfTestTimeoutSec s" -ForegroundColor Red
        return $false
    }
    if (Test-Path $report) {
        Get-Content $report | ForEach-Object { Write-Host "   $_" }
        Remove-Item $report -Force
    } else {
        Write-Host "   The self-test wrote no report (exit $($proc.ExitCode))" -ForegroundColor Red
    }
    return $proc.ExitCode -eq 0
}
