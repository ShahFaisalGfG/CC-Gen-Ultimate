# test_subtitle_parser.py — unit tests for ccgen.core.subtitle_parser

import pytest

from ccgen.core.subtitle_parser import is_subtitle, parse_subtitle

SRT_CONTENT = (
    "1\n"
    "00:00:00,000 --> 00:00:02,500\n"
    "Hello world.\n"
    "\n"
    "2\n"
    "00:00:03,000 --> 00:00:05,750\n"
    "This is a test.\n"
)

VTT_CONTENT = (
    "WEBVTT\n"
    "\n"
    "00:00:00.000 --> 00:00:02.500\n"
    "Hello world.\n"
    "\n"
    "00:00:03.000 --> 00:00:05.750\n"
    "This is a test.\n"
)


def _write(tmp_path, name, content):
    """Write content to a file under tmp_path and return its string path."""
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return str(path)


class TestParseSrt:
    def test_parses_all_blocks(self, tmp_path):
        path = _write(tmp_path, "sample.srt", SRT_CONTENT)
        segments = parse_subtitle(path)
        assert len(segments) == 2

    def test_first_segment_fields(self, tmp_path):
        path = _write(tmp_path, "sample.srt", SRT_CONTENT)
        segments = parse_subtitle(path)
        first = segments[0]
        assert first["id"] == 0
        assert first["start"] == 0.0
        assert first["end"] == 2.5
        assert first["text"] == "Hello world."

    def test_segment_ids_increment(self, tmp_path):
        path = _write(tmp_path, "sample.srt", SRT_CONTENT)
        segments = parse_subtitle(path)
        assert [seg["id"] for seg in segments] == [0, 1]

    def test_segment_has_empty_words_and_language(self, tmp_path):
        path = _write(tmp_path, "sample.srt", SRT_CONTENT)
        segments = parse_subtitle(path)
        assert segments[0]["words"] == []
        assert segments[0]["language"] == ""

    def test_multiline_body_joined_with_space(self, tmp_path):
        content = "1\n00:00:00,000 --> 00:00:02,000\nLine one\nLine two\n"
        path = _write(tmp_path, "multi.srt", content)
        segments = parse_subtitle(path)
        assert segments[0]["text"] == "Line one Line two"

    def test_skips_block_without_timestamp(self, tmp_path):
        content = SRT_CONTENT + "\n3\nNot a timestamp\nOrphan text\n"
        path = _write(tmp_path, "malformed.srt", content)
        segments = parse_subtitle(path)
        assert len(segments) == 2

    def test_skips_block_without_body_text(self, tmp_path):
        content = "1\n00:00:00,000 --> 00:00:02,000\n"
        path = _write(tmp_path, "empty_body.srt", content)
        assert parse_subtitle(path) == []

    def test_malformed_timestamp_defaults_to_zero(self, tmp_path):
        content = "1\naa:bb:cc,ddd --> ee:ff:gg,hhh\nSome text\n"
        path = _write(tmp_path, "bad_time.srt", content)
        segments = parse_subtitle(path)
        assert segments[0]["start"] == 0.0
        assert segments[0]["end"] == 0.0

    def test_empty_file_returns_no_segments(self, tmp_path):
        path = _write(tmp_path, "empty.srt", "")
        assert parse_subtitle(path) == []

    def test_whitespace_only_file_returns_no_segments(self, tmp_path):
        path = _write(tmp_path, "blank.srt", "\n\n   \n")
        assert parse_subtitle(path) == []

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            parse_subtitle(str(tmp_path / "missing.srt"))


class TestMarkup:
    def test_srt_styling_tags_are_removed(self, tmp_path):
        content = "1\n00:00:00,000 --> 00:00:02,000\n{\\an8}<i>Hello</i> <font color=\"#ff0\">world</font>.\n"
        assert parse_subtitle(_write(tmp_path, "a.srt", content))[0]["text"] == "Hello world."

    def test_vtt_voice_class_and_timestamp_tags_are_removed(self, tmp_path):
        content = (
            "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\n"
            "<v Roger>Rock <00:00:01.000><c.loud>&amp; roll</c>\n"
        )
        assert parse_subtitle(_write(tmp_path, "a.vtt", content))[0]["text"] == "Rock & roll"

    def test_plain_angle_brackets_and_braces_stay(self, tmp_path):
        content = "1\n00:00:00,000 --> 00:00:02,000\n3 < 5 and {braces} stay\n"
        assert parse_subtitle(_write(tmp_path, "a.srt", content))[0]["text"] == "3 < 5 and {braces} stay"

    def test_cue_with_only_markup_is_skipped(self, tmp_path):
        content = "1\n00:00:00,000 --> 00:00:02,000\n<i></i>\n\n2\n00:00:03,000 --> 00:00:04,000\nHi\n"
        assert [s["text"] for s in parse_subtitle(_write(tmp_path, "a.srt", content))] == ["Hi"]


