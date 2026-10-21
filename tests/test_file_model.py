# test_file_model.py - unit tests for ccgen.models.file_model.MediaFileModel

import pytest
from PySide6.QtCore import QCoreApplication

from ccgen.models.file_model import MediaFileModel, effective_language, has_text


@pytest.fixture(scope="session")
def qt_app():
    """Provide a single QCoreApplication instance for headless Qt object tests."""
    app = QCoreApplication.instance() or QCoreApplication([])
    yield app


@pytest.fixture
def two_files(tmp_path):
    """Create two small real files on disk and return their paths."""
    first = tmp_path / "clip_one.mp4"
    second = tmp_path / "clip_two.wav"
    first.write_bytes(b"a" * 1024)
    second.write_bytes(b"b" * 2048)
    return [str(first), str(second)]


@pytest.fixture
def model(qt_app):
    return MediaFileModel()


class TestAddFiles:
    def test_adds_files_and_updates_count(self, model, two_files):
        model.addFiles(two_files)
        assert model.count == 2
        assert model.rowCount() == 2

    def test_role_data_matches_file_metadata(self, model, two_files):
        model.addFiles(two_files)
        index = model.index(0)
        assert model.data(index, MediaFileModel.NameRole) == "clip_one.mp4"
        assert model.data(index, MediaFileModel.PathRole) == two_files[0]
        assert model.data(index, MediaFileModel.ExtRole) == "MP4"
        assert model.data(index, MediaFileModel.StatusRole) == "pending"
        assert model.data(index, MediaFileModel.SelectedRole) is False

    def test_size_role_is_formatted_string(self, model, two_files):
        model.addFiles(two_files)
        index = model.index(0)
        assert model.data(index, MediaFileModel.SizeRole) == "1.0 KB"

    def test_total_size_reflects_all_files(self, model, two_files):
        model.addFiles(two_files)
        assert model.totalSize == "3.0 KB"

    def test_missing_file_is_skipped(self, model, tmp_path):
        missing = str(tmp_path / "does_not_exist.mp4")
        model.addFiles([missing])
        assert model.count == 0

    def test_duplicate_path_is_not_added_twice(self, model, two_files):
        model.addFiles([two_files[0]])
        model.addFiles([two_files[0]])
        assert model.count == 1

    def test_invalid_index_returns_none(self, model, two_files):
        model.addFiles(two_files)
        out_of_range = model.index(5)
        assert model.data(out_of_range, MediaFileModel.NameRole) is None


class TestRemoveAt:
    def test_removes_item_and_updates_count(self, model, two_files):
        model.addFiles(two_files)
        model.removeAt(0)
        assert model.count == 1
        assert model.getPaths() == [two_files[1]]

    def test_out_of_range_row_is_noop(self, model, two_files):
        model.addFiles(two_files)
        model.removeAt(99)
        assert model.count == 2

    def test_removing_shifts_selection_indices(self, model, two_files):
        model.addFiles(two_files)
        model.toggleSelection(1)
        model.removeAt(0)
        assert model.selectedCount == 1
        index = model.index(0)
        assert model.data(index, MediaFileModel.SelectedRole) is True


class TestRemoveSelected:
    def test_removes_only_selected_rows(self, model, two_files):
        model.addFiles(two_files)
        model.toggleSelection(0)
        model.removeSelected()
        assert model.count == 1
        assert model.getPaths() == [two_files[1]]
        assert model.selectedCount == 0

    def test_no_selection_removes_nothing(self, model, two_files):
        model.addFiles(two_files)
        model.removeSelected()
        assert model.count == 2


class TestSelectAll:
    def test_selects_every_row(self, model, two_files):
        model.addFiles(two_files)
        model.selectAll()
        assert model.selectedCount == 2

    def test_empty_model_selects_nothing(self, model):
        model.selectAll()
        assert model.selectedCount == 0


class TestClearSelection:
    def test_clears_all_selected_rows(self, model, two_files):
        model.addFiles(two_files)
        model.selectAll()
        model.clearSelection()
        assert model.selectedCount == 0


class TestToggleSelection:
    def test_toggle_on_then_off(self, model, two_files):
        model.addFiles(two_files)
        model.toggleSelection(0)
        assert model.selectedCount == 1
        model.toggleSelection(0)
        assert model.selectedCount == 0


