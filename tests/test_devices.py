# test_devices.py - unit tests for accelerator selection in ccgen.engines.devices

import sys
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from ccgen.engines import devices
from ccgen.engines.devices import (
    Accelerator,
    arch_supported,
    ct2_open,
    cuda_gpu,
    first_working,
    onnx_accelerators,
    torch_accelerators,
    torch_edition,
)

_GB = 1024 ** 3


def _fake_torch(cuda=False, hip=None, xpu=False, mps=False, capability=(8, 6), vram_gb=12,
                arches="sm_61 sm_70 sm_75 sm_80 sm_86 sm_90 sm_100 sm_120", cuda_version="12.8"):
    """Build a stand-in torch module reporting the given accelerators."""
    torch = MagicMock()
    torch.device.side_effect = lambda name: f"device:{name}"
    torch.cuda.is_available.return_value = cuda
    torch.cuda.get_device_properties.return_value = SimpleNamespace(
        name="Card", major=capability[0], minor=capability[1], total_memory=vram_gb * _GB,
    )
    torch._C._cuda_getArchFlags.return_value = arches
    torch.version = SimpleNamespace(hip=hip, cuda=cuda_version, xpu=None)
    torch.xpu.is_available.return_value = xpu
    torch.xpu.get_device_name.return_value = "Arc"
    torch.backends.mps.is_available.return_value = mps
    return torch


@pytest.fixture
def no_directml(monkeypatch):
    """Make torch_directml unimportable regardless of what this machine has installed."""
    monkeypatch.setitem(sys.modules, "torch_directml", None)


class TestTorchAccelerators:
    @pytest.mark.parametrize("kwargs, first", [
        ({"cuda": True}, "NVIDIA GPU (CUDA): Card"),
        ({"cuda": True, "hip": "6.2"}, "AMD GPU (ROCm): Card"),
        ({"xpu": True}, "Intel GPU (XPU): Arc"),
        ({"mps": True}, "Apple GPU (Metal)"),
    ])
    def test_gpu_comes_first_and_cpu_last(self, no_directml, kwargs, first):
        with patch.dict(sys.modules, {"torch": _fake_torch(**kwargs)}):
            found = torch_accelerators()
        assert [a.label for a in found] == [first, "CPU"]

    def test_cpu_only_machine(self, no_directml):
        with patch.dict(sys.modules, {"torch": _fake_torch()}):
            assert [a.label for a in torch_accelerators()] == ["CPU"]

    def test_cpu_preference_skips_gpus(self, no_directml):
        with patch.dict(sys.modules, {"torch": _fake_torch(cuda=True)}):
            assert [a.label for a in torch_accelerators("cpu")] == ["CPU"]

    def test_a_gpu_this_build_has_no_code_for_is_skipped(self, no_directml):
        with patch.dict(sys.modules, {"torch": _fake_torch(cuda=True, capability=(5, 0))}):
            assert [a.label for a in torch_accelerators()] == ["CPU"]

    def test_directml_is_used_when_installed(self):
        dml = MagicMock()
        dml.is_available.return_value = True
        dml.device_name.return_value = "Radeon"
        with patch.dict(sys.modules, {"torch": _fake_torch(), "torch_directml": dml}):
            labels = [a.label for a in torch_accelerators()]
        assert labels == ["GPU (DirectML): Radeon", "CPU"]


