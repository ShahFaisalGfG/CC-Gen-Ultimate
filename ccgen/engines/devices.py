# devices.py - choose the accelerator torch and ONNX Runtime models run on
#
# Speech engines use two runtimes. PyTorch (XTTS) reaches NVIDIA through CUDA, AMD through ROCm
# builds (which also report as CUDA), Intel through XPU builds, Apple Silicon through MPS, and
# any DirectX 12 GPU on Windows through torch-directml when it is installed. ONNX Runtime (Piper
# and Kokoro) reaches NVIDIA through CUDA, AMD through ROCm, any DirectX 12 GPU through DirectML,
# and Apple Silicon through CoreML. Which of these exist depends on the installed build, so every
# choice is probed at run time and the CPU is always the last resort.
#
# Each edition of the app ships a PyTorch build compiled for a range of NVIDIA GPUs: the standard
# edition (CUDA 12.8) runs on GeForce GTX 10 series cards up to RTX 50, the Legacy NVIDIA edition
# (CUDA 12.6) on Maxwell cards such as the GTX 900 series and the 940MX up to RTX 40. A GPU outside
# the build's range is skipped with a note naming the edition that can use it. A GPU too weak to
# be sure of beating the CPU is timed against it, and the faster one is used.

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional, TypeVar

from ccgen.config.defaults import DubbingDefaults

_log = logging.getLogger(__name__)

DEVICE_AUTO = DubbingDefaults.DEVICE_AUTO
DEVICE_CPU = DubbingDefaults.DEVICE_CPU

_T = TypeVar("_T")

# Preference order for ONNX Runtime; whichever the installed onnxruntime build offers is used.
_ONNX_GPU_PROVIDERS = (
    ("CUDAExecutionProvider", "NVIDIA GPU (CUDA)"),
    ("ROCMExecutionProvider", "AMD GPU (ROCm)"),
    ("DmlExecutionProvider", "GPU (DirectML)"),
    ("CoreMLExecutionProvider", "Apple GPU (Core ML)"),
)
_ONNX_CPU = "CPUExecutionProvider"
# A CUDA GPU at least this new and this large runs every model faster than any CPU, so it is used
# without timing it against the CPU.
_STRONG_CAPABILITY = (7, 0)
_STRONG_VRAM_GB = 8.0
# CTranslate2 compute types on a GPU, fastest first; float32 is the slow last resort of old GPUs.
_CT2_GPU_TYPES = ("float16", "int8_float16", "int8", "float32")
# The device each timed CTranslate2 model ran fastest on, by model and setting.
_fastest_ct2: dict[tuple[str, str], str] = {}
_GB = 1024 ** 3
# The device each probed model ran fastest on, by model file and device setting. Hardware doesn't
# change while the app runs, so later jobs open the model there directly: opening a session can
# take seconds, and probing opens one per device.
_fastest_onnx: dict[tuple[str, str], str] = {}


@dataclass(frozen=True)
class Accelerator:
    """One device a model can run on: a runtime-specific handle and a label for the user."""

    handle: Any
    label: str

    @property
    def is_gpu(self) -> bool:
        """True for anything other than the CPU."""
        return self.label != "CPU"


@dataclass(frozen=True)
class CudaGpu:
    """The first CUDA GPU, and whether this edition's PyTorch build can run on it."""

    name: str
    capability: tuple[int, int]
    vram_gb: float
    usable: bool
    rocm: bool = False

    @property
    def strong(self) -> bool:
        """True when the GPU outruns any CPU, so it needs no timing against one."""
        return self.usable and (self.rocm or (self.capability >= _STRONG_CAPABILITY and self.vram_gb >= _STRONG_VRAM_GB))

    @property
    def note(self) -> str:
        """Why the GPU goes unused and which edition can use it ("" when it is used)."""
        if self.usable:
            return ""
        edition = "the standard edition" if self.capability >= (10, 0) else "the Legacy NVIDIA edition"
        return f"needs {edition}"


def cuda_gpu() -> Optional[CudaGpu]:
    """The first GPU PyTorch reaches through CUDA (NVIDIA, or AMD on ROCm builds), or None."""
    import torch

    if not torch.cuda.is_available():
        return None
    properties = torch.cuda.get_device_properties(0)
    capability = (properties.major, properties.minor)
    # ROCm builds report AMD GPUs through the CUDA API and set torch.version.hip.
    rocm = bool(getattr(getattr(torch, "version", None), "hip", None))
    usable = rocm or arch_supported(capability, built_architectures())
    return CudaGpu(properties.name, capability, properties.total_memory / _GB, usable, rocm)


def built_architectures() -> list[str]:
    """The GPU architectures this PyTorch build carries code for, e.g. ["sm_61", "sm_120"]
    (empty for CPU and Intel builds). Read from the build itself, so it works without a GPU."""
    import torch

    try:
        flags = getattr(torch._C, "_cuda_getArchFlags", None)
        names = str(flags() or "").split() if flags is not None else torch.cuda.get_arch_list()
        return [str(name) for name in names]
    except Exception:
        _log.debug("Reading the build's GPU architectures failed", exc_info=True)
        return []