class TestParseVtt:
    def test_parses_all_cues(self, tmp_path):
        path = _write(tmp_path, "sample.vtt", VTT_CONTENT)
        segments = parse_subtitle(path)
        assert len(segments) == 2

    def test_first_cue_fields(self, tmp_path):
        path = _write(tmp_path, "sample.vtt", VTT_CONTENT)
        segments = parse_subtitle(path)
        first = segments[0]
        assert first["start"] == 0.0
        assert first["end"] == 2.5
        assert first["text"] == "Hello world."

    def test_skips_note_block_before_header(self, tmp_path):
        content = (
            "WEBVTT\n"
            "\n"
            "NOTE\n"
            "A comment that should be ignored.\n"
            "\n"
            "00:00:00.000 --> 00:00:02.500\n"
            "Hello world.\n"
        )
        path = _write(tmp_path, "note.vtt", content)
        segments = parse_subtitle(path)
        assert len(segments) == 1
        assert segments[0]["text"] == "Hello world."

    def test_numeric_cue_identifier_ignored(self, tmp_path):
        content = "WEBVTT\n\n1\n00:00:00.000 --> 00:00:02.500\nHello.\n"
        path = _write(tmp_path, "cue_id.vtt", content)
        segments = parse_subtitle(path)
        assert segments[0]["text"] == "Hello."

    def test_minutes_seconds_timestamp_without_hours(self, tmp_path):
        content = "WEBVTT\n\n01:02.500 --> 01:05.000\nShort form timestamp.\n"
        path = _write(tmp_path, "short_time.vtt", content)
        segments = parse_subtitle(path)
        assert segments[0]["start"] == 62.5
        assert segments[0]["end"] == 65.0

    def test_cue_settings_after_timestamp_ignored(self, tmp_path):
        content = (
            "WEBVTT\n"
            "\n"
            "00:00:01.000 --> 00:00:04.000 position:10%,line:0\n"
            "Positioned cue.\n"
        )
        path = _write(tmp_path, "positioned.vtt", content)
        segments = parse_subtitle(path)
        assert segments[0]["end"] == 4.0
        assert segments[0]["text"] == "Positioned cue."

    def test_empty_vtt_returns_no_segments(self, tmp_path):
        path = _write(tmp_path, "empty.vtt", "WEBVTT\n")
        assert parse_subtitle(path) == []

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            parse_subtitle(str(tmp_path / "missing.vtt"))


class TestParseSbv:
    SBV_CONTENT = (
        "0:00:00.000,0:00:02.500\n"
        "Hello world.\n"
        "\n"
        "0:00:03.000,0:00:05.750\n"
        "This is a test.\n"
    )

    def test_parses_all_blocks(self, tmp_path):
        path = _write(tmp_path, "sample.sbv", self.SBV_CONTENT)
        segments = parse_subtitle(path)
        assert len(segments) == 2

    def test_first_block_fields(self, tmp_path):
        path = _write(tmp_path, "sample.sbv", self.SBV_CONTENT)
        segments = parse_subtitle(path)
        first = segments[0]
        assert first["start"] == 0.0
        assert first["end"] == 2.5
        assert first["text"] == "Hello world."

    def test_multiline_body_joined_with_space(self, tmp_path):
        content = "0:00:00.000,0:00:02.000\nLine one\nLine two\n"
        path = _write(tmp_path, "multi.sbv", content)
        segments = parse_subtitle(path)
        assert segments[0]["text"] == "Line one Line two"

    def test_empty_file_returns_no_segments(self, tmp_path):
        path = _write(tmp_path, "empty.sbv", "")
        assert parse_subtitle(path) == []


