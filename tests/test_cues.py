# test_cues.py - unit tests for ccgen.core.cues (subtitle cue segmentation and translation spreading)

from ccgen.core import Segment
from ccgen.core.cues import (
    CueBuilder,
    CueLayout,
    build_cues,
    distribute_text,
    ends_sentence,
    finalize_timing,
    sentence_units,
    spread_translation,
)


def _words(text: str, start: float = 0.0, step: float = 0.3, gaps: dict[int, float] | None = None):
    """Build WordTokens for space-separated text, one word every `step` seconds plus optional gaps."""
    words = []
    t = start
    for idx, token in enumerate(text.split()):
        t += (gaps or {}).get(idx, 0.0)
        words.append({"word": f" {token}", "start": t, "end": t + step * 0.9})
        t += step
    return words


def _segment(text: str, words=None, start: float = 0.0, end: float = 1.0, language: str = "en") -> Segment:
    return Segment(id=0, start=start, end=end, text=text, words=words or [], language=language)


def _cue(idx: int, text: str, start: float, end: float) -> Segment:
    return Segment(id=idx, start=start, end=end, text=text, words=[], language="en")


class TestCueBuilder:
    def test_short_segment_becomes_one_cue(self):
        builder = CueBuilder(CueLayout())
        cues = builder.add(_segment(" Hello there.", _words("Hello there."))) + builder.flush()
        assert [c["text"] for c in cues] == ["Hello there."]

    def test_segment_without_words_keeps_its_timing(self):
        builder = CueBuilder(CueLayout())
        cues = builder.add(_segment("  No words here ", start=2.0, end=5.0)) + builder.flush()
        assert (cues[0]["text"], cues[0]["start"], cues[0]["end"]) == ("No words here", 2.0, 5.0)

    def test_ids_are_sequential_across_segments(self):
        builder = CueBuilder(CueLayout(max_line_length=20, max_lines=1))
        builder.add(_segment("", _words("one two three four five six seven eight")))
        builder.add(_segment("", _words("nine ten", start=10.0)))
        assert [c["id"] for c in builder.cues] == list(range(len(builder.cues)))
        assert builder.source_count == 2

    def test_respects_character_limit_without_losing_words(self):
        text = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron pi rho"
        builder = CueBuilder(CueLayout(max_line_length=20, max_lines=2))
        cues = builder.add(_segment(text, _words(text))) + builder.flush()
        assert all(len(c["text"]) <= 40 for c in cues)
        assert " ".join(c["text"] for c in cues) == text

    def test_prefers_breaking_after_sentence_end(self):
        text = "This is the first sentence here. And this second one keeps going for quite a while longer"
        builder = CueBuilder(CueLayout(max_line_length=30, max_lines=2))
        cues = builder.add(_segment(text, _words(text))) + builder.flush()
        assert cues[0]["text"] == "This is the first sentence here."

    def test_long_pause_starts_new_cue(self):
        text = "before the pause after the pause"
        builder = CueBuilder(CueLayout())
        cues = builder.add(_segment(text, _words(text, gaps={3: 2.0}))) + builder.flush()
        assert [c["text"] for c in cues] == ["before the pause", "after the pause"]

    def test_max_duration_splits_slow_speech(self):
        text = "one two three four five six"
        builder = CueBuilder(CueLayout(max_duration=3.0))
        cues = builder.add(_segment(text, _words(text, step=1.0))) + builder.flush()
        assert len(cues) == 2
        assert all(c["end"] - c["start"] <= 3.0 for c in cues)

    def test_no_space_language_uses_shorter_lines(self):
        layout = CueLayout().for_language("ja")
        assert layout.max_line_length == 16
        assert CueLayout().for_language("en").max_line_length == 42

    def test_unfinished_tail_joins_the_next_segment(self):
        builder = CueBuilder(CueLayout())
        first = builder.add(_segment("", _words("Subtitles made on your")))
        second = builder.add(_segment("", _words("own computer, without uploads.", start=1.2)))
        assert first == []
        assert [c["text"] for c in second] == ["Subtitles made on your own computer, without uploads."]

    def test_tail_after_a_pause_stays_separate(self):
        builder = CueBuilder(CueLayout())
        builder.add(_segment("", _words("and then")))
        builder.add(_segment("", _words("much later.", start=5.0)))
        assert [c["text"] for c in builder.cues] == ["and then", "much later."]

    def test_short_sentence_end_is_a_valid_break(self):
        text = "Welcome to the show. Today we are going to talk about how subtitles are made on your own computer"
        builder = CueBuilder(CueLayout())
        cues = builder.add(_segment(text, _words(text))) + builder.flush()
        assert cues[0]["text"] == "Welcome to the show."

    def test_overlong_sentence_is_split_evenly(self):
        text = "Then a speech recognition model listens to every word and writes it down with precise timestamps."
        builder = CueBuilder(CueLayout())
        cues = builder.add(_segment(text, _words(text))) + builder.flush()
        assert [c["text"] for c in cues] == [
            "Then a speech recognition model listens to every word",
            "and writes it down with precise timestamps.",
        ]

    def test_empty_text_segments_are_dropped(self):
        builder = CueBuilder(CueLayout())
        assert builder.add(_segment("   ")) == []
        assert builder.cues == []


