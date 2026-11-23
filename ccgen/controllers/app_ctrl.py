# app_ctrl.py - main window controller (theme, app info, desktop shell actions, logs, taskbar,
# notifications)

import ctypes
import logging
import os
import winreg
from ctypes import wintypes
from typing import Optional

from PySide6.QtCore import Property, QObject, QPoint, QRect, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QGuiApplication, QWindow

from ccgen.config.defaults import AppInfo
from ccgen.core.errors import missing_file_message
from ccgen.services.notifier import Notifier
from ccgen.services.taskbar import ERROR, INDETERMINATE, NORMAL, PAUSED, TaskbarProgress
from ccgen.utils.helpers import to_local_path
from ccgen.utils.logging import clear_logs, get_log_file, get_logs_dir
from ccgen.utils.settings import load_settings, save_settings

_log = logging.getLogger(__name__)

# setTaskbarProgress's states, as the taskbar button shows them; "none" clears the button.
_TASKBAR_STATES = {"normal": NORMAL, "paused": PAUSED, "error": ERROR, "indeterminate": INDETERMINATE}

# "Show in folder" goes through the shell. Starting explorer.exe by name would let Windows find an
# explorer.exe in the app's folder or the current folder first, and "/select," breaks on commas.
_shell32 = ctypes.WinDLL("shell32")
_shell32.ILCreateFromPathW.argtypes = [wintypes.LPCWSTR]
_shell32.ILCreateFromPathW.restype = ctypes.c_void_p
_shell32.SHOpenFolderAndSelectItems.argtypes = [ctypes.c_void_p, wintypes.UINT, ctypes.c_void_p, wintypes.DWORD]
_shell32.SHOpenFolderAndSelectItems.restype = ctypes.HRESULT  # raises OSError for a failure code
_shell32.ILFree.argtypes = [ctypes.c_void_p]
_shell32.ILFree.restype = None


def _detect_system_theme() -> str:
    """Read the Windows registry to determine the current light or dark app mode."""
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return "light" if value == 1 else "dark"
    except OSError:
        return "light"


def _select_in_explorer(path: str) -> None:
    """Open File Explorer at the file's folder with the file selected; raises OSError on failure.

    The shell call needs COM, which Qt has already initialised on the GUI thread.
    """
    item = _shell32.ILCreateFromPathW(path)
    if not item:
        raise OSError(f"File Explorer can't find {path}")
    try:
        _shell32.SHOpenFolderAndSelectItems(item, 0, None, 0)
    finally:
        _shell32.ILFree(item)


