# test_jobs.py - the Qt-free job shaping shared by the tabs and ccgen (ccgen/core/jobs.py)

import os

from ccgen.api.schemas.job import parse_task_config
from ccgen.core import jobs


def _touch(folder, name: str) -> str:
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\0")
    return str(path)


class TestFiles:
    def test_expand_inputs_searches_folders_and_drops_duplicates(self, tmp_path):
        video = _touch(tmp_path, "a/talk.mp4")
        _touch(tmp_path, "a/b/song.mp3")
        _touch(tmp_path, "a/readme.txt")
        files, skipped = jobs.expand_inputs([str(tmp_path / "a"), video, str(tmp_path / "gone.mp4")],
                                            jobs.TASK_EXTS["generate"])
        assert [os.path.basename(f) for f in files] == ["talk.mp4", "song.mp3"]
        assert skipped == [str(tmp_path / "gone.mp4")]

    def test_dub_pairs_subtitles_with_media_of_the_same_name(self, tmp_path):
        video = _touch(tmp_path, "talk.mp4")
        paired = _touch(tmp_path, "talk_es.srt")
        sibling = _touch(tmp_path, "intro_ur.srt")
        beside = _touch(tmp_path, "intro.mkv")
        alone = _touch(tmp_path, "notes_en.srt")
        media, companions, unpaired = jobs.pair_for_dub([video, paired, sibling, alone])
        assert media == [video, beside]
        assert companions == {video: paired, beside: sibling}
        assert unpaired == [alone]

    def test_items_carry_the_language_of_their_text(self, tmp_path):
        assert jobs.make_item(str(tmp_path / "talk_ur.srt"))["language"] == "ur"
        item = jobs.make_item(str(tmp_path / "talk.mp4"), companion=str(tmp_path / "talk_es.srt"))
        assert jobs.has_text(item) and jobs.effective_language(item) == "es"


class TestJobs:
    def test_media_on_the_translate_tab_is_transcribed_first(self, tmp_path):
        options = {**jobs.translate_options({}), "target_lang": "ur"}
        body = jobs.task_job("translate", jobs.make_item(str(tmp_path / "talk.mp4")), options, {})
        assert [s["kind"] for s in body["steps"]] == ["generate", "translate"]
        assert body["steps"][0]["write_output"] is False
        parse_task_config(body)

    def test_speech_already_in_the_target_script_converts_the_other_way(self, tmp_path):
        options = {**jobs.transliterate_options({}), "source_scheme": "roman", "target_scheme": "ur"}
        body = jobs.task_job("transliterate", jobs.make_item(str(tmp_path / "talk.mp4")), options, {})
        assert body["steps"][1]["alternate_target"] == "roman"
        parse_task_config(body)

    def test_known_urdu_speech_into_urdu_is_blocked_before_start(self, tmp_path):
        options = {**jobs.transliterate_options({}), "spoken_language": "ur", "source_scheme": "ur",
                   "target_scheme": "ur"}
        blocker = jobs.queue_blocker("transliterate", [jobs.make_item(str(tmp_path / "talk.mp4"))], options, {})
        assert "Urdu speech is transcribed in Urdu (Nastaliq) already" in blocker
        options["source_scheme"] = "roman"
        assert jobs.queue_blocker("transliterate", [jobs.make_item(str(tmp_path / "talk.mp4"))], options, {}) == ""

    def test_dub_of_media_translates_then_speaks(self, tmp_path):
        options = {**jobs.dub_options({}), "language": "es", "spoken_language": "en"}
        body = jobs.task_job("dub", jobs.make_item(str(tmp_path / "talk.mp4")), options, {})
        assert [s["kind"] for s in body["steps"]] == ["generate", "translate", "dub"]
        parse_task_config(body)

    def test_the_light_profile_needs_no_licence_for_a_dub(self):
        options = {**jobs.dub_options({}), "language": "es"}
        assert jobs.pending_licence("dub", options, {"performance": {"profile": "light"}}) == ""
        assert jobs.pending_licence("dub", options, {"performance": {"profile": "balanced"}}) == "omnivoice"

    def test_relies_on_names_the_saved_models(self):
        settings = {"model": {"name": "base"}}
        assert jobs.relies_on("translate", jobs.translate_options(settings), settings) \
            == "Uses Whisper base for speech in videos and audio."
        assert jobs.relies_on("generate", jobs.generate_options(settings), settings) == ""


class TestPlannedOutputs:
    def test_generate_lists_each_format(self, tmp_path):
        options = {**jobs.generate_options({}), "formats": ["srt", "vtt"]}
        body = jobs.task_job("generate", jobs.make_item(str(tmp_path / "talk.mp4")), options, {})
        assert [os.path.basename(p) for p in jobs.planned_outputs(body)] == ["talk.srt", "talk.vtt"]

    def test_a_subtitle_s_language_tag_is_dropped_from_the_name(self, tmp_path):
        options = {**jobs.translate_options({}), "target_lang": "ur"}
        body = jobs.task_job("translate", jobs.make_item(str(tmp_path / "talk_en.srt")), options, {})
        assert [os.path.basename(p) for p in jobs.planned_outputs(body)] == ["talk_ur.srt"]

    def test_a_dub_into_a_known_language(self, tmp_path):
        options = {**jobs.dub_options({}), "language": "es"}
        body = jobs.task_job("dub", jobs.make_item(str(tmp_path / "talk.mp3")), options, {})
        assert [os.path.basename(p) for p in jobs.planned_outputs(body)] == ["talk_dub_es.mka"]

    def test_existing_outputs_are_found(self, tmp_path):
        body = jobs.task_job("generate", jobs.make_item(str(tmp_path / "talk.mp4")), jobs.generate_options({}), {})
        assert jobs.existing_outputs(body) == []
        (tmp_path / "talk.srt").write_text("")
        assert jobs.existing_outputs(body) == [str(tmp_path / "talk.srt")]
