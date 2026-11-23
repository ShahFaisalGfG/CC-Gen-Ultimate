# test_cli.py - the ccgen command line: task commands over fake tasks, JSON events, exit statuses,
# licences, models, settings, the skill, and every command line the skill shows parsing for real.

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ccgen import cli, cli_tasks
from ccgen.core.tasks import TaskResult
from ccgen.utils import settings as settings_module

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "ccgen"


@pytest.fixture(autouse=True)
def private_settings(tmp_path, monkeypatch):
    """Keep each test's settings in its own file, never the repository's."""
    path = tmp_path / "settings.json"
    monkeypatch.setattr(settings_module, "get_settings_file", lambda: str(path))
    return path


@pytest.fixture(autouse=True)
def no_mutexes(monkeypatch):
    monkeypatch.setattr(cli_tasks, "hold_app_mutexes", lambda: None)
    monkeypatch.setattr(cli_tasks, "release_app_mutexes", lambda: None)


class FakeTask:
    """A task that reports a status and progress, then writes its planned subtitle file."""

    stages = ["load", "transcribe"]

    def __init__(self, config: Any, outcome: str = "ok") -> None:
        self.config = config
        self.outcome = outcome
        self.cancelled = False
        self.stage, self.step = "", 0

    def cancel(self) -> None:
        self.cancelled = True

    def prepare(self, status_cb=None, progress_cb=None) -> None:
        self.stage = "load"
        status_cb("Loading speech recognition model...")

    def run(self, status_cb=None, segment_cb=None, progress_cb=None) -> TaskResult:
        self.stage, self.step = "transcribe", 1
        status_cb("Transcribing...")
        progress_cb(1, 1)
        if segment_cb:
            segment_cb({"id": 0, "start": 0.0, "end": 1.0, "text": "Hello.", "words": [], "language": "en"})
        path = self.config.input_path
        if self.outcome == "fail":
            return TaskResult(success=False, input_path=path, error="The graphics card ran out of memory.",
                              error_detail="RuntimeError: CUDA out of memory")
        out = os.path.splitext(path)[0] + ".srt"
        Path(out).write_text("1\n00:00:00,000 --> 00:00:01,000\nHello.\n", encoding="utf-8")
        return TaskResult(success=True, input_path=path, output_files=[out], output_languages={out: "en"},
                          warnings=["No speech in the last minute."])


def fake_tasks(monkeypatch, outcome: str = "ok") -> list[FakeTask]:
    made: list[FakeTask] = []

    def create(config):
        made.append(FakeTask(config, outcome))
        return made[-1]

    monkeypatch.setattr(cli_tasks, "create_task", create)
    return made


def run_json(capsys, argv: list[str]) -> tuple[int, list[dict[str, Any]]]:
    code = cli.main(argv)
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    return code, [json.loads(line) for line in lines]


def media(tmp_path: Path, name: str = "talk.mp4") -> str:
    path = tmp_path / name
    path.write_bytes(b"\0" * 64)
    return str(path)


def subtitle(tmp_path: Path, name: str) -> str:
    path = tmp_path / name
    path.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello.\n", encoding="utf-8")
    return str(path)


