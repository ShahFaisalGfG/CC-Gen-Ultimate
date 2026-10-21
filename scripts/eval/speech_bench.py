# speech_bench.py - score dubbing voices on native FLEURS speakers in every supported language
#
#   python scripts/eval/speech_bench.py --engines native,xtts,piper --languages ur,hi --count 12
#
# For each language, FLEURS recording i is the voice to clone and the engine speaks the text of
# recording i+1, so every engine reads the same sentences in the same voices. "native" scores
# the recordings themselves: the level a dub should come close to. Shipped engines (xtts,
# kokoro, piper) run in this process exactly as the app runs them; candidate engines run in
# their own Python environment through a worker script in workers/ (see README.md).
# Results and the synthesized clips are cached per engine and language.

import argparse
import json
import os
import subprocess
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import data  # noqa: E402
from metrics import resample  # noqa: E402
from scoring import ClipScore, Scorer, Timer, clip_rows, summary  # noqa: E402

# The app's own engines: benchmark name -> (voice engine, fast mode). "omnivoice_app" is the
# shipped OmniVoice in the fast mode the Balanced and Light profiles use; it builds its voice
# prompt as a dub does, transcribing the reference itself.
SHIPPED = {
    "xtts": ("xtts", False),
    "kokoro": ("kokoro", False),
    "piper": ("piper", False),
    "omnivoice_app": ("omnivoice", True),
}
# Candidate engines: worker script, the environment variable naming the Python that runs it
# (default: this interpreter), and settings passed to the worker. OmniVoice is also scored with
# fewer denoising steps, which trades some quality for speed on a CPU, and as an INT8 ONNX graph.
WORKERS = {
    "omnivoice": ("omnivoice_worker.py", "EVAL_OMNIVOICE_PYTHON", {}),
    "omnivoice16": ("omnivoice_worker.py", "EVAL_OMNIVOICE_PYTHON", {"OMNIVOICE_STEPS": "16"}),
    "omnivoice8": ("omnivoice_worker.py", "EVAL_OMNIVOICE_PYTHON", {"OMNIVOICE_STEPS": "8"}),
    "omnivoice16_onnx": ("omnivoice_worker.py", "EVAL_OMNIVOICE_PYTHON",
                         {"OMNIVOICE_STEPS": "16", "OMNIVOICE_BACKEND": "onnx"}),
    "omnivoice8_onnx": ("omnivoice_worker.py", "EVAL_OMNIVOICE_PYTHON",
                        {"OMNIVOICE_STEPS": "8", "OMNIVOICE_BACKEND": "onnx"}),
    "qwen3tts": ("qwen3tts_worker.py", "EVAL_QWEN3TTS_PYTHON", {}),
    "xtts_urdu": ("xtts_urdu_worker.py", "EVAL_XTTS_URDU_PYTHON", {}),
}
class Unsupported(Exception):
    """The engine doesn't speak the language. Other errors, such as a failed download, are
    reported and retried on the next run instead of being saved as a result."""


def jobs_for(language: str, count: int) -> list[dict]:
    """Voice i reads the text of recording i+1, so text and voice never come from the same clip.

    The whole recording is the reference, so its transcript matches what is heard: given a cut
    clip with the full transcript, a cloning model says the missing words before the line.
    """
    utterances = data.fleurs(language, count)
    jobs = []
    for i, voice in enumerate(utterances):
        line = utterances[(i + 1) % len(utterances)]
        jobs.append({"id": i, "language": language, "text": line.text, "native_seconds": line.seconds,
                     "ref_key": voice.key, "ref_text": voice.text,
                     "ref_audio": voice.audio, "ref_rate": voice.rate})
    return jobs


def synthesize_shipped(engine_name: str, jobs: list[dict]) -> list[tuple[np.ndarray, int, float]]:
    """Speak every job with a shipped engine, as a dub would (cloned or stock voice)."""
    from ccgen.config.voices import resolve_voice
    from ccgen.engines.speech import CloningEngine, create_engine
    from ccgen.engines.speech.base import REFERENCE_RATE

    language = jobs[0]["language"]
    mode, fast = SHIPPED[engine_name]
    try:
        voice, warning = resolve_voice(language, mode)
    except ValueError as e:
        raise Unsupported(str(e)) from e
    if warning:
        raise Unsupported(warning)
    engine = create_engine(voice, "cpu", fast=fast)
    engine.load()
    outputs = []
    for job in jobs:
        speaker = 0
        if isinstance(engine, CloningEngine):
            engine.set_speakers({0: [resample(job["ref_audio"], job["ref_rate"], REFERENCE_RATE)]})
        with Timer() as timer:
            audio, rate = engine.synthesize(job["text"], 1.0, speaker)
        outputs.append((np.asarray(audio, dtype=np.float32), rate, timer.seconds))
    return outputs


