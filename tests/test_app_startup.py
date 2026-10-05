# test_app_startup.py - the splash must appear before the heavy engine libraries load

import json
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
# Libraries that take seconds to import; the boot thread loads them behind the splash.
_HEAVY = ("torch", "ctranslate2", "transformers", "faster_whisper", "argostranslate", "TTS", "ccgen.api.app")


def test_importing_the_entry_point_leaves_heavy_libraries_for_the_boot_thread():
    # A fresh interpreter, so modules other tests already imported can't hide a regression.
    probe = f"import json, sys; import app; print(json.dumps([m for m in {_HEAVY!r} if m in sys.modules]))"
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=_ROOT, capture_output=True, text=True, timeout=120, check=True,
    )
    assert json.loads(result.stdout.strip().splitlines()[-1]) == []
