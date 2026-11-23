# notifier.py - a Windows notification when a long run ends while the app is in the background
#
# CC-Gen-Ultimate has no tray icon of its own, and Qt shows a notification from a notification-area
# icon (QSystemTrayIcon). So the icon appears only with a notification and goes when the user is
# back: on a click of the notification or the icon (which bring the window forward), or when
# any of the app's windows becomes active again.

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QSystemTrayIcon

from ccgen.config.defaults import AppInfo

SHOW_MS = 10_000

_log = logging.getLogger(__name__)


class Notifier(QObject):
    """Shows notifications from a notification-area icon that exists only while one is unread."""

    def __init__(self, show_window: Callable[[], None], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._show_window = show_window
        self._tray: QSystemTrayIcon | None = None
        app = QGuiApplication.instance()
        if isinstance(app, QGuiApplication):
            app.applicationStateChanged.connect(self._on_state)

    def notify(self, title: str, message: str) -> bool:
        """Show a notification; False (logged) when Windows has no notification area to show it from."""
        if not (QSystemTrayIcon.isSystemTrayAvailable() and QSystemTrayIcon.supportsMessages()):
            _log.info("Notification not shown (no notification area): %s: %s", title, message)
            return False
        tray = self._tray or self._make_tray()
        tray.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, SHOW_MS)
        return True

    def dismiss(self) -> None:
        """Remove the icon once the user is back or the app closes."""
        if self._tray is not None:
            self._tray.hide()
            self._tray.deleteLater()
            self._tray = None

    def _make_tray(self) -> QSystemTrayIcon:
        """The notification-area icon notifications come from, shown until dismiss()."""
        tray = QSystemTrayIcon(QGuiApplication.windowIcon(), self)
        tray.setToolTip(AppInfo.APP_NAME)
        tray.messageClicked.connect(self._open)
        tray.activated.connect(self._open)
        tray.show()
        self._tray = tray
        return tray

    def _open(self, *_args: object) -> None:
        """A click on the notification or the icon: bring the window forward."""
        self.dismiss()
        self._show_window()

    def _on_state(self, state: Qt.ApplicationState) -> None:
        """The user switched back to the app: the notification has done its job."""
        if state == Qt.ApplicationState.ApplicationActive:
            self.dismiss()