def arch_supported(capability: tuple[int, int], architectures: list[str]) -> bool:
    """True when a build compiled for `architectures` (e.g. ["sm_61", "compute_90"]) runs on a
    GPU of compute `capability`: it has a binary for the same major version and an equal or
    lower minor one, or PTX code for an equal or lower version, which the driver compiles.
    An empty list means the build doesn't say, so the GPU is tried."""
    if not architectures:
        return True
    for arch in architectures:
        kind, _, number = arch.partition("_")
        if not number.isdigit():
            continue
        built = (int(number) // 10, int(number) % 10)
        if kind == "sm" and built[0] == capability[0] and built[1] <= capability[1]:
            return True
        if kind == "compute" and built <= capability:
            return True
    return False


def torch_edition() -> str:
    """Which edition's PyTorch build is installed: "cuda" (CUDA 12.8 or newer), "legacy" (an
    older CUDA, for Maxwell GPUs), "xpu" (Intel GPUs), or "cpu"."""
    import torch

    version = getattr(torch, "version", None)
    if getattr(version, "xpu", None):
        return "xpu"
    cuda = getattr(version, "cuda", None)
    if not cuda:
        return "cpu"
    major, _, minor = cuda.partition(".")
    return "cuda" if (int(major), int(minor or 0)) >= (12, 8) else "legacy"


EDITION_LABELS = {"cuda": "Standard", "legacy": "Legacy NVIDIA", "xpu": "Intel GPU", "cpu": "CPU only"}


def release_gpu_memory() -> None:
    """Hand back GPU memory a failed attempt left cached, so the next device starts clean."""
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        _log.debug("Releasing GPU memory failed", exc_info=True)


def torch_accelerators(preference: str = DEVICE_AUTO) -> list[Accelerator]:
    """Return torch devices to try in order, ending with the CPU."""
    import torch

    cpu = Accelerator(torch.device("cpu"), "CPU")
    if preference == DEVICE_CPU:
        return [cpu]
    found: list[Accelerator] = []
    try:
        gpu = cuda_gpu()
        if gpu is not None and gpu.usable:
            vendor = "AMD GPU (ROCm)" if gpu.rocm else "NVIDIA GPU (CUDA)"
            found.append(Accelerator(torch.device("cuda"), f"{vendor}: {gpu.name}"))
        elif gpu is not None:
            _log.info("%s %s, so it isn't used", gpu.name, gpu.note)
        xpu = getattr(torch, "xpu", None)
        if xpu is not None and xpu.is_available():
            found.append(Accelerator(torch.device("xpu"), f"Intel GPU (XPU): {xpu.get_device_name(0)}"))
        mps = getattr(torch.backends, "mps", None)
        if mps is not None and mps.is_available():
            found.append(Accelerator(torch.device("mps"), "Apple GPU (Metal)"))
    except Exception:
        _log.warning("Probing torch GPU support failed", exc_info=True)
    try:
        import torch_directml  # type: ignore[import-not-found]

        if torch_directml.is_available():
            found.append(Accelerator(torch_directml.device(), f"GPU (DirectML): {torch_directml.device_name(0)}"))
    except ImportError:
        pass
    except Exception:
        _log.warning("Probing DirectML for torch failed", exc_info=True)
    return found + [cpu]


def onnx_accelerators(preference: str = DEVICE_AUTO) -> list[Accelerator]:
    """Return ONNX Runtime provider lists to try in order, ending with the CPU alone."""
    import onnxruntime

    cpu = Accelerator([_ONNX_CPU], "CPU")
    if preference == DEVICE_CPU:
        return [cpu]
    available = set(onnxruntime.get_available_providers())
    found = [
        Accelerator([provider, _ONNX_CPU], label)
        for provider, label in _ONNX_GPU_PROVIDERS
        if provider in available
    ]
    return found + [cpu]


def onnx_session(
    model_path: str,
    preference: str = DEVICE_AUTO,
    probe: Optional[Callable[[Any], None]] = None,
) -> tuple[Any, Accelerator]:
    """Open an ONNX Runtime session on the fastest device that can run the model.

    With a `probe` (a short sample run), every candidate is timed and the quickest kept: small
    speech models often run slower on an integrated GPU than on the CPU, and a GPU provider can
    accept a model yet fail on its first run (DirectML on older Intel graphics rejects some of
    Kokoro's layers). Without one, the first device that opens the model is used. A probed
    choice is remembered for the rest of the session, with the CPU still behind a GPU choice.
    """
    import onnxruntime

    def open_session(accelerator: Accelerator) -> Any:
        options = onnxruntime.SessionOptions()
        if "DmlExecutionProvider" in accelerator.handle:
            # DirectML does not support memory patterns or parallel execution.
            options.enable_mem_pattern = False
            options.execution_mode = onnxruntime.ExecutionMode.ORT_SEQUENTIAL
        return onnxruntime.InferenceSession(model_path, sess_options=options, providers=accelerator.handle)

    accelerators = onnx_accelerators(preference)
    key = (model_path, preference)
    known = [a for a in accelerators if a.label == _fastest_onnx.get(key)]
    if known:
        return first_working(known + accelerators[-1:] if known[0].is_gpu else known, open_session)
    if probe is None or len(accelerators) == 1:
        return first_working(accelerators, open_session)
    session, accelerator = fastest_working(accelerators, open_session, probe)
    _fastest_onnx[key] = accelerator.label
    return session, accelerator


def fastest_working(
    accelerators: list[Accelerator],
    load: Callable[[Accelerator], _T],
    probe: Callable[[_T], object],
) -> tuple[_T, Accelerator]:
    """Load on every accelerator, time `probe` on each, and keep the fastest that works.

    The probe runs twice per device and only the second run is timed, so one-time warm-up
    (graph compilation, GPU memory allocation) doesn't count against a device.
    """
    timed: list[tuple[float, _T, Accelerator]] = []
    for accelerator in accelerators:
        try:
            value = load(accelerator)
            probe(value)
            start = time.perf_counter()
            probe(value)
            timed.append((time.perf_counter() - start, value, accelerator))
        except Exception as e:
            if not accelerator.is_gpu:
                raise
            _log.warning("%s failed, trying the next device: %r", accelerator.label, e)
    seconds, value, accelerator = min(timed, key=lambda entry: entry[0])
    _log.info(
        "Running on %s (%s)", accelerator.label,
        ", ".join(f"{a.label}: {s * 1000:.0f} ms" for s, _, a in timed),
    )
    return value, accelerator


def ct2_gpu_compute_type() -> Optional[str]:
    """The fastest compute type CTranslate2 offers on the first CUDA GPU, or None without one
    (older GPUs offer only float32)."""
    import ctranslate2

    try:
        if ctranslate2.get_cuda_device_count() <= 0:
            return None
        supported = ctranslate2.get_supported_compute_types("cuda")
    except Exception:
        _log.debug("CTranslate2 CUDA query failed", exc_info=True)
        return None
    return next((kind for kind in _CT2_GPU_TYPES if kind in supported), None)


def ct2_open(
    key: str,
    open_model: Callable[[str, str], _T],
    probe: Callable[[_T], object],
    compute_type: str = "auto",
) -> tuple[_T, str, str]:
    """Open a CTranslate2 model (`open_model(device, compute_type)`) on the GPU or the CPU.

    The GPU runs its fastest type, or `compute_type` when one is given; a GPU that fails falls
    back to the CPU in 8-bit. A GPU that offers only float32 is timed against the CPU once per
    session, since an old GPU in float32 can lose to it. Returns the model, its device, and its
    compute type.
    """
    gpu_type = ct2_gpu_compute_type()
    cpu = Accelerator(("cpu", "int8"), "CPU")
    if gpu_type is None:
        return open_model("cpu", "int8"), "cpu", "int8"
    if compute_type != "auto":
        gpu_type = compute_type
    gpu = Accelerator(("cuda", gpu_type), "GPU")
    known = _fastest_ct2.get((key, gpu_type))
    if gpu_type != "float32" or compute_type != "auto" or known == "GPU":
        model, chosen = first_working([gpu, cpu], lambda a: open_model(*a.handle))
    elif known == "CPU":
        model, chosen = open_model("cpu", "int8"), cpu
    else:
        model, chosen = fastest_working([gpu, cpu], lambda a: open_model(*a.handle), probe)
        _fastest_ct2[(key, gpu_type)] = chosen.label
    device, compute_type = chosen.handle
    return model, device, compute_type


def first_working(
    accelerators: list[Accelerator],
    load: Callable[[Accelerator], _T],
) -> tuple[_T, Accelerator]:
    """Load on each accelerator in turn and return the first that works.

    A GPU whose driver or memory can't take the model falls back to the next device, and
    finally the CPU, so a broken accelerator slows a job down instead of failing it.
    """
    error: Optional[Exception] = None
    for accelerator in accelerators:
        try:
            value = load(accelerator)
            _log.info("Running on %s", accelerator.label)
            return value, accelerator
        except Exception as e:
            if not accelerator.is_gpu:
                raise
            _log.warning("%s failed, trying the next device: %r", accelerator.label, e)
            error = e
    raise RuntimeError(f"No device could load the model: {error}")


def describe_accelerators() -> dict[str, list[str]]:
    """Labels of every device each runtime can use, for the self-test and logs."""
    result: dict[str, list[str]] = {}
    for runtime, probe in (("torch", torch_accelerators), ("onnxruntime", onnx_accelerators)):
        try:
            result[runtime] = [a.label for a in probe()]
        except ImportError as e:
            result[runtime] = [f"unavailable ({e})"]
    return result
