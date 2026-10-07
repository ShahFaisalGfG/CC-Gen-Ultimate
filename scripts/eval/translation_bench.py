# translation_bench.py - score translation engines on FLORES-200 for every supported direction
#
#   python scripts/eval/translation_bench.py --engines opus_mt,nllb --count 40
#
# Each engine translates the first --count devtest sentences of each direction. The report
# gives chrF against the professional reference, the app's meaning score, the output/reference
# length ratio, and seconds per sentence. Results are cached per engine and direction, so an
# interrupted run picks up where it stopped. Candidate engines that the app does not ship yet
# live in candidates.py.

import argparse
import json
import os
import sys
import time
from typing import Callable

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import data  # noqa: E402
from metrics import chrf, summarize  # noqa: E402

from ccgen.engines.translation import MeaningCheck, create_engine  # noqa: E402

# Every direction to or from English, plus pairs that OPUS-MT has to pivot through English.
PIVOT_PAIRS = (("ur", "fr"), ("zh", "ur"), ("ja", "de"), ("ar", "hi"), ("ru", "es"), ("ko", "tr"))
DEFAULT_DIRECTIONS = tuple(
    [("en", lang) for lang in data.LANGUAGES if lang != "en"]
    + [(lang, "en") for lang in data.LANGUAGES if lang != "en"]
    + list(PIVOT_PAIRS)
)
SHIPPED_ENGINES = ("opus_mt", "nllb", "madlad", "hymt2", "argos")

Translator = Callable[[list[str]], list[str]]


def shipped_translator(engine: str, source: str, target: str, meaning: MeaningCheck) -> Translator:
    """An engine exactly as the app runs it (meaning check on)."""
    instance = create_engine(engine, source, target, meaning)
    instance.ensure_model()

    def run(texts: list[str]) -> list[str]:
        segments = [{"id": i, "start": float(i), "end": float(i) + 1.0, "text": t} for i, t in enumerate(texts)]
        return [s["translated"] for s in instance.translate_segments(segments)]  # type: ignore[arg-type]
    return run


def make_translator(engine: str, source: str, target: str, meaning: MeaningCheck) -> Translator:
    """A translator for a shipped or candidate engine; raises ValueError for unsupported pairs."""
    if engine in SHIPPED_ENGINES:
        return shipped_translator(engine, source, target, meaning)
    import candidates

    return candidates.translator(engine, source, target, meaning)


def run_direction(engine: str, source: str, target: str, count: int, meaning: MeaningCheck) -> dict:
    """Translate one direction's sentences and score them."""
    sources = data.flores(source, count)
    references = data.flores(target, count)
    translate = make_translator(engine, source, target, meaning)
    started = time.perf_counter()
    outputs = translate(sources)
    seconds = time.perf_counter() - started
    meaning_scores = meaning.scores(sources, outputs, target)
    ratios = [len(out) / max(1, len(ref)) for out, ref in zip(outputs, references)]
    return {
        "engine": engine, "source": source, "target": target, "count": len(sources),
        "chrf": chrf(outputs, references),
        "meaning": summarize(meaning_scores),
        "length_ratio": summarize(ratios),
        "seconds_per_sentence": seconds / max(1, len(sources)),
        "samples": [
            {"source": s, "output": o, "reference": r, "meaning": m}
            for s, o, r, m in list(zip(sources, outputs, references, meaning_scores))[:5]
        ],
    }


def result_path(engine: str, source: str, target: str, count: int) -> str:
    """Cache file for one engine and direction."""
    folder = os.path.join(data.cache_root(), "results", "translation", engine)
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f"{source}-{target}-{count}.json")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engines", default="opus_mt,nllb,madlad")
    parser.add_argument("--directions", default="", help="Comma-separated pairs like en-ur,ja-en (default: all)")
    parser.add_argument("--count", type=int, default=40)
    parser.add_argument("--rerun", action="store_true", help="Ignore cached results")
    args = parser.parse_args()
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

    directions = [tuple(d.split("-")) for d in args.directions.split(",") if d] or list(DEFAULT_DIRECTIONS)
    meaning = MeaningCheck()
    meaning.ensure()
    for engine in args.engines.split(","):
        for source, target in directions:
            path = result_path(engine, source, target, args.count)
            if os.path.exists(path) and not args.rerun:
                continue
            try:
                result = run_direction(engine, source, target, args.count, meaning)
            except ValueError as e:  # the engine has no model for this direction
                result = {"engine": engine, "source": source, "target": target, "count": 0, "unsupported": str(e)}
            except Exception as e:  # a download or model failure: report it, keep going, cache nothing
                print(f"{engine:>14} {source}->{target}: FAILED {e!r}", flush=True)
                continue
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(result, fh, ensure_ascii=False, indent=1)
            summary = "unsupported" if "unsupported" in result else (
                f"chrF {result['chrf']:.1f}  meaning {result['meaning']['mean']:.3f}  "
                f"{result['seconds_per_sentence']:.2f} s/sentence")
            print(f"{engine:>14} {source}->{target}: {summary}", flush=True)


if __name__ == "__main__":
    main()