class TestCudaGpu:
    @pytest.mark.parametrize("capability, arches, supported", [
        ((5, 0), ["sm_61", "sm_86", "sm_120"], False),   # a GeForce 940MX on the standard build
        ((5, 0), ["sm_50", "sm_60", "sm_86"], True),     # ... and on the Legacy NVIDIA build
        ((8, 9), ["sm_50", "sm_86"], True),               # RTX 40 runs the 8.6 code
        ((12, 0), ["sm_50", "sm_86", "sm_90"], False),    # RTX 50 needs the standard build
        ((12, 0), ["sm_90", "compute_90"], True),         # ... unless the build carries PTX
        ((7, 5), [], True),                                # a build that doesn't say is tried
    ])
    def test_arch_supported(self, capability, arches, supported):
        assert arch_supported(capability, arches) is supported

    def test_old_gpu_on_the_standard_build_names_the_legacy_edition(self):
        with patch.dict(sys.modules, {"torch": _fake_torch(cuda=True, capability=(5, 0), vram_gb=2)}):
            gpu = cuda_gpu()
        assert gpu is not None and not gpu.usable and gpu.note == "needs the Legacy NVIDIA edition"

    def test_rtx_50_on_the_legacy_build_names_the_standard_edition(self):
        torch = _fake_torch(cuda=True, capability=(12, 0), arches="sm_50 sm_60 sm_86 sm_90", cuda_version="12.6")
        with patch.dict(sys.modules, {"torch": torch}):
            gpu = cuda_gpu()
        assert gpu is not None and gpu.note == "needs the standard edition"

    @pytest.mark.parametrize("capability, vram_gb, strong", [((8, 6), 12, True), ((8, 6), 6, False), ((5, 0), 2, False)])
    def test_only_a_new_large_gpu_skips_timing(self, capability, vram_gb, strong):
        arches = "sm_50 sm_86"
        with patch.dict(sys.modules, {"torch": _fake_torch(cuda=True, capability=capability, vram_gb=vram_gb, arches=arches)}):
            gpu = cuda_gpu()
        assert gpu is not None and gpu.strong is strong

    @pytest.mark.parametrize("cuda_version, edition", [("12.8", "cuda"), ("12.6", "legacy"), (None, "cpu")])
    def test_edition_follows_the_installed_build(self, cuda_version, edition):
        with patch.dict(sys.modules, {"torch": _fake_torch(cuda_version=cuda_version)}):
            assert torch_edition() == edition


class TestCt2Open:
    def _open(self, gpu_type, speeds, compute_type="auto", key="model"):
        opened = []

        def open_model(device, kind):
            opened.append((device, kind))
            return device

        def probe(device):
            time.sleep(speeds[device])

        with patch.object(devices, "ct2_gpu_compute_type", return_value=gpu_type):
            result = ct2_open(key, open_model, probe, compute_type)
        return result, opened

    def test_without_a_gpu_the_cpu_runs_int8(self):
        assert self._open(None, {})[0] == ("cpu", "cpu", "int8")

    def test_a_reduced_precision_gpu_is_used_without_timing(self):
        (_, device, kind), opened = self._open("float16", {"cuda": 0.0, "cpu": 0.0})
        assert (device, kind) == ("cuda", "float16") and opened == [("cuda", "float16")]

    def test_a_float32_only_gpu_loses_to_a_faster_cpu_and_is_remembered(self):
        devices._fastest_ct2.clear()
        (_, device, _), _ = self._open("float32", {"cuda": 0.03, "cpu": 0.0}, key="old-gpu")
        assert device == "cpu"
        (_, device, _), opened = self._open("float32", {"cuda": 0.0, "cpu": 0.0}, key="old-gpu")
        assert device == "cpu" and opened == [("cpu", "int8")]

    def test_an_explicit_compute_type_skips_timing(self):
        (_, device, kind), _ = self._open("float32", {"cuda": 0.03, "cpu": 0.0}, compute_type="float16")
        assert (device, kind) == ("cuda", "float16")


class TestOnnxAccelerators:
    def test_offers_directml_then_cpu(self):
        ort = MagicMock()
        ort.get_available_providers.return_value = ["DmlExecutionProvider", "CPUExecutionProvider"]
        with patch.dict(sys.modules, {"onnxruntime": ort}):
            found = onnx_accelerators()
        assert [a.handle for a in found] == [
            ["DmlExecutionProvider", "CPUExecutionProvider"], ["CPUExecutionProvider"],
        ]

    def test_prefers_cuda_over_directml(self):
        ort = MagicMock()
        ort.get_available_providers.return_value = [
            "CPUExecutionProvider", "DmlExecutionProvider", "CUDAExecutionProvider",
        ]
        with patch.dict(sys.modules, {"onnxruntime": ort}):
            labels = [a.label for a in onnx_accelerators()]
        assert labels == ["NVIDIA GPU (CUDA)", "GPU (DirectML)", "CPU"]

    def test_directml_sessions_disable_memory_patterns(self):
        ort = MagicMock()
        ort.get_available_providers.return_value = ["DmlExecutionProvider", "CPUExecutionProvider"]
        with patch.dict(sys.modules, {"onnxruntime": ort}):
            _, accelerator = devices.onnx_session("model.onnx")
        options = ort.InferenceSession.call_args.kwargs["sess_options"]
        assert options.enable_mem_pattern is False
        assert accelerator.label == "GPU (DirectML)"


class TestFirstWorking:
    def test_falls_back_to_cpu_when_the_gpu_fails(self):
        gpu, cpu = Accelerator("gpu", "GPU"), Accelerator("cpu", "CPU")

        def load(accelerator):
            if accelerator is gpu:
                raise RuntimeError("out of memory")
            return "model"

        assert first_working([gpu, cpu], load) == ("model", cpu)

    def test_cpu_failure_is_raised(self):
        with pytest.raises(ValueError, match="broken"):
            first_working([Accelerator("cpu", "CPU")], lambda a: (_ for _ in ()).throw(ValueError("broken")))


