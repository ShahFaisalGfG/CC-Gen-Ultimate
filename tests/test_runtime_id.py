# test_runtime_id.py - the runtime fingerprint that decides between a patch and the full installer

import configparser
import importlib.util
import os

import pytest

_SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "runtime_id.py")
_spec = importlib.util.spec_from_file_location("runtime_id", _SCRIPT)
assert _spec is not None and _spec.loader is not None
runtime_id = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runtime_id)

EXE = "CC-Gen-Ultimate.exe"


@pytest.fixture
def bundle(tmp_path):
    """A small onedir bundle: the exe, app files, and a few runtime files."""
    files = {
        EXE: b"exe with every python module",
        "ccgen_shell.dll": b"shell",
        "_internal/ccgen/qml/main.qml": b"qml",
        "_internal/ccgen/assets/icon.png": b"png",
        "_internal/LICENSE": b"licence",
        "_internal/THIRD_PARTY_NOTICES.md": b"notices",
        "_internal/torch/lib/torch_cuda.dll": b"cuda",
        "_internal/base_library.zip": b"stdlib",
    }
    for relative, body in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    return tmp_path


def test_the_runtime_layer_leaves_out_the_app_layer(bundle):
    assert runtime_id.runtime_files(str(bundle), EXE) == [
        "_internal/base_library.zip", "_internal/torch/lib/torch_cuda.dll", "ccgen_shell.dll"]


def test_app_changes_keep_the_fingerprint(bundle):
    """A release that changes only the app can be installed as a patch."""
    before = runtime_id.runtime_id(str(bundle), EXE)
    (bundle / EXE).write_bytes(b"new exe")
    (bundle / "_internal/ccgen/qml/main.qml").write_bytes(b"new qml")
    (bundle / "_internal/THIRD_PARTY_NOTICES.md").write_bytes(b"new notices")
    runtime_id.write_build_info(str(bundle), "cuda", before)
    assert runtime_id.runtime_id(str(bundle), EXE) == before


@pytest.mark.parametrize("change", ["_internal/torch/lib/torch_cuda.dll", "ccgen_shell.dll", "_internal/new_lib.dll"])
def test_runtime_changes_change_the_fingerprint(bundle, change):
    """A changed, added, or renamed runtime file needs the full installer."""
    before = runtime_id.runtime_id(str(bundle), EXE)
    (bundle / change).write_bytes(b"changed")
    assert runtime_id.runtime_id(str(bundle), EXE) != before


def test_build_info_is_read_back_as_the_app_reads_it(bundle):
    assert runtime_id.main([str(bundle), "--edition", "legacy", "--exe", EXE]) == 0
    parser = configparser.ConfigParser()
    parser.read(bundle / "build.ini", encoding="utf-8")
    assert parser.get("build", "edition") == "legacy"
    assert parser.get("build", "runtime_id") == runtime_id.runtime_id(str(bundle), EXE)


def test_a_folder_without_the_exe_is_refused(tmp_path):
    assert runtime_id.main([str(tmp_path), "--edition", "cuda"]) == 1