class TestFinalizeTiming:
    def test_overlapping_cue_is_trimmed_to_next_start(self):
        cues = finalize_timing([_cue(0, "a b c", 0.0, 3.0), _cue(1, "d", 2.0, 4.0)], CueLayout())
        assert cues[0]["end"] == 2.0

    def test_short_cue_extended_for_reading_time(self):
        cues = finalize_timing([_cue(0, "A reasonably long line to read", 0.0, 0.4)], CueLayout())
        assert cues[0]["end"] > 1.5

    def test_extension_never_overlaps_next_cue(self):
        cues = finalize_timing(
            [_cue(0, "A reasonably long line to read", 0.0, 0.4), _cue(1, "next", 0.9, 2.0)], CueLayout(),
        )
        assert cues[0]["end"] == 0.9

    def test_inverted_timing_is_repaired(self):
        cues = finalize_timing([_cue(0, "x", 5.0, 4.0)], CueLayout())
        assert cues[0]["end"] >= cues[0]["start"]

    def test_build_cues_combines_split_and_timing(self):
        cues = build_cues([_segment("Hi.", _words("Hi."))], CueLayout())
        assert cues[0]["end"] - cues[0]["start"] >= 0.5


class TestSentenceUnits:
    def test_groups_cues_until_sentence_end(self):
        cues = [_cue(0, "I went to", 0, 1), _cue(1, "the market.", 1, 2), _cue(2, "It was fun.", 2, 3)]
        assert sentence_units(cues) == [[0, 1], [2]]

    def test_long_gap_breaks_unit(self):
        cues = [_cue(0, "no ending", 0, 1), _cue(1, "much later", 10, 11)]
        assert sentence_units(cues) == [[0], [1]]

    def test_ends_sentence_ignores_closing_quotes(self):
        assert ends_sentence('He said "stop."')
        assert ends_sentence("کیا حال ہے؟")
        assert not ends_sentence("and then,")

    def test_abbreviations_and_initials_do_not_end_a_sentence(self):
        for text in ("I spoke with Dr.", "for example, e.g.", "John F.", "(Mr."):
            assert not ends_sentence(text), text
        for text in ("No.", "That was me, I.", "I got an A.", "We waited...", "Version 2."):
            assert ends_sentence(text), text

    def test_unit_continues_past_an_abbreviation(self):
        cues = [_cue(0, "Today Dr.", 0, 1), _cue(1, "Smith joins us.", 1, 2)]
        assert sentence_units(cues) == [[0, 1]]


class TestDistributeText:
    def test_splits_proportionally(self):
        assert distribute_text("a b c d", [1, 1]) == ["a b", "c d"]

    def test_every_part_gets_words_when_enough_tokens(self):
        parts = distribute_text("one two three", [100, 1, 1])
        assert all(parts)
        assert " ".join(parts) == "one two three"

    def test_prefers_punctuation_boundary(self):
        assert distribute_text("uno dos, tres cuatro cinco", [1, 1]) == ["uno dos,", "tres cuatro cinco"]

    def test_fewer_tokens_than_parts_leaves_empty_parts(self):
        parts = distribute_text("hola", [1, 1, 1])
        assert "".join(parts) == "hola"

    def test_single_part_returns_whole_text(self):
        assert distribute_text(" hola mundo ", [5]) == ["hola mundo"]

    def test_no_space_text_splits_by_character(self):
        assert distribute_text("abcd", [1, 1], no_space=True) == ["ab", "cd"]


class TestSpreadTranslation:
    def test_maps_parts_to_cue_ids_and_timing(self):
        cues = [_cue(4, "I went to the market", 0.0, 2.0), _cue(5, "with my friend.", 2.0, 3.0)]
        result = spread_translation(cues, "fui al mercado con mi amigo.", "es")
        assert [r["id"] for r in result] == [4, 5]
        assert result[0]["start"] == 0.0 and result[1]["end"] == 3.0
        assert " ".join(r["translated"] for r in result) == "fui al mercado con mi amigo."

    def test_short_translation_merges_into_previous_cue(self):
        cues = [_cue(0, "Yes", 0.0, 1.0), _cue(1, "indeed", 1.0, 2.0), _cue(2, "absolutely", 2.0, 3.0)]
        result = spread_translation(cues, "Sí", "es")
        assert len(result) == 1
        assert result[0]["translated"] == "Sí"
        assert (result[0]["start"], result[0]["end"]) == (0.0, 3.0)