class TestTasks:
    def test_generate_reports_every_event_and_the_file(self, tmp_path, monkeypatch, capsys):
        made = fake_tasks(monkeypatch)
        code, events = run_json(capsys, ["generate", media(tmp_path), "--model", "tiny", "--json", "--segments"])
        assert code == cli.EXIT_OK
        kinds = [e["event"] for e in events]
        assert kinds[0] == "start" and kinds[-1] == "done"
        for kind in ("item", "status", "progress", "segment", "file", "warning"):
            assert kind in kinds
        written = next(e for e in events if e["event"] == "file")
        assert written["path"].endswith("talk.srt") and written["language"] == "en"
        assert events[-1] == {**events[-1], "ok": True, "exit_code": 0, "done": 1, "failed": 0, "written": 1}
        assert made[0].config.model_name == "tiny"

    def test_folders_are_searched_and_unusable_files_skipped(self, tmp_path, monkeypatch, capsys):
        fake_tasks(monkeypatch)
        nested = tmp_path / "season" / "disc 1"
        nested.mkdir(parents=True)
        media(nested, "one.mkv")
        media(tmp_path / "season", "two.mp3")
        subtitle(tmp_path / "season", "notes.srt")
        code, events = run_json(capsys, ["generate", str(tmp_path / "season"), "--json"])
        assert code == cli.EXIT_OK
        # A folder's own files come before its subfolders', as the app's folder scan adds them.
        assert [os.path.basename(e["input"]) for e in events if e["event"] == "item"] == ["two.mp3", "one.mkv"]

    def test_results_already_there_are_skipped_by_default(self, tmp_path, monkeypatch, capsys):
        made = fake_tasks(monkeypatch)
        path = media(tmp_path)
        subtitle(tmp_path, "talk.srt")
        code, events = run_json(capsys, ["generate", path, "--json"])
        assert code == cli.EXIT_OK and not made
        assert [e["event"] for e in events] == ["start", "skipped", "done"]
        assert "--existing replace" in events[1]["reason"]

    def test_keep_both_passes_its_choice_to_the_task(self, tmp_path, monkeypatch, capsys):
        made = fake_tasks(monkeypatch)
        path = media(tmp_path)
        subtitle(tmp_path, "talk.srt")
        code, _events = run_json(capsys, ["generate", path, "--existing", "keep-both", "--json"])
        assert code == cli.EXIT_OK and made[0].config.existing == "keep_both"

    def test_a_failed_file_is_an_error_event_and_exit_1(self, tmp_path, monkeypatch, capsys):
        fake_tasks(monkeypatch, "fail")
        code, events = run_json(capsys, ["generate", media(tmp_path), "--json"])
        assert code == cli.EXIT_FAILED
        error = next(e for e in events if e["event"] == "error")
        assert error["kind"] == "gpu_memory" and "CUDA out of memory" in error["detail"]
        assert events[-1]["ok"] is False and events[-1]["failed"] == 1

    def test_nothing_usable_is_exit_2(self, tmp_path, capsys):
        code, events = run_json(capsys, ["generate", subtitle(tmp_path, "talk_en.srt"), "--json"])
        assert code == cli.EXIT_INVALID
        assert events[-1]["event"] == "done" and events[-1]["exit_code"] == 2

    def test_ctrl_c_stops_with_130(self, tmp_path, monkeypatch, capsys):
        def interrupted(*_args, **_kwargs):
            raise KeyboardInterrupt

        monkeypatch.setattr(cli_tasks, "run_job", interrupted)
        code, events = run_json(capsys, ["generate", media(tmp_path), "--json"])
        assert code == cli.EXIT_STOPPED
        assert events[-1]["exit_code"] == 130 and "Run the command again" in events[-1]["message"]

    def test_human_mode_prints_the_written_files_on_stdout(self, tmp_path, monkeypatch, capsys):
        fake_tasks(monkeypatch)
        assert cli.main(["generate", media(tmp_path)]) == cli.EXIT_OK
        captured = capsys.readouterr()
        assert captured.out.strip().endswith("talk.srt")
        assert "1 done" in captured.err

    def test_translate_builds_the_tab_s_job(self, tmp_path, monkeypatch, capsys):
        made = fake_tasks(monkeypatch)
        code, _events = run_json(capsys, ["translate", subtitle(tmp_path, "talk.srt"), "--subtitle-language", "en",
                                          "--to", "es", "--engine", "opus_mt", "--json"])
        assert code == cli.EXIT_OK
        config = made[0].config
        assert (config.task, config.source_lang, config.target_lang) == ("translate", "en", "es")

    def test_a_subtitle_without_a_language_is_refused(self, tmp_path, capsys):
        code, events = run_json(capsys, ["translate", subtitle(tmp_path, "talk.srt"), "--to", "es", "--json"])
        assert code == cli.EXIT_INVALID
        assert "--subtitle-language" in events[-1]["message"]

    def test_dub_pairs_a_video_with_its_subtitle(self, tmp_path, monkeypatch, capsys):
        made = fake_tasks(monkeypatch)
        video = media(tmp_path, "talk.mp4")
        subtitle(tmp_path, "talk_es.srt")
        code, events = run_json(capsys, ["dub", str(tmp_path), "--to", "es", "--voices", "piper", "--json"])
        assert code == cli.EXIT_OK
        assert [e["input"] for e in events if e["event"] == "item"] == [video]
        config = made[0].config
        assert config.text_path.endswith("talk_es.srt") and config.steps[-1].mode == "piper"

    def test_workflow_steps_file(self, tmp_path, monkeypatch, capsys):
        made = fake_tasks(monkeypatch)
        steps = tmp_path / "steps.json"
        steps.write_text(json.dumps([{"kind": "generate"}, {"kind": "translate", "input": "step:0",
                                                            "target_lang": "ur", "engine": "opus_mt"}]))
        code, _events = run_json(capsys, ["workflow", media(tmp_path), "--steps", str(steps), "--json"])
        assert code == cli.EXIT_OK
        assert [s.kind for s in made[0].config.steps] == ["generate", "translate"]

    def test_workflow_preset_by_name(self, tmp_path, monkeypatch, capsys):
        from ccgen.utils import workflow_presets

        made = fake_tasks(monkeypatch)
        workflow_presets.save_preset("Urdu subtitles", [{"kind": "generate"}, {"kind": "translate",
                                                                               "input": "step:0", "target_lang": "ur"}])
        code, _events = run_json(capsys, ["workflow", media(tmp_path), "--preset", "urdu SUBTITLES", "--json"])
        assert code == cli.EXIT_OK and made[0].config.steps[1].target_lang == "ur"
        code, events = run_json(capsys, ["workflow", "--list", "--json"])
        assert code == cli.EXIT_OK and events[0]["presets"][0]["name"] == "Urdu subtitles"


