# test_settings.py — unit tests for ccgen.utils.settings

import json

import ccgen.utils.settings as settings_module
from ccgen.config.defaults import get_default_settings
from ccgen.utils.settings import (
    get_settings_file,
    load_settings,
    merge_settings,
    save_settings,
)


def _redirect_settings_file(monkeypatch, tmp_path):
    """Point get_settings_file at a temp path so tests never touch real config."""
    fake_path = str(tmp_path / "settings.json")
    monkeypatch.setattr(settings_module, "get_settings_file", lambda: fake_path)
    return fake_path


class TestGetSettingsFile:
    def test_dev_mode_returns_path_next_to_module(self):
        result = get_settings_file()
        assert result.endswith("settings.json")

    def test_frozen_mode_uses_appdata(self, monkeypatch, tmp_path):
        monkeypatch.setattr(settings_module.sys, "frozen", True, raising=False)
        monkeypatch.setenv("APPDATA", str(tmp_path))
        result = get_settings_file()
        assert result == str(tmp_path / "CC-Gen-Ultimate" / "settings.json")
        assert (tmp_path / "CC-Gen-Ultimate").is_dir()


class TestLoadSettings:
    def test_missing_file_returns_defaults(self, monkeypatch, tmp_path):
        _redirect_settings_file(monkeypatch, tmp_path)
        assert load_settings() == get_default_settings()

    def test_loads_existing_file_merged_with_defaults(self, monkeypatch, tmp_path):
        fake_path = _redirect_settings_file(monkeypatch, tmp_path)
        with open(fake_path, "w", encoding="utf-8") as fh:
            json.dump({"model": {"name": "small"}}, fh)
        result = load_settings()
        assert result["model"]["name"] == "small"
        assert result["model"]["device"] == get_default_settings()["model"]["device"]

    def test_corrupt_json_falls_back_to_defaults(self, monkeypatch, tmp_path):
        fake_path = _redirect_settings_file(monkeypatch, tmp_path)
        with open(fake_path, "w", encoding="utf-8") as fh:
            fh.write("{not valid json")
        assert load_settings() == get_default_settings()

    def test_missing_keys_filled_from_defaults(self, monkeypatch, tmp_path):
        fake_path = _redirect_settings_file(monkeypatch, tmp_path)
        with open(fake_path, "w", encoding="utf-8") as fh:
            json.dump({}, fh)
        assert load_settings() == get_default_settings()

    def test_old_files_move_untouched_model_defaults_to_automatic(self, monkeypatch, tmp_path):
        fake_path = _redirect_settings_file(monkeypatch, tmp_path)
        with open(fake_path, "w", encoding="utf-8") as fh:
            json.dump({
                "model": {"name": "base"},
                "translation": {"engine": "nllb"},
                "transliteration": {"engine": "rule"},
                "dubbing": {"mode": "xtts", "xtts_terms_accepted": True},
            }, fh)
        result = load_settings()
        # Old defaults become Automatic; a model picked by hand (NLLB) and answers stay.
        assert (result["model"]["name"], result["transliteration"]["engine"], result["dubbing"]["mode"]) == (
            "auto", "auto", "auto")
        assert result["translation"]["engine"] == "nllb"
        assert result["dubbing"]["xtts_terms_accepted"] is True
        assert result["version"] == 2

    def test_current_files_are_not_migrated_again(self, monkeypatch, tmp_path):
        fake_path = _redirect_settings_file(monkeypatch, tmp_path)
        with open(fake_path, "w", encoding="utf-8") as fh:
            json.dump({"version": 2, "model": {"name": "base"}}, fh)
        assert load_settings()["model"]["name"] == "base"

    def test_drops_options_removed_since_the_file_was_written(self, monkeypatch, tmp_path):
        fake_path = _redirect_settings_file(monkeypatch, tmp_path)
        with open(fake_path, "w", encoding="utf-8") as fh:
            json.dump({
                "translation": {"enabled": True, "target_lang": "ur"},
                "retired_section": {"x": 1},
                "ui": "not-a-section",
            }, fh)
        result = load_settings()
        assert "enabled" not in result["translation"]
        assert result["translation"]["target_lang"] == "ur"
        assert "retired_section" not in result
        assert result["ui"] == get_default_settings()["ui"]


class TestSaveSettings:
    def test_round_trip_save_and_load(self, monkeypatch, tmp_path):
        _redirect_settings_file(monkeypatch, tmp_path)
        custom = get_default_settings()
        custom["ui"]["theme"] = "dark"
        assert save_settings(custom) is True
        assert load_settings() == custom

    def test_writes_readable_json_file(self, monkeypatch, tmp_path):
        fake_path = _redirect_settings_file(monkeypatch, tmp_path)
        save_settings({"a": 1})
        with open(fake_path, "r", encoding="utf-8") as fh:
            assert json.load(fh) == {"a": 1}

    def test_returns_false_on_write_failure(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            settings_module, "get_settings_file", lambda: str(tmp_path / "nodir" / "settings.json")
        )
        assert save_settings({"a": 1}) is False


class TestMergeSettings:
    def test_overrides_take_precedence(self):
        defaults = {"a": 1, "b": 2}
        result = merge_settings(defaults, {"a": 99})
        assert result == {"a": 99, "b": 2}

    def test_missing_override_keys_keep_default(self):
        defaults = {"model": {"name": "base", "device": "cpu"}}
        result = merge_settings(defaults, {"model": {"name": "small"}})
        assert result == {"model": {"name": "small", "device": "cpu"}}

    def test_nested_dict_deep_merge(self):
        defaults = {"a": {"x": {"y": 1, "z": 2}}}
        overrides = {"a": {"x": {"y": 9}}}
        result = merge_settings(defaults, overrides)
        assert result == {"a": {"x": {"y": 9, "z": 2}}}

    def test_non_dict_override_replaces_dict_default(self):
        defaults = {"a": {"x": 1}}
        overrides = {"a": "not-a-dict"}
        result = merge_settings(defaults, overrides)
        assert result == {"a": "not-a-dict"}

    def test_empty_overrides_returns_defaults_copy(self):
        defaults = {"a": 1}
        result = merge_settings(defaults, {})
        assert result == defaults
        assert result is not defaults
