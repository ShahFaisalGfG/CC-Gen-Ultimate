# calibrate.py - check that each speech metric tells native speech from a dub people rejected
#
#   python scripts/eval/calibrate.py --bad-media "1. Intro_dub_hi.mkv" --bad-track 1 \
#       --bad-subtitles "1. Intro_hi.srt" --bad-language hi --original "1. Intro.mp4"
#
# Known good: FLEURS recordings of native speakers in the bad dub's language (and others).
# Known bad: each line of a dub that listeners judged unusable, cut from its dub track by the
# subtitle times. Lines are the sentences the app speaks as one (see core/dubbing.spoken_units). A measure may decide between engines only if it puts every known-good group
# clearly ahead of the known-bad one; the verdict for each measure is printed and saved.

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import data  # noqa: E402
from scoring import ClipScore, Scorer, clip_rows, summary  # noqa: E402

from ccgen.core.dubbing import spoken_units  # noqa: E402
from ccgen.core.subtitle_parser import parse_subtitle  # noqa: E402

# A native speaking rate within this range of the dub's counts as natural pacing.
NATURAL_RATE = (0.87, 1.15)
# The bad dub's mean CER must exceed every native group's by this factor.
_CER_FACTOR = 1.5


def dub_lines(media: str, track: int, subtitles: str, scorer: Scorer, language: str,
              original: str, out_dir: str) -> list[ClipScore]:
    """Score every line of a dub track against its subtitle text and the original speaker."""
    audio, rate = data.read_audio(media, track)
    cues = parse_subtitle(subtitles)
    reference = None
    if original:
        source, source_rate = data.read_audio(original)
        reference = scorer.speakers.vector(source[: 30 * source_rate], source_rate)
    scores = []
    units = spoken_units(cues, [0] * len(cues), language)
    for number, (members, text) in enumerate(units):
        following = units[number + 1][0][0] if number + 1 < len(units) else None
        end = cues[following]["start"] if following is not None else cues[members[-1]]["end"] + 1.0
        clip = audio[int(cues[members[0]]["start"] * rate): int(end * rate)]
        text = " ".join(text.split())
        data.write_wav(os.path.join(out_dir, "bad", f"{members[0] + 1:03d}.wav"), clip, rate)
        scores.append(scorer.score(clip, rate, text, language, reference))
    return scores


def native(language: str, count: int, scorer: Scorer, out_dir: str) -> list[ClipScore]:
    """Score FLEURS recordings of native speakers."""
    scores = []
    for utterance in data.fleurs(language, count):
        data.write_wav(os.path.join(out_dir, f"native_{language}", utterance.key), utterance.audio, utterance.rate)
        scores.append(scorer.score(utterance.audio, utterance.rate, utterance.text, language))
    return scores


def verdicts(good: dict[str, dict], bad: dict, bad_language: str) -> dict[str, dict]:
    """For each measure, whether every native group is clearly better than the rejected dub."""
    worst_native = {key: max(g[key] if key.endswith("rate") else g[key]["mean"] for g in good.values())
                    for key in ("cer", "failed_rate", "babble_rate")}
    rate = bad.get("rate_vs_native", 1.0)
    return {
        "mean_cer": {"bad": bad["cer"]["mean"], "worst_native": worst_native["cer"],
                     "separates": bad["cer"]["mean"] >= _CER_FACTOR * worst_native["cer"]},
        "failed_rate": {"bad": bad["failed_rate"], "worst_native": worst_native["failed_rate"],
                        "separates": bad["failed_rate"] > worst_native["failed_rate"]},
        "babble_rate": {"bad": bad["babble_rate"], "worst_native": worst_native["babble_rate"],
                        "separates": bad["babble_rate"] > worst_native["babble_rate"]},
        "rate_vs_native": {"bad": rate, "worst_native": 1.0, "language": bad_language,
                           "separates": not NATURAL_RATE[0] <= rate <= NATURAL_RATE[1]},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bad-media", required=True)
    parser.add_argument("--bad-track", type=int, default=1, help="Audio track index of the dub (0 is the first)")
    parser.add_argument("--bad-subtitles", required=True)
    parser.add_argument("--bad-language", required=True)
    parser.add_argument("--original", default="", help="Original media, for speaker similarity")
    parser.add_argument("--native", default="", help="Extra native languages to compare (default: the dub's and ur)")
    parser.add_argument("--count", type=int, default=20)
    args = parser.parse_args()
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

    out_dir = os.path.join(data.cache_root(), "results", "calibration")
    scorer = Scorer()
    bad_scores = dub_lines(args.bad_media, args.bad_track, args.bad_subtitles, scorer, args.bad_language,
                           args.original, out_dir)
    languages = [args.bad_language] + [l for l in (args.native or "ur").split(",") if l != args.bad_language]
    good_scores = {f"native_{lang}": native(lang, args.count, scorer, out_dir) for lang in languages}
    good = {name: summary(scores) for name, scores in good_scores.items()}
    native_rate = good[f"native_{args.bad_language}"]["seconds_per_char"]["median"]
    bad = summary(bad_scores, native_rate)
    report = {"bad": bad, "good": good, "verdicts": verdicts(good, bad, args.bad_language),
              "bad_clips": clip_rows(bad_scores), "good_clips": {n: clip_rows(s) for n, s in good_scores.items()}}
    with open(os.path.join(out_dir, "calibration.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)

    for measure, verdict in report["verdicts"].items():
        print(f"{measure:<16} rejected dub {verdict['bad']:.3f}   worst native {verdict['worst_native']:.3f}   "
              f"separates: {verdict['separates']}")
    if bad.get("speaker_similarity"):
        print(f"rejected dub speaker similarity to the original: {bad['speaker_similarity']['median']:.3f}")


if __name__ == "__main__":
    main()
