# bundle.ps1 - PyInstaller arguments and the bundle self-test, shared by every build script and
# the release workflow so local and CI builds package and verify exactly the same files.
# Dot-source it from the project root: . "$PSScriptRoot\bundle.ps1"

$SelfTestTimeoutSec = 300

# One installer can carry only one PyTorch build, and each GPU vendor needs its own, so every
# build targets one: "cuda" (NVIDIA, the main release) or "xpu" (Intel Arc and Core Ultra).
# Speech recognition and voice cloning use PyTorch; Piper and Kokoro voices run through
# DirectML in both builds, which reaches any DirectX 12 GPU (NVIDIA, AMD, or Intel).
# The version matches the torch<2.9 pin in requirements.txt.
$TorchVersion = "2.8.0"
$TorchIndex = @{
    cuda = "https://download.pytorch.org/whl/cu128"
    xpu  = "https://download.pytorch.org/whl/xpu"
}
# Local version label of each index's wheels. Pinning it matters: pip treats any installed
# 2.8.0 wheel as satisfying "torch==2.8.0" and only swaps it for a label that sorts higher, so
# an NVIDIA build made after an Intel build would otherwise keep the +xpu wheel.
$TorchLocal = @{
    cuda = "cu128"
    xpu  = "xpu"
}
# Appended to installer and portable file names; the NVIDIA build keeps the plain names.
$GpuSuffix = @{
    cuda = ""
    xpu  = "_intel_gpu"
}

function Install-GpuRuntime {
    <#
    .SYNOPSIS
        Installs the PyTorch build for one GPU vendor and the DirectML build of ONNX Runtime.
    .DESCRIPTION
        Run after `pip install -r requirements.txt`. onnxruntime-directml ships the same
        `onnxruntime` module as the CPU package that faster-whisper and kokoro-onnx depend on, so
        the CPU package is removed first and DirectML installed without dependencies.
    #>
    param([Parameter(Mandatory)] [ValidateSet("cuda", "xpu")] [string]$Gpu)

    $Pin = "$TorchVersion+$($TorchLocal[$Gpu])"
    python -m pip install --upgrade "torch==$Pin" "torchaudio==$Pin" --index-url $TorchIndex[$Gpu]
    if ($LASTEXITCODE -ne 0) { throw "Installing the $Gpu build of PyTorch failed (exit $LASTEXITCODE)" }
    python -m pip uninstall --yes onnxruntime
    python -m pip install --no-deps "onnxruntime-directml>=1.20"
    if ($LASTEXITCODE -ne 0) { throw "Installing onnxruntime-directml failed (exit $LASTEXITCODE)" }
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
