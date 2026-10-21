# common.py - the job loop shared by the candidate engine workers
#
# A worker runs in the candidate's own Python environment, so it imports nothing from the app.
# It reads jobs.json (id, language, text, ref_audio, ref_text, out), writes each clip to `out`,
# and records the seconds each one took in jobs.json.done.

import json
import os
import sys
import time
from typing import Callable

import numpy as np
import soundfile

LANGUAGE_NAMES = {
    "ar": "Arabic", "de": "German", "en": "English", "es": "Spanish", "fr": "French", "hi": "Hindi",
    "ja": "Japanese", "ko": "Korean", "pt": "Portuguese", "ru": "Russian", "tr": "Turkish", "ur": "Urdu",
    "zh": "Chinese",
}

Speak = Callable[[dict], tuple[np.ndarray, int]]


def run_jobs(speak: Speak) -> None:
    """Synthesize every job in the file named on the command line."""
    jobs_path = sys.argv[1]
    with open(jobs_path, encoding="utf-8") as fh:
        jobs = json.load(fh)
    done = []
    for job in jobs:
        started = time.perf_counter()
        audio, rate = speak(job)
        seconds = time.perf_counter() - started
        os.makedirs(os.path.dirname(job["out"]), exist_ok=True)
        soundfile.write(job["out"], np.asarray(audio, dtype=np.float32).ravel(), rate, subtype="PCM_16")
        done.append({"id": job["id"], "seconds": seconds})
        print(f"{job['id']}: {seconds:.1f} s", flush=True)
    with open(jobs_path + ".done", "w", encoding="utf-8") as fh:
        json.dump(done, fh)