class TestFastestWorking:
    def test_keeps_the_quickest_device(self):
        gpu, cpu = Accelerator("gpu", "GPU"), Accelerator("cpu", "CPU")
        delays = {"gpu": 0.03, "cpu": 0.0}
        value, chosen = devices.fastest_working([gpu, cpu], lambda a: a.handle, lambda h: time.sleep(delays[h]))
        assert (value, chosen) == ("cpu", cpu)

    def test_skips_a_gpu_whose_probe_fails(self):
        gpu, cpu = Accelerator("gpu", "GPU"), Accelerator("cpu", "CPU")

        def probe(handle):
            if handle == "gpu":
                raise RuntimeError("unsupported layer")

        assert devices.fastest_working([gpu, cpu], lambda a: a.handle, probe)[1] is cpu

    def test_onnx_session_times_every_provider_when_probing(self, monkeypatch):
        monkeypatch.setattr(devices, "_fastest_onnx", {})
        ort = MagicMock()
        ort.get_available_providers.return_value = ["DmlExecutionProvider", "CPUExecutionProvider"]
        probed = []
        with patch.dict(sys.modules, {"onnxruntime": ort}):
            devices.onnx_session("model.onnx", probe=probed.append)
        assert len(probed) == 4  # a warm-up and a timed run on each provider

    def test_onnx_session_reuses_the_device_it_chose(self, monkeypatch):
        monkeypatch.setattr(devices, "_fastest_onnx", {})
        ort = MagicMock()
        ort.get_available_providers.return_value = ["DmlExecutionProvider", "CPUExecutionProvider"]
        probed = []
        with patch.dict(sys.modules, {"onnxruntime": ort}):
            first = devices.onnx_session("model.onnx", probe=probed.append)[1]
            ort.InferenceSession.reset_mock()
            again = devices.onnx_session("model.onnx", probe=probed.append)[1]
        assert again == first
        assert len(probed) == 4
        assert ort.InferenceSession.call_count == 1

    def test_remembered_gpu_still_falls_back_to_the_cpu(self, monkeypatch):
        monkeypatch.setattr(devices, "_fastest_onnx", {("model.onnx", devices.DEVICE_AUTO): "GPU (DirectML)"})
        ort = MagicMock()
        ort.get_available_providers.return_value = ["DmlExecutionProvider", "CPUExecutionProvider"]

        def open_session(path, sess_options, providers):
            if providers[0] == "DmlExecutionProvider":
                raise RuntimeError("device removed")
            return "cpu session"

        ort.InferenceSession.side_effect = open_session
        with patch.dict(sys.modules, {"onnxruntime": ort}):
            session, chosen = devices.onnx_session("model.onnx", probe=lambda s: None)
        assert (session, chosen.label) == ("cpu session", "CPU")


class TestCpuFallbackMidRun:
    def test_engine_moves_to_cpu_after_a_gpu_failure(self):
        from ccgen.config.voices import resolve_voice
        from ccgen.engines.speech.base import SpeechEngine

        class Flaky(SpeechEngine):
            def load(self, status_cb=None, progress_cb=None):
                self.device_label = "CPU" if self._device_preference == "cpu" else "GPU (DirectML)"

            def synthesize(self, text, speed=1.0, speaker=0):
                try:
                    if self.device_label != "CPU":
                        raise RuntimeError("driver error")
                    return "ok", 1
                except RuntimeError as e:
                    self._fall_back_to_cpu(e)
                    return self.synthesize(text, speed, speaker)

        engine = Flaky(resolve_voice("en", "piper")[0], "auto")
        engine.load()
        assert engine.synthesize("hi") == ("ok", 1)
        assert engine.device_label == "CPU"

    def test_failure_on_the_cpu_is_raised(self):
        from ccgen.config.voices import resolve_voice
        from ccgen.engines.speech.base import SpeechEngine

        class Broken(SpeechEngine):
            def load(self, status_cb=None, progress_cb=None):
                self.device_label = "CPU"

            def synthesize(self, text, speed=1.0, speaker=0):
                return "unused", 1

        engine = Broken(resolve_voice("en", "piper")[0], "cpu")
        engine.load()
        with pytest.raises(ValueError, match="bad text"):
            engine._fall_back_to_cpu(ValueError("bad text"))
