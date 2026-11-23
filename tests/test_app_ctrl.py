# test_app_ctrl.py - the window area the shared AppWindow component asks the app controller for,
# "Show in folder" going through the shell, what a moved file says, the log and the clipboard,
# taskbar progress, and notifications while the app is in the background

import inspect
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QCoreApplication, QPoint, QRect, Qt
from PySide6.QtWidgets import QSystemTrayIcon

from ccgen.controllers import app_ctrl
from ccgen.controllers.app_ctrl import AppController
from ccgen.core.errors import missing_file_message
from ccgen.services import notifier as notifier_module
from ccgen.services.notifier import Notifier
from ccgen.services.taskbar import ERROR, INDETERMINATE, NORMAL, PAUSED


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


def _notices(controller: AppController) -> list[str]:
    """Every message the controller shows in the window's toast from now on."""
    notices: list[str] = []
    controller.notice.connect(notices.append)
    return notices


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

    def test_a_moved_file_says_so(self, controller, shell, opened, tmp_path):
        notices = _notices(controller)
        controller.revealFile(str(tmp_path / "movie_ur.srt"))
        shell.ILCreateFromPathW.assert_not_called()
        assert opened == []
        assert notices == [missing_file_message(str(tmp_path / "movie_ur.srt"), queued=False)]
        assert notices[0].startswith("movie_ur.srt isn't there any more.")

    def test_no_path_does_nothing(self, controller, shell, opened):
        notices = _notices(controller)
        controller.revealFile("")
        shell.ILCreateFromPathW.assert_not_called()
        assert opened == [] and notices == []

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


@pytest.fixture
def opened_urls(monkeypatch):
    """The local paths QDesktopServices is asked to open; openUrl reports success."""
    opened: list[str] = []

    def open_url(url) -> bool:
        opened.append(os.path.normpath(url.toLocalFile()))
        return True

    monkeypatch.setattr(app_ctrl, "QDesktopServices", SimpleNamespace(openUrl=open_url))
    return opened


class TestOpenFolder:
    def test_opens_an_existing_folder(self, controller, opened_urls, tmp_path):
        controller.openFolder(str(tmp_path))
        assert opened_urls == [str(tmp_path)]

    def test_a_moved_folder_says_so(self, controller, opened_urls, tmp_path):
        notices = _notices(controller)
        controller.openFolder(str(tmp_path / "subs"))
        assert opened_urls == []
        assert notices == [missing_file_message(str(tmp_path / "subs"), queued=False)]

    def test_no_path_does_nothing(self, controller, opened_urls):
        notices = _notices(controller)
        controller.openFolder("")
        assert opened_urls == [] and notices == []


class TestLogAndClipboard:
    def test_open_log_opens_the_log_file(self, controller, opened_urls, tmp_path, monkeypatch):
        log_file = tmp_path / "ccgen.log"
        log_file.write_text("started", encoding="utf-8")
        monkeypatch.setattr(app_ctrl, "get_log_file", lambda: str(log_file))
        controller.openLog()
        assert opened_urls == [str(log_file)]

    def test_without_a_log_file_the_logs_folder_opens(self, controller, opened_urls, tmp_path, monkeypatch):
        monkeypatch.setattr(app_ctrl, "get_log_file", lambda: str(tmp_path / "ccgen.log"))
        monkeypatch.setattr(app_ctrl, "get_logs_dir", lambda: str(tmp_path))
        controller.openLog()
        assert opened_urls == [str(tmp_path)]

    def test_a_log_file_no_app_opens_falls_back_to_the_folder(self, controller, tmp_path, monkeypatch):
        log_file = tmp_path / "ccgen.log"
        log_file.write_text("started", encoding="utf-8")
        tried: list[str] = []

        def open_url(url) -> bool:
            tried.append(os.path.normpath(url.toLocalFile()))
            return False

        monkeypatch.setattr(app_ctrl, "QDesktopServices", SimpleNamespace(openUrl=open_url))
        monkeypatch.setattr(app_ctrl, "get_log_file", lambda: str(log_file))
        monkeypatch.setattr(app_ctrl, "get_logs_dir", lambda: str(tmp_path))
        controller.openLog()
        assert tried == [str(log_file), str(tmp_path)]

    def test_copy_text_puts_it_on_the_clipboard(self, controller, monkeypatch):
        clipboard = MagicMock()
        monkeypatch.setattr(_TwoScreens, "clipboard", staticmethod(lambda: clipboard), raising=False)
        controller.copyText("CUDA out of memory")
        clipboard.setText.assert_called_once_with("CUDA out of memory")