class TestParseLrc:
    LRC_CONTENT = (
        "[00:00.00]Hello world.\n"
        "[00:03.00]This is a test.\n"
    )

    def test_parses_all_lines(self, tmp_path):
        path = _write(tmp_path, "sample.lrc", self.LRC_CONTENT)
        segments = parse_subtitle(path)
        assert len(segments) == 2

    def test_first_line_fields(self, tmp_path):
        path = _write(tmp_path, "sample.lrc", self.LRC_CONTENT)
        segments = parse_subtitle(path)
        first = segments[0]
        assert first["start"] == 0.0
        assert first["text"] == "Hello world."

    def test_end_time_derived_from_next_line_start(self, tmp_path):
        path = _write(tmp_path, "sample.lrc", self.LRC_CONTENT)
        segments = parse_subtitle(path)
        assert segments[0]["end"] == 3.0

    def test_last_line_gets_fallback_duration(self, tmp_path):
        path = _write(tmp_path, "sample.lrc", self.LRC_CONTENT)
        segments = parse_subtitle(path)
        assert segments[1]["end"] == segments[1]["start"] + 4.0

    def test_blank_text_timestamp_is_skipped(self, tmp_path):
        content = "[00:00.00]\n[00:03.00]Real lyric.\n"
        path = _write(tmp_path, "instrumental.lrc", content)
        segments = parse_subtitle(path)
        assert len(segments) == 1
        assert segments[0]["text"] == "Real lyric."

    def test_empty_file_returns_no_segments(self, tmp_path):
        path = _write(tmp_path, "empty.lrc", "")
        assert parse_subtitle(path) == []


class TestParseAss:
    ASS_CONTENT = (
        "[Script Info]\n"
        "Title: Test\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname\n"
        "Style: Default,Arial\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:00.00,0:00:02.50,Default,,0,0,0,,Hello world.\n"
        "Dialogue: 0,0:00:03.00,0:00:05.75,Default,,0,0,0,,Line one\\NLine two\n"
    )

    def test_parses_all_dialogue_lines(self, tmp_path):
        path = _write(tmp_path, "sample.ass", self.ASS_CONTENT)
        segments = parse_subtitle(path)
        assert len(segments) == 2

    def test_first_dialogue_fields(self, tmp_path):
        path = _write(tmp_path, "sample.ass", self.ASS_CONTENT)
        segments = parse_subtitle(path)
        first = segments[0]
        assert first["start"] == 0.0
        assert first["end"] == 2.5
        assert first["text"] == "Hello world."

    def test_forced_line_break_becomes_space(self, tmp_path):
        path = _write(tmp_path, "sample.ass", self.ASS_CONTENT)
        segments = parse_subtitle(path)
        assert segments[1]["text"] == "Line one Line two"

    def test_override_tags_stripped(self, tmp_path):
        content = (
            "[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
            "Dialogue: 0,0:00:00.00,0:00:02.00,Default,,0,0,0,,{\\an8}Styled text.\n"
        )
        path = _write(tmp_path, "styled.ass", content)
        segments = parse_subtitle(path)
        assert segments[0]["text"] == "Styled text."

    def test_ssa_extension_uses_same_parser(self, tmp_path):
        path = _write(tmp_path, "sample.ssa", self.ASS_CONTENT)
        segments = parse_subtitle(path)
        assert len(segments) == 2

    def test_empty_file_returns_no_segments(self, tmp_path):
        path = _write(tmp_path, "empty.ass", "[Script Info]\n")
        assert parse_subtitle(path) == []


class TestParseSubtitleErrors:
    def test_unsupported_extension_raises_value_error(self, tmp_path):
        path = _write(tmp_path, "captions.txt", SRT_CONTENT)
        with pytest.raises(ValueError):
            parse_subtitle(path)


class TestIsSubtitle:
    def test_srt_extension_true(self):
        assert is_subtitle("/videos/movie.srt") is True

    def test_vtt_extension_true(self):
        assert is_subtitle("/videos/movie.vtt") is True

    def test_uppercase_extension_true(self):
        assert is_subtitle("/videos/MOVIE.SRT") is True

    def test_mixed_case_extension_true(self):
        assert is_subtitle("/videos/movie.Vtt") is True

    def test_lrc_extension_true(self):
        assert is_subtitle("/videos/movie.lrc") is True

    def test_ass_extension_true(self):
        assert is_subtitle("/videos/movie.ass") is True

    def test_ssa_extension_true(self):
        assert is_subtitle("/videos/movie.ssa") is True

    def test_sbv_extension_true(self):
        assert is_subtitle("/videos/movie.sbv") is True

    def test_video_extension_false(self):
        assert is_subtitle("/videos/movie.mp4") is False

    def test_no_extension_false(self):
        assert is_subtitle("/videos/movie") is False
