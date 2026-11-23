# test_workflow_presets.py - saved workflows and the steps the Workflow tab remembers

import json

import pytest

from ccgen.utils import workflow_presets


def test_save_load_and_delete(tmp_path):
    path = str(tmp_path / "workflows.json")
    name = workflow_presets.save_preset("  Urdu   subtitles ", [{"kind": "generate"}], path)
    assert name == "Urdu subtitles"
    assert workflow_presets.preset_names(path) == ["Urdu subtitles"]
    steps = workflow_presets.get_preset("urdu subtitles", path)
    assert steps is not None and steps[0]["kind"] == "generate" and "model_name" in steps[0]
    assert workflow_presets.delete_preset("URDU SUBTITLES", path)
    assert workflow_presets.preset_names(path) == []


def test_a_name_is_required(tmp_path):
    with pytest.raises(ValueError, match="Type a name"):
        workflow_presets.save_preset("   ", [{"kind": "generate"}], str(tmp_path / "w.json"))


def test_unknown_steps_and_bad_inputs_are_cleaned(tmp_path):
    steps = workflow_presets.clean_steps([
        {"kind": "generate", "model_name": "tiny", "beam_size": "five"},
        {"kind": "summarise"},
        {"kind": "translate", "input": "step:7", "target_lang": "ur"},
        {"kind": "dub", "input": "step:1"},
        "not a step",
    ])
    assert [s["kind"] for s in steps] == ["generate", "translate", "dub"]
    assert steps[0]["model_name"] == "tiny" and isinstance(steps[0]["beam_size"], int)
    assert steps[1]["input"] == "source" and steps[1]["target_lang"] == "ur"
    assert steps[2]["input"] == "step:1"


def test_an_unreadable_file_reads_as_empty(tmp_path):
    path = tmp_path / "workflows.json"
    path.write_text("{not json", encoding="utf-8")
    assert workflow_presets.load_store(str(path)) == {"last": [], "presets": {}}


def test_the_last_steps_are_remembered(tmp_path):
    path = str(tmp_path / "workflows.json")
    workflow_presets.save_last([{"kind": "generate"}, {"kind": "translate", "input": "step:0"}], path)
    stored = json.loads((tmp_path / "workflows.json").read_text(encoding="utf-8"))
    assert [s["kind"] for s in stored["last"]] == ["generate", "translate"]