class _FakeTaskbar:
    """Records what the controller shows on the taskbar button."""

    def __init__(self):
        self.hwnd = 0
        self.calls: list[tuple] = []
        self.closed = False

    def attach(self, hwnd: int) -> None:
        self.hwnd = hwnd

    def update(self, fraction, state=None) -> None:
        self.calls.append((fraction, state))

    def close(self) -> None:
        self.closed = True


class _FakeWindow:
    """The main window's state and the calls that bring it forward."""

    def __init__(self, states=Qt.WindowState.WindowNoState):
        self.states = states
        self.calls: list[str] = []

    def winId(self) -> int:
        return 0x1234

    def windowStates(self):
        return self.states

    def setWindowStates(self, states) -> None:
        self.states = states

    def show(self) -> None:
        self.calls.append("show")

    def raise_(self) -> None:
        self.calls.append("raise")

    def requestActivate(self) -> None:
        self.calls.append("activate")


class TestWindow:
    @pytest.fixture
    def taskbar(self, monkeypatch):
        fake = _FakeTaskbar()
        monkeypatch.setattr(app_ctrl, "TaskbarProgress", lambda: fake)
        return fake

    def test_progress_before_the_window_exists_is_ignored(self, controller, taskbar):
        controller.setTaskbarProgress(0.5, "normal")
        assert taskbar.calls == []

    @pytest.mark.parametrize("state, flag", [("normal", NORMAL), ("paused", PAUSED), ("error", ERROR),
                                             ("indeterminate", INDETERMINATE)])
    def test_progress_shows_on_the_windows_taskbar_button(self, controller, taskbar, state, flag):
        controller.attach_window(_FakeWindow())
        controller.setTaskbarProgress(0.25, state)
        assert taskbar.hwnd == 0x1234
        assert taskbar.calls == [(0.25, flag)]

    def test_none_clears_the_button_and_an_unknown_state_is_ignored(self, controller, taskbar):
        controller.attach_window(_FakeWindow())
        controller.setTaskbarProgress(1.0, "none")
        controller.setTaskbarProgress(0.5, "green")
        assert taskbar.calls == [(None, None)]

    def test_shutdown_clears_the_button(self, controller, taskbar):
        controller.attach_window(_FakeWindow())
        controller.shutdown()
        assert taskbar.closed

    def test_bring_to_front_restores_a_minimized_window_as_it_was(self, controller, taskbar):
        window = _FakeWindow(Qt.WindowState.WindowMinimized | Qt.WindowState.WindowMaximized)
        controller.attach_window(window)
        controller.bring_to_front()
        assert window.states == Qt.WindowState.WindowMaximized
        assert window.calls == ["show", "raise", "activate"]

    def test_bring_to_front_leaves_an_open_window_as_it_is(self, controller, taskbar):
        window = _FakeWindow(Qt.WindowState.WindowMaximized)
        controller.attach_window(window)
        controller.bring_to_front()
        assert window.states == Qt.WindowState.WindowMaximized
        assert window.calls == ["show", "raise", "activate"]

    def test_bring_to_front_without_a_window_does_nothing(self, controller):
        controller.bring_to_front()

    @pytest.mark.parametrize("state, shown", [(Qt.ApplicationState.ApplicationActive, False),
                                              (Qt.ApplicationState.ApplicationInactive, True),
                                              (Qt.ApplicationState.ApplicationHidden, True)])
    def test_notifications_only_while_the_app_is_in_the_background(self, controller, monkeypatch, state, shown):
        monkeypatch.setattr(_TwoScreens, "applicationState", staticmethod(lambda: state), raising=False)
        notifier = MagicMock()
        monkeypatch.setattr(controller, "_notifier", notifier)
        controller.notify("Translate finished", "3 files done.")
        expected = [(("Translate finished", "3 files done."),)] if shown else []
        assert notifier.notify.call_args_list == expected