class TestLicences:
    def test_an_unaccepted_licence_is_refused_with_its_option(self, tmp_path, monkeypatch, capsys):
        made = fake_tasks(monkeypatch)
        code, events = run_json(capsys, ["translate", subtitle(tmp_path, "talk_en.srt"), "--to", "ur",
                                          "--engine", "nllb", "--json"])
        assert code == cli.EXIT_INVALID and not made
        assert "--accept-terms nllb" in events[-1]["message"] and "Ask the user" in events[-1]["message"]

    def test_accept_terms_records_the_licence_and_runs(self, tmp_path, monkeypatch, capsys, private_settings):
        made = fake_tasks(monkeypatch)
        code, events = run_json(capsys, ["translate", subtitle(tmp_path, "talk_en.srt"), "--to", "ur",
                                          "--engine", "nllb", "--accept-terms", "nllb", "--json"])
        assert code == cli.EXIT_OK and made
        assert json.loads(private_settings.read_text())["translation"]["nllb_terms_accepted"] is True
        assert any(e["event"] == "warning" and "Accepted" in e["message"] for e in events)

    def test_licences_can_t_be_set_as_settings(self, capsys):
        code, _events = run_json(capsys, ["settings", "set", "translation.nllb_terms_accepted", "true", "--json"])
        assert code == cli.EXIT_INVALID


class TestSettings:
    def test_set_get_and_list(self, capsys, private_settings):
        assert run_json(capsys, ["settings", "set", "translation.target_lang", "ur", "--json"])[0] == cli.EXIT_OK
        code, events = run_json(capsys, ["settings", "get", "translation.target_lang", "--json"])
        assert code == cli.EXIT_OK and events[0] == {"key": "translation.target_lang", "value": "ur"}
        code, events = run_json(capsys, ["settings", "list", "--json"])
        assert events[0]["translation"]["target_lang"] == "ur"

    def test_a_value_the_setting_doesn_t_take_is_refused(self, capsys):
        code, events = run_json(capsys, ["settings", "set", "model.name", "huge", "--json"])
        assert code == cli.EXIT_INVALID and "Choose one of" in events[0]["error"]

    def test_auto_means_detect_for_the_spoken_language(self, capsys):
        assert cli.main(["settings", "set", "transcription.language", "ur"]) == cli.EXIT_OK
        assert cli.main(["settings", "set", "transcription.language", "auto"]) == cli.EXIT_OK
        capsys.readouterr()
        assert run_json(capsys, ["settings", "get", "transcription.language", "--json"])[1][0]["value"] is None

    def test_reset_needs_yes_without_a_terminal(self, capsys, monkeypatch):
        monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: False))
        assert run_json(capsys, ["settings", "reset", "--json"])[0] == cli.EXIT_INVALID
        assert run_json(capsys, ["settings", "reset", "--yes", "--json"])[0] == cli.EXIT_OK