class AppController(QObject):
    """Exposes theme, app metadata, desktop shell actions, taskbar progress, and notifications to QML."""

    themeChanged = Signal(str)
    # A one-off message for the main window's toast ("movie_ur.srt isn't there any more...").
    notice = Signal(str)
    # The tab a launch's files went to: "generate", "translate", "transliterate", "dub", or "workflow".
    openTab = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._preference = str(load_settings().get("ui", {}).get("theme", "system"))
        self._theme = self._resolve(self._preference)
        self._window: Optional[QWindow] = None
        self._taskbar: Optional[TaskbarProgress] = None
        self._notifier = Notifier(self.bring_to_front, self)

    # ── Properties ───────────────────────────────────────────────────────────

    @Property(str, notify=themeChanged)
    def currentTheme(self) -> str:
        """Resolved theme name: 'light' or 'dark'."""
        return self._theme

    @Property(str, constant=True)
    def appName(self) -> str:
        """Application display name."""
        return AppInfo.APP_NAME

    @Property(str, constant=True)
    def appVersion(self) -> str:
        """Application version string."""
        return AppInfo.APP_VERSION

    @Property(str, constant=True)
    def appDescription(self) -> str:
        """Short application description."""
        return AppInfo.APP_DESCRIPTION

    @Property(str, constant=True)
    def appAuthor(self) -> str:
        """Application author."""
        return AppInfo.APP_AUTHOR

    # ── Theme ────────────────────────────────────────────────────────────────

    @Slot()
    def detectTheme(self) -> None:
        """Follow a Windows light/dark switch while the theme preference is 'system'."""
        self._set_theme(self._resolve(self._preference))

    @Slot(str)
    def applyTheme(self, theme: str) -> None:
        """Apply and persist a theme choice ('system', 'light', 'dark')."""
        self._preference = theme
        self._set_theme(self._resolve(theme))
        settings = load_settings()
        settings.setdefault("ui", {})["theme"] = theme
        save_settings(settings)

    # ── Windows ──────────────────────────────────────────────────────────────

    @Slot(int, int, result=QRect)
    def availableGeometry(self, x: int, y: int) -> QRect:
        """The area windows may use (without the taskbar) on the screen at (x, y), else the primary screen.

        AppWindow centres, fits, and maximizes each window within it.
        """
        screen = QGuiApplication.screenAt(QPoint(x, y)) or QGuiApplication.primaryScreen()
        return screen.availableGeometry()

    def attach_window(self, window: QWindow) -> None:
        """Use this main window for taskbar progress, notifications, and bring_to_front()."""
        self._window = window
        if self._taskbar is None:
            self._taskbar = TaskbarProgress()
        self._taskbar.attach(int(window.winId()))

    def bring_to_front(self) -> None:
        """Show the main window in front, restoring it when minimized (a later launch, a notification click)."""
        window = self._window
        if window is None:
            return
        states = window.windowStates()
        if states & Qt.WindowState.WindowMinimized:
            window.setWindowStates(states & ~Qt.WindowState.WindowMinimized)
        window.show()
        window.raise_()
        window.requestActivate()

    def shutdown(self) -> None:
        """Clear the taskbar button and remove a notification's icon (on exit)."""
        self._notifier.dismiss()
        if self._taskbar is not None:
            self._taskbar.close()
            self._taskbar = None

    @Slot(float, str)
    def setTaskbarProgress(self, fraction: float, state: str) -> None:
        """Show a run's progress (0..1) on the taskbar button.

        `state` is "normal", "paused", "error", "indeterminate" (fraction ignored), or "none" to clear it.
        """
        if self._taskbar is None:
            return
        if state == "none":
            self._taskbar.update(None)
            return
        flag = _TASKBAR_STATES.get(state)
        if flag is None:
            _log.warning("Unknown taskbar progress state %r", state)
            return
        self._taskbar.update(fraction, flag)

    @Slot(str, str)
    def notify(self, title: str, message: str) -> None:
        """Show a Windows notification, only while the app is in the background (none of its windows active)."""
        if QGuiApplication.applicationState() == Qt.ApplicationState.ApplicationActive:
            return
        self._notifier.notify(title, message)

    # ── Desktop shell actions ────────────────────────────────────────────────

    @Slot(str)
    def openFolder(self, path: str) -> None:
        """Open a folder in File Explorer, or say (notice) that it isn't there any more."""
        if not path:
            return
        if not os.path.isdir(path):
            self.notice.emit(missing_file_message(path, queued=False))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    @Slot(str)
    def revealFile(self, path: str) -> None:
        """Open File Explorer with the given file selected, or say (notice) that it isn't there any more."""
        if not path:
            return
        if not os.path.exists(path):
            self.notice.emit(missing_file_message(path, queued=False))
            return
        try:
            _select_in_explorer(os.path.normpath(path))
        except OSError:
            _log.warning("Could not reveal %s in Explorer", path, exc_info=True)
            self.openFolder(os.path.dirname(path))

    @Slot(str, result=str)
    def localPath(self, url: str) -> str:
        """Convert a file:// URL from a QML dialog into a local Windows path."""
        return to_local_path(url)

    @Slot(str, result=str)
    def folderUrl(self, path: str) -> str:
        """The file:// URL of the folder holding `path`, for starting a QML dialog there."""
        return QUrl.fromLocalFile(os.path.dirname(path)).toString() if path else ""

    @Slot(str)
    def copyText(self, text: str) -> None:
        """Put text on the clipboard (a file's error details, say)."""
        QGuiApplication.clipboard().setText(text)

    @Slot()
    def openLog(self) -> None:
        """Open the current log file in the default text editor, or the logs folder when there is none yet."""
        log_file = get_log_file()
        if os.path.isfile(log_file) and QDesktopServices.openUrl(QUrl.fromLocalFile(log_file)):
            return
        self.openLogsFolder()

    @Slot()
    def openLogsFolder(self) -> None:
        """Open the folder holding the application log files."""
        self.openFolder(get_logs_dir())

    @Slot(result=bool)
    def clearLogs(self) -> bool:
        """Empty the application log files. Returns True on success."""
        return clear_logs()

    # ── Internal helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _resolve(preference: str) -> str:
        """Map a theme preference to the concrete 'light' or 'dark' theme."""
        return _detect_system_theme() if preference not in ("light", "dark") else preference

    def _set_theme(self, theme: str) -> None:
        """Store the resolved theme and notify QML when it changed."""
        if theme != self._theme:
            self._theme = theme
            self.themeChanged.emit(theme)