class _FakeSignal:
    def __init__(self):
        self.slots: list = []

    def connect(self, slot) -> None:
        self.slots.append(slot)

    def emit(self, *args) -> None:
        for slot in self.slots:
            slot(*args)


class _FakeTray:
    """Stands in for QSystemTrayIcon: records the icons made and the messages shown."""

    MessageIcon = QSystemTrayIcon.MessageIcon
    available = True
    made: list = []

    def __init__(self, icon, parent):
        self.icon = icon
        self.visible = False
        self.deleted = False
        self.tooltip = ""
        self.messages: list[tuple[str, str]] = []
        self.messageClicked = _FakeSignal()
        self.activated = _FakeSignal()
        _FakeTray.made.append(self)

    @classmethod
    def isSystemTrayAvailable(cls) -> bool:
        return cls.available

    @classmethod
    def supportsMessages(cls) -> bool:
        return cls.available

    def setToolTip(self, text: str) -> None:
        self.tooltip = text

    def show(self) -> None:
        self.visible = True

    def hide(self) -> None:
        self.visible = False

    def deleteLater(self) -> None:
        self.deleted = True

    def showMessage(self, title, message, icon, ms) -> None:
        self.messages.append((title, message))


class _NoGuiApp:
    """QGuiApplication for a test run without a window system."""

    @staticmethod
    def instance():
        return None

    @staticmethod
    def windowIcon():
        return "app icon"


class TestNotifier:
    @pytest.fixture
    def tray(self, monkeypatch):
        monkeypatch.setattr(_FakeTray, "made", [])
        monkeypatch.setattr(_FakeTray, "available", True)
        monkeypatch.setattr(notifier_module, "QSystemTrayIcon", _FakeTray)
        monkeypatch.setattr(notifier_module, "QGuiApplication", _NoGuiApp)
        return _FakeTray

    @pytest.fixture
    def shown(self):
        return []

    @pytest.fixture
    def notifier(self, tray, shown):
        if QCoreApplication.instance() is None:
            QCoreApplication([])
        return Notifier(lambda: shown.append("window"))

    def test_the_icon_appears_with_the_first_notification(self, notifier, tray):
        assert tray.made == []
        assert notifier.notify("Done", "2 files done.")
        assert notifier.notify("Done", "1 file failed.")
        assert len(tray.made) == 1
        icon = tray.made[0]
        assert icon.visible and icon.icon == "app icon" and icon.tooltip == "CC-Gen-Ultimate"
        assert icon.messages == [("Done", "2 files done."), ("Done", "1 file failed.")]

    def test_a_click_on_the_notification_brings_the_window_forward_and_removes_the_icon(self, notifier, tray,
                                                                                        shown):
        notifier.notify("Done", "2 files done.")
        icon = tray.made[0]
        icon.messageClicked.emit()
        assert shown == ["window"]
        assert not icon.visible and icon.deleted

    def test_a_click_on_the_icon_does_the_same(self, notifier, tray, shown):
        notifier.notify("Done", "2 files done.")
        tray.made[0].activated.emit(QSystemTrayIcon.ActivationReason.Trigger)
        assert shown == ["window"]
        assert tray.made[0].deleted

    def test_coming_back_to_the_app_removes_the_icon(self, notifier, tray):
        notifier.notify("Done", "2 files done.")
        notifier._on_state(Qt.ApplicationState.ApplicationInactive)
        assert tray.made[0].visible
        notifier._on_state(Qt.ApplicationState.ApplicationActive)
        assert not tray.made[0].visible and tray.made[0].deleted
        notifier.notify("Done", "Again.")
        assert len(tray.made) == 2

    def test_without_a_notification_area_nothing_is_shown(self, notifier, tray):
        tray.available = False
        assert notifier.notify("Done", "2 files done.") is False
        assert tray.made == []