def synthesize_worker(engine_name: str, jobs: list[dict], out_dir: str) -> list[tuple[np.ndarray, int, float]]:
    """Speak every job in a candidate engine's own environment."""
    script, variable, settings = WORKERS[engine_name]
    python = os.environ.get(variable) or sys.executable
    with tempfile.TemporaryDirectory() as scratch:
        listed = []
        for job in jobs:
            ref_path = os.path.join(scratch, f"ref_{job['id']}.wav")
            data.write_wav(ref_path, job["ref_audio"], job["ref_rate"])
            listed.append({"id": job["id"], "language": job["language"], "text": job["text"],
                           "ref_audio": ref_path, "ref_text": job["ref_text"],
                           "out": os.path.join(out_dir, f"{job['id']:03d}.wav")})
        jobs_path = os.path.join(scratch, "jobs.json")
        with open(jobs_path, "w", encoding="utf-8") as fh:
            json.dump(listed, fh, ensure_ascii=False)
        worker = os.path.join(os.path.dirname(os.path.abspath(__file__)), "workers", script)
        subprocess.run([python, worker, jobs_path], check=True, env={**os.environ, **settings})
        with open(jobs_path + ".done", encoding="utf-8") as fh:
            timings = {row["id"]: row["seconds"] for row in json.load(fh)}
    outputs = []
    for row in listed:
        audio, rate = data.read_audio(row["out"])
        outputs.append((audio, rate, timings[row["id"]]))
    return outputs


def native_scores(language: str, count: int, scorer: Scorer) -> tuple[list[ClipScore], float]:
    """The native recordings' own scores, and their typical seconds per character."""
    scores = [scorer.score(u.audio, u.rate, u.text, language) for u in data.fleurs(language, count)]
    return scores, float(np.median([s.seconds_per_char for s in scores]))


def native_rate(language: str, count: int, scorer: Scorer) -> float:
    """Native speakers' seconds per character, from the saved "native" result when there is one."""
    path = os.path.join(data.cache_root(), "results", "speech", "native", f"{language}-{count}.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return float(json.load(fh)["native_seconds_per_char"])
    return native_scores(language, count, scorer)[1]


def run(engine_name: str, language: str, count: int, scorer: Scorer) -> dict:
    """Synthesize and score one engine in one language."""
    out_dir = os.path.join(data.cache_root(), "results", "speech", engine_name, language)
    os.makedirs(out_dir, exist_ok=True)
    if engine_name == "native":
        natives, per_char = native_scores(language, count, scorer)
        return {"engine": "native", "language": language, "summary": summary(natives, per_char),
                "clips": clip_rows(natives), "native_seconds_per_char": per_char}
    per_char = native_rate(language, count, scorer)
    jobs = jobs_for(language, count)
    if engine_name in SHIPPED:
        outputs = synthesize_shipped(engine_name, jobs)
        for job, (audio, rate, _) in zip(jobs, outputs):
            data.write_wav(os.path.join(out_dir, f"{job['id']:03d}.wav"), audio, rate)
    else:
        outputs = synthesize_worker(engine_name, jobs, out_dir)
    scores = []
    for job, (audio, rate, seconds) in zip(jobs, outputs):
        reference = scorer.speakers.vector(job["ref_audio"], job["ref_rate"])
        scores.append(scorer.score(audio, rate, job["text"], language, reference, seconds))
    audio_seconds = sum(s.seconds for s in scores)
    return {"engine": engine_name, "language": language, "summary": summary(scores, per_char),
            "clips": clip_rows(scores),
            "native_seconds_per_char": per_char,
            "real_time_factor": sum(s.synthesis_seconds or 0 for s in scores) / max(audio_seconds, 1e-6)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engines", default="native,xtts,kokoro,piper")
    parser.add_argument("--languages", default=",".join(data.LANGUAGES))
    parser.add_argument("--count", type=int, default=12)
    parser.add_argument("--rerun", action="store_true")
    args = parser.parse_args()
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

    scorer = Scorer()
    for engine_name in args.engines.split(","):
        for language in args.languages.split(","):
            folder = os.path.join(data.cache_root(), "results", "speech", engine_name)
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, f"{language}-{args.count}.json")
            if os.path.exists(path) and not args.rerun:
                continue
            try:
                result = run(engine_name, language, args.count, scorer)
            except Unsupported as e:
                result = {"engine": engine_name, "language": language, "unsupported": str(e)}
            except Exception as e:  # a download, worker, or model failure: report it, keep going
                print(f"{engine_name:>10} {language}: FAILED {e!r}", flush=True)
                continue
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(result, fh, ensure_ascii=False, indent=1)
            if "unsupported" in result:
                print(f"{engine_name:>10} {language}: unsupported ({result['unsupported']})", flush=True)
                continue
            s = result["summary"]
            sim = s["speaker_similarity"]["median"] if s.get("speaker_similarity") else float("nan")
            print(f"{engine_name:>10} {language}: mean CER {s['cer']['mean']:.3f}  failed {s['failed_rate']:.0%}  "
                  f"babble {s['babble_rate']:.0%}  rate {s['rate_vs_native']:.2f}x  sim {sim:.3f}  "
                  f"RTF {result.get('real_time_factor', 0):.2f}", flush=True)


if __name__ == "__main__":
    main()