class TestGetPaths:
    def test_returns_paths_in_insertion_order(self, model, two_files):
        model.addFiles(two_files)
        assert model.getPaths() == two_files

    def test_empty_model_returns_empty_list(self, model):
        assert model.getPaths() == []


class TestClearAll:
    def test_removes_all_files_and_resets_selection(self, model, two_files):
        model.addFiles(two_files)
        model.selectAll()
        model.clearAll()
        assert model.count == 0
        assert model.selectedCount == 0
        assert model.totalSize == "0.0 B"


class TestSetStatus:
    def test_updates_status_for_row(self, model, two_files):
        model.addFiles(two_files)
        model.setStatus(0, "done")
        index = model.index(0)
        assert model.data(index, MediaFileModel.StatusRole) == "done"


class TestBulkOperations:
    def test_add_scanned_skips_duplicates_in_one_insert(self, model, two_files):
        inserts = []
        model.rowsInserted.connect(lambda *args: inserts.append(args))
        added = model.addScanned([(two_files[0], 1024), (two_files[1], 2048), (two_files[0], 1024)])
        assert added == 2
        assert len(inserts) == 1
        assert model.addScanned([(two_files[0], 1024)]) == 0

    def test_thousands_of_rows_add_and_remove_quickly(self, model, tmp_path):
        import time
        entries = [(str(tmp_path / f"clip{i}.mp4"), 10) for i in range(5000)]
        start = time.perf_counter()
        model.addScanned(entries)
        model.selectAll()
        model.removeSelected()
        assert model.count == 0
        assert time.perf_counter() - start < 3.0

    def test_processing_row_is_not_removed(self, model, two_files):
        model.addFiles(two_files)
        model.set_run_state(two_files[0], status="processing")
        model.clearAll()
        assert model.getPaths() == [two_files[0]]

    def test_remove_finished_keeps_other_rows(self, model, two_files):
        model.addFiles(two_files)
        model.set_run_state(two_files[0], status="done")
        model.removeFinished()
        assert model.getPaths() == [two_files[1]]

    def test_runnable_paths_prefers_unfinished(self, model, two_files):
        model.addFiles(two_files)
        model.set_run_state(two_files[0], status="done")
        assert model.runnable_paths() == [two_files[1]]
        model.set_run_state(two_files[1], status="done")
        assert model.runnable_paths() == two_files

    def test_kind_role(self, model, two_files):
        model.addFiles(two_files)
        assert model.data(model.index(0), MediaFileModel.KindRole) == "video"
        assert model.data(model.index(1), MediaFileModel.KindRole) == "audio"


class TestTextLanguage:
    @pytest.fixture
    def subtitles(self, tmp_path):
        paths = []
        for name in ("one.srt", "two_en.srt", "clip.mp4"):
            (tmp_path / name).write_text("")
            paths.append(str(tmp_path / name))
        return paths

    def test_language_comes_from_the_name_and_a_choice_overrides_it(self, model, subtitles):
        model.addFiles(subtitles)
        assert [effective_language(model.item(p)) for p in subtitles] == ["", "en", ""]
        model.setChosenLanguage(1, "fr")
        assert effective_language(model.item(subtitles[1])) == "fr"
        model.setChosenLanguage(1, "")
        assert effective_language(model.item(subtitles[1])) == "en"

    def test_choice_applies_to_every_selected_row_with_text(self, model, subtitles):
        model.addFiles(subtitles)
        changes = []
        model.inputsChanged.connect(lambda: changes.append(True))
        model.selectAll()
        model.setChosenLanguage(0, "ur")
        assert [model.item(p)["chosen_language"] for p in subtitles] == ["ur", "ur", ""]
        assert changes == [True]

    def test_choice_on_an_unselected_row_changes_only_that_row(self, model, subtitles):
        model.addFiles(subtitles)
        model.setSingle(1)
        model.setChosenLanguage(0, "ur")
        assert [model.item(p)["chosen_language"] for p in subtitles] == ["ur", "", ""]

    def test_pairing_resets_the_choice(self, model, subtitles):
        model.addFiles(subtitles)
        model.setCompanion(2, subtitles[1])
        assert has_text(model.item(subtitles[2]))
        model.setChosenLanguage(2, "de")
        model.setCompanion(2, subtitles[0])
        item = model.item(subtitles[2])
        assert item["chosen_language"] == "" and item["language"] == ""
