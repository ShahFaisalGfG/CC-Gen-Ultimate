# report.py - gather cached benchmark results into one Markdown report
#
#   python scripts/eval/report.py            (writes results/report.md in the benchmark cache)
#
# Translation: chrF per direction and engine (best per row in bold), with the meaning score and
# seconds per sentence. Speech: per language and engine, the mean CER, the shares of failed and
# babbling lines, the speaking rate against native speakers, speaker similarity, and the
# real-time factor, with native FLEURS speech as the first row of every language.

import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import data  # noqa: E402


def _load(pattern: str) -> list[dict]:
    rows = []
    for path in sorted(glob.glob(pattern)):
        with open(path, encoding="utf-8") as fh:
            rows.append(json.load(fh))
    return rows


def translation_table(rows: list[dict]) -> list[str]:
    """One row per direction, one column per engine."""
    engines = sorted({r["engine"] for r in rows})
    by_direction: dict[tuple[str, str], dict[str, dict]] = {}
    for r in rows:
        by_direction.setdefault((r["source"], r["target"]), {})[r["engine"]] = r
    lines = ["| Direction | " + " | ".join(engines) + " |", "|---|" + "---|" * len(engines)]
    for (source, target), cells in sorted(by_direction.items()):
        scored = {e: c["chrf"] for e, c in cells.items() if "chrf" in c}
        best = max(scored.values(), default=None)
        row = []
        for engine in engines:
            cell = cells.get(engine)
            if cell is None:
                row.append("")
            elif "chrf" not in cell:
                row.append("n/a")
            else:
                text = f"{cell['chrf']:.1f} ({cell['meaning']['mean']:.2f}, {cell['seconds_per_sentence']:.1f}s)"
                row.append(f"**{text}**" if cell["chrf"] == best else text)
        lines.append(f"| {source}→{target} | " + " | ".join(row) + " |")
    return lines


def asr_table(rows: list[dict]) -> list[str]:
    """One row per language, one column per Whisper model."""
    models = sorted({r["model"] for r in rows}, key=lambda m: ["tiny", "base", "small", "medium",
                                                               "large-v3-turbo", "large-v3"].index(m))
    cells = {(r["language"], r["model"]): r for r in rows}
    lines = ["| Language | " + " | ".join(models) + " |", "|---|" + "---|" * len(models)]
    for language in sorted({r["language"] for r in rows}):
        row = [f"{cells[(language, m)]['mean_cer']:.3f} ({cells[(language, m)]['real_time_factor']:.2f}x)"
               if (language, m) in cells else "" for m in models]
        lines.append(f"| {language} | " + " | ".join(row) + " |")
    return lines


def speech_table(rows: list[dict]) -> list[str]:
    """One block per language, one row per engine."""
    lines = ["| Language | Engine | Mean CER | Failed lines | Babble | Rate vs native | Speaker sim. | RTF |",
             "|---|---|---|---|---|---|---|---|"]
    order = {"native": 0}
    for r in sorted(rows, key=lambda r: (r["language"], order.get(r["engine"], 1), r["engine"])):
        if "unsupported" in r:
            continue
        s = r["summary"]
        sim = f"{s['speaker_similarity']['median']:.3f}" if s.get("speaker_similarity") else "-"
        rtf = f"{r['real_time_factor']:.2f}" if "real_time_factor" in r else "-"
        lines.append(f"| {r['language']} | {r['engine']} | {s['cer']['mean']:.3f} | {s['failed_rate']:.0%} | "
                     f"{s['babble_rate']:.0%} | {s['rate_vs_native']:.2f}x | {sim} | {rtf} |")
    return lines


def main() -> None:
    root = os.path.join(data.cache_root(), "results")
    out = ["# CC-Gen-Ultimate quality benchmark", ""]
    calibration = os.path.join(root, "calibration", "calibration.json")
    if os.path.exists(calibration):
        with open(calibration, encoding="utf-8") as fh:
            verdicts = json.load(fh)["verdicts"]
        out += ["## Calibration (native speech vs the rejected dub)", "",
                "| Measure | Rejected dub | Worst native group | Separates |", "|---|---|---|---|"]
        for measure, v in verdicts.items():
            out.append(f"| {measure} | {v['bad']:.3f} | {v['worst_native']:.3f} | {'yes' if v['separates'] else 'no'} |")
        out.append("")
    translation = _load(os.path.join(root, "translation", "*", "*.json"))
    if translation:
        out += ["## Translation (FLORES-200 devtest chrF; meaning score, seconds per sentence)", ""]
        out += translation_table(translation) + [""]
    asr = _load(os.path.join(root, "asr", "*.json"))
    if asr:
        out += ["## Subtitle generation (Whisper on FLEURS; mean CER, real-time factor)", ""]
        out += asr_table(asr) + [""]
    speech = _load(os.path.join(root, "speech", "*", "*.json"))
    if speech:
        out += ["## Dubbing voices (medians over clips; FLEURS native speech first)", ""]
        out += speech_table(speech) + [""]
    path = os.path.join(root, "report.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out))
    print(path)


if __name__ == "__main__":
    main()
