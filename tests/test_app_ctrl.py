# test_app_ctrl.py - the window area the shared AppWindow component asks the app controller for,
# and "Show in folder" going through the shell

import inspect
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QCoreApplication, QPoint, QRect

from ccgen.controllers import app_ctrl
from ccgen.controllers.app_ctrl import AppController


class _TwoScreens:
    """Stands in for QGuiApplication: two 1920x1080 screens side by side, taskbars at the bottom."""

    left = SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 1920, 1040))
    right = SimpleNamespace(availableGeometry=lambda: QRect(1920, 0, 1920, 1040))

    @classmethod
    def screenAt(cls, point: QPoint):
        if not 0 <= point.y() < 1080:
            return None
        if 0 <= point.x() < 1920:
            return cls.left
        if 1920 <= point.x() < 3840:
            return cls.right
        return None

    @classmethod
    def primaryScreen(cls):
        return cls.left


@pytest.fixture
def controller(monkeypatch):
    if QCoreApplication.instance() is None:
        QCoreApplication([])
    monkeypatch.setattr(app_ctrl, "load_settings", lambda: {})
    monkeypatch.setattr(app_ctrl, "_detect_system_theme", lambda: "light")
    monkeypatch.setattr(app_ctrl, "QGuiApplication", _TwoScreens)
    return AppController()


class TestAvailableGeometry:
    def test_the_free_area_of_the_screen_under_the_point(self, controller):
        assert controller.availableGeometry(2500, 400) == QRect(1920, 0, 1920, 1040)
        assert controller.availableGeometry(100, 100) == QRect(0, 0, 1920, 1040)

    def test_a_point_off_every_screen_uses_the_primary_one(self, controller):
        assert controller.availableGeometry(-5000, 200) == QRect(0, 0, 1920, 1040)


class TestRevealFile:
    """The shell selects the file; no program is started by name, which Windows would look up in
    the app's own folder and the current folder first."""

    @pytest.fixture
    def shell(self, monkeypatch):
        fake = MagicMock()
        fake.ILCreateFromPathW.return_value = 1234
        monkeypatch.setattr(app_ctrl, "_shell32", fake)
        return fake

    @pytest.fixture
    def opened(self, controller, monkeypatch):
        folders: list[str] = []
        monkeypatch.setattr(controller, "openFolder", folders.append)
        return folders

    def test_selects_the_file_in_explorer(self, controller, shell, opened, tmp_path):
        target = tmp_path / "talk, final.mp4"  # a comma broke explorer's /select, argument
        target.write_bytes(b"x")
        controller.revealFile(str(target))
        shell.ILCreateFromPathW.assert_called_once_with(os.path.normpath(str(target)))
        shell.SHOpenFolderAndSelectItems.assert_called_once_with(1234, 0, None, 0)
        shell.ILFree.assert_called_once_with(1234)
        assert opened == []

    def test_a_missing_file_does_nothing(self, controller, shell, opened, tmp_path):
        controller.revealFile(str(tmp_path / "gone.mp4"))
        controller.revealFile("")
        shell.ILCreateFromPathW.assert_not_called()
        assert opened == []

    def test_a_shell_failure_opens_the_folder_instead(self, controller, shell, opened, tmp_path):
        target = tmp_path / "a.srt"
        target.write_bytes(b"x")
        shell.SHOpenFolderAndSelectItems.side_effect = OSError("[WinError -2147024894] not found")
        controller.revealFile(str(target))
        shell.ILFree.assert_called_once_with(1234)
        assert opened == [str(tmp_path)]

    def test_no_shell_item_opens_the_folder_instead(self, controller, shell, opened, tmp_path):
        target = tmp_path / "a.srt"
        target.write_bytes(b"x")
        shell.ILCreateFromPathW.return_value = None
        controller.revealFile(str(target))
        shell.SHOpenFolderAndSelectItems.assert_not_called()
        assert opened == [str(tmp_path)]

    def test_the_shell_functions_are_declared(self):
        assert app_ctrl._shell32.SHOpenFolderAndSelectItems.restype is app_ctrl.ctypes.HRESULT
        assert app_ctrl._shell32.ILCreateFromPathW.restype is app_ctrl.ctypes.c_void_p

    def test_no_program_is_started_by_name(self):
        source = inspect.getsource(app_ctrl)
        assert "subprocess" not in source and "Popen" not in source and "os.system" not in source