class TestModels:
    ROWS = [
        {"id": "whisper:tiny", "category": "whisper", "engine": "Whisper", "label": "tiny", "downloaded": True,
         "size_bytes": 78_000_000, "approx_size_mb": 75},
        {"id": "voices:kokoro", "category": "voices", "engine": "Kokoro", "label": "Kokoro", "downloaded": False,
         "size_bytes": None, "approx_size_mb": 354},
    ]

    def test_list_filters(self, monkeypatch, capsys):
        monkeypatch.setattr(cli_tasks.asset_registry, "list_assets", lambda: self.ROWS)
        code, events = run_json(capsys, ["models", "list", "--downloaded", "--json"])
        assert code == cli.EXIT_OK and [m["id"] for m in events[0]["models"]] == ["whisper:tiny"]

    def test_download_reports_progress_and_done(self, monkeypatch, capsys):
        monkeypatch.setattr(cli_tasks.asset_registry, "list_assets", lambda: self.ROWS)
        monkeypatch.setattr(cli_tasks.asset_registry, "check_free_space", lambda asset: None)

        def download(asset_id, status_cb, progress_cb, cancel_check):
            progress_cb(50, 100)
            progress_cb(100, 100)

        monkeypatch.setattr(cli_tasks.asset_registry, "download_asset", download)
        code, events = run_json(capsys, ["models", "download", "voices:kokoro", "--json"])
        assert code == cli.EXIT_OK
        assert [e["event"] for e in events][-2:] == ["file", "done"]
        assert any(e["event"] == "progress" and e["fraction"] == 1.0 for e in events)

    def test_a_failed_download_is_plain_and_exit_1(self, monkeypatch, capsys):
        monkeypatch.setattr(cli_tasks.asset_registry, "list_assets", lambda: self.ROWS)
        monkeypatch.setattr(cli_tasks.asset_registry, "check_free_space", lambda asset: None)

        def download(*_args):
            raise RuntimeError("Download failed: HTTPSConnectionPool: Max retries exceeded")

        monkeypatch.setattr(cli_tasks.asset_registry, "download_asset", download)
        code, events = run_json(capsys, ["models", "download", "voices:kokoro", "--json"])
        assert code == cli.EXIT_FAILED
        assert next(e for e in events if e["event"] == "error")["message"].startswith("The model couldn't be")

    def test_unknown_ids_are_refused(self, monkeypatch, capsys):
        monkeypatch.setattr(cli_tasks.asset_registry, "list_assets", lambda: self.ROWS)
        assert run_json(capsys, ["models", "delete", "whisper:huge", "--json"])[0] == cli.EXIT_INVALID


class TestShortCommands:
    def test_options_lists_every_choice(self, capsys):
        code, events = run_json(capsys, ["options", "--json"])
        assert code == cli.EXIT_OK
        assert {"languages", "translation_engines", "voices", "profiles", "licences"} <= set(events[0])

    def test_version(self, capsys):
        with pytest.raises(SystemExit) as stop:
            cli.main(["--version"])
        assert stop.value.code == 0 and capsys.readouterr().out.strip() == "ccgen 1.0.0"


