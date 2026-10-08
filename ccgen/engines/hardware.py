# hardware.py - what this PC has for running models: GPU memory, RAM, and CPU cores
#
# The recommended performance profile is chosen from these (see ccgen.config.profiles). Only a
# GPU that PyTorch and CTranslate2 can use for every model counts towards the GPU memory: NVIDIA
# (CUDA) or AMD (ROCm) through PyTorch, or Intel through PyTorch's XPU backend. DirectML devices
# speed up the ONNX voices but not the large models, so they are named without counting, and so
# is an NVIDIA GPU this edition's PyTorch build can't run, with the edition that can.
# Detection imports torch, so callers run it off the UI thread.

import logging
import os
from dataclasses import dataclass

import psutil

from ccgen.config.profiles import recommend
from ccgen.engines.devices import cuda_gpu

_log = logging.getLogger(__name__)

_GB = 1024 ** 3


@dataclass(frozen=True)
class HardwareProfile:
    """The parts of a PC that decide which models it runs well."""

    gpu: str
    vram_gb: float
    ram_gb: float
    physical_cores: int
    # Why the GPU goes unused, e.g. "needs the Legacy NVIDIA edition" ("" when it is used).
    gpu_note: str = ""

    @property
    def recommended(self) -> str:
        """The performance profile that suits this hardware."""
        return recommend(self.vram_gb, self.ram_gb, self.physical_cores)

    @property
    def fingerprint(self) -> str:
        """Changes when the GPU, its memory, the RAM, or the core count changes."""
        return f"{self.gpu}|{round(self.vram_gb)}|{round(self.ram_gb)}|{self.physical_cores}"

    @property
    def summary(self) -> str:
        """One line for the Performance page, e.g. "NVIDIA RTX 4070 (12 GB), 32 GB RAM, 8 cores"."""
        if self.gpu_note:
            gpu = f"{self.gpu} ({self.gpu_note})"
        else:
            gpu = f"{self.gpu} ({self.vram_gb:.0f} GB)" if self.vram_gb else (self.gpu or "No supported GPU")
        return f"{gpu}, {self.ram_gb:.0f} GB RAM, {self.physical_cores} CPU cores"


def detect() -> HardwareProfile:
    """Measure this PC. Never raises: an undetectable GPU counts as none."""
    gpu, vram, note = _gpu()
    cores = psutil.cpu_count(logical=False) or os.cpu_count() or 1
    ram = psutil.virtual_memory().total / _GB
    profile = HardwareProfile(gpu=gpu, vram_gb=vram, ram_gb=ram, physical_cores=cores, gpu_note=note)
    _log.info("Hardware: %s -> %s profile", profile.summary, profile.recommended)
    return profile


def _gpu() -> tuple[str, float, str]:
    """The first GPU PyTorch can run models on and its memory in GB, or a GPU it can't run (or a
    DirectML name) with 0 GB, and the note saying why it goes unused."""
    try:
        import torch

        gpu = cuda_gpu()
        if gpu is not None:
            return gpu.name, gpu.vram_gb if gpu.usable else 0.0, gpu.note
        xpu = getattr(torch, "xpu", None)
        if xpu is not None and xpu.is_available():
            properties = xpu.get_device_properties(0)
            return properties.name, properties.total_memory / _GB, ""
    except Exception as e:  # a broken driver or runtime must not stop the app
        _log.warning("GPU detection failed: %r", e)
    return _directml_name(), 0.0, ""


def _directml_name() -> str:
    """Name of a DirectML GPU, when the ONNX voices can use one."""
    try:
        import onnxruntime

        if "DmlExecutionProvider" in onnxruntime.get_available_providers():
            return "DirectML GPU"
    except Exception as e:
        _log.debug("ONNX Runtime provider check failed: %r", e)
    return ""