class TestSkill:
    def test_install_into_a_folder(self, tmp_path, capsys):
        code, events = run_json(capsys, ["skill", "install", "--dir", str(tmp_path), "--json"])
        assert code == cli.EXIT_OK
        installed = tmp_path / "ccgen"
        assert (installed / "SKILL.md").is_file() and (installed / "references" / "commands.md").is_file()
        assert events[0]["installed"] == [str(installed)]

    def test_frontmatter_names_the_folder(self):
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        front = text.split("---")[1]
        assert re.search(r"^name: ccgen$", front, re.M)
        for key in ("description:", "license:", "compatibility:", "metadata:", "version:"):
            assert key in front

    def test_every_command_line_in_the_skill_parses(self):
        """Each `ccgen ...` line in the skill's examples is a command the real parser takes."""
        parser = cli.build_parser()
        lines = list(_skill_command_lines())
        assert len(lines) >= 25
        for line in lines:
            args = [part.strip('"') for part in shlex.split(line, posix=False)[1:]]
            try:
                parser.parse_args(args)
            except SystemExit as stop:  # --version and --help end the parse with status 0
                if stop.code != 0:
                    pytest.fail(f"The skill shows a command ccgen rejects ({stop.code}): {line}")

    def test_every_option_in_the_references_exists(self):
        """Each `--option` the references name is one the parser knows."""
        known = set()
        for action in _all_actions(cli.build_parser()):
            known.update(action.option_strings)
        text = "\n".join(path.read_text(encoding="utf-8") for path in SKILL.rglob("*.md"))
        named = set(re.findall(r"(?<![\w-])(--[a-z][a-z-]+)", text))
        assert named <= known, sorted(named - known)


def _skill_command_lines():
    """Command lines in the skill's powershell examples and in its tables (`ccgen ...` in backticks)."""
    for path in SKILL.rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        for block in re.findall(r"```powershell\n(.*?)```", text, re.S):
            yield from (line.strip() for line in block.splitlines() if line.strip().startswith("ccgen "))
        for row in (line for line in text.splitlines() if line.startswith("|")):
            for code in re.findall(r"`(ccgen [^`|]+)`", row):
                if not re.search(r"[A-Z]{2,}|\.\.\.|\[", code):  # placeholders such as ID or FOLDER aren't commands
                    yield code.strip()


def _all_actions(parser):
    for action in parser._actions:
        yield action
        for sub in getattr(action, "choices", None) or {}:
            child = action.choices[sub] if isinstance(action.choices, dict) else None
            if child is not None and hasattr(child, "_actions"):
                yield from _all_actions(child)


class TestImportGuard:
    def test_the_command_line_needs_no_qt(self):
        """ccgen runs without the GUI: neither its quick commands nor its tasks load Qt."""
        code = ("import sys, ccgen.cli, ccgen.cli_tasks; "
                "bad = [m for m in sys.modules if m.split('.')[0] in ('PySide6', 'shiboken6')]; "
                "print(','.join(bad))")
        out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True)
        assert out.stdout.strip() == ""

    def test_quick_commands_load_no_engine(self):
        """settings, options, skill, and --version start without torch or the speech libraries."""
        code = ("import sys, ccgen.cli; "
                "bad = [m for m in ('torch', 'ctranslate2', 'faster_whisper', 'ccgen.core.tasks') if m in sys.modules]; "
                "print(','.join(bad))")
        out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True)
        assert out.stdout.strip() == ""


def test_a_full_drive_stops_a_model_download(monkeypatch, capsys):
    import errno

    monkeypatch.setattr(cli_tasks.asset_registry, "list_assets", lambda: TestModels.ROWS)

    def full(_asset):
        raise OSError(errno.ENOSPC, "The drive for D:\Models is full. It needs about 354 MB free.")

    monkeypatch.setattr(cli_tasks.asset_registry, "check_free_space", full)
    monkeypatch.setattr(cli_tasks.asset_registry, "download_asset", lambda *_args: pytest.fail("downloaded"))
    code, events = run_json(capsys, ["models", "download", "voices:kokoro", "--json"])
    assert code == cli.EXIT_FAILED
    assert "354 MB" in next(e for e in events if e["event"] == "error")["message"]
