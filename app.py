# app.py - CC-Gen-Ultimate GUI entry point

import logging
import os
import sys
from multiprocessing import freeze_support
from typing import Any, Optional

from PySide6.QtCore import QSize, QThreadPool
from PySide6.QtGui import QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication, QMessageBox

from ccgen.ui.boot_thread import BootThread
from ccgen.ui.splash_screen import SplashScreen
from ccgen.utils.helpers import resource_path
from ccgen.utils.logging import configure_from_settings
from ccgen.utils.settings import load_settings

# The controllers, API, and self-test pull in torch, CTranslate2, and transformers, which take
# many seconds to import. They are imported where they are used: the boot thread loads them
# behind the splash, so by the time _on_ready runs they are already in memory.

_log = logging.getLogger(__name__)
_SHUTDOWN_WAIT_MS = 2000
_SELF_TEST_FLAG = "--self-test"


class _Startup:
    """Owns the splash screen and boot thread, then builds the main window once ready."""

    def __init__(self, app: QApplication) -> None:
        self._app = app
        self._input_paths = [p for p in sys.argv[1:] if os.path.exists(p)]
        self._engine: Optional[QQmlApplicationEngine] = None
        self._api_server = None
        self._app_ctrl = None
        # One TaskController per task tab, keyed by the QML context property name.
        self._task_ctrls: dict[str, Any] = {}
        self._prefs_ctrl = None
        self._assets_ctrl = None
        self._performance_ctrl = None

        self._splash = SplashScreen(resource_path("ccgen/assets/icons/Square310x310Logo.scale-100.png"))
        self._splash.show()
        _log.info("Splash shown")

        self._boot = BootThread()
        self._boot.stage_changed.connect(self._splash.set_stage)
        self._boot.boot_ready.connect(self._on_ready)
        self._boot.boot_failed.connect(self._on_failed)
        self._boot.start()

    def _on_ready(self, api_server) -> None:
        """Build controllers and load the QML UI once the backend is ready."""
        from ccgen.controllers.app_ctrl import AppController
        from ccgen.controllers.assets_ctrl import AssetsController
        from ccgen.controllers.performance_ctrl import PerformanceController
        from ccgen.controllers.prefs_ctrl import PrefsController
        from ccgen.controllers.task_ctrl import TaskController
        from ccgen.controllers.task_tabs import (
            DubController,
            GenerateController,
            TranslateController,
            TransliterateController,
        )
        from ccgen.controllers.workflow_ctrl import WorkflowController

        try:
            _log.info("Embedded API server ready at %s", api_server.base_url)
            self._api_server = api_server

            icon = QIcon()
            for size in (16, 32, 48, 256):
                path = resource_path(f"ccgen/assets/icons/Square44x44Logo.targetsize-{size}.png")
                if os.path.isfile(path):
                    icon.addFile(path, QSize(size, size))
            if not icon.isNull():
                self._app.setWindowIcon(icon)

            app_ctrl   = AppController()
            task_ctrls: dict[str, TaskController] = {
                "generateController": GenerateController(api_server.base_url),
                "translateController": TranslateController(api_server.base_url),
                "transliterateController": TransliterateController(api_server.base_url),
                "dubController": DubController(api_server.base_url),
                "workflowController": WorkflowController(api_server.base_url),
            }
            prefs_ctrl = PrefsController(api_server.base_url)
            assets_ctrl = AssetsController(api_server.base_url)
            performance_ctrl = PerformanceController(api_server.base_url)
            if self._input_paths:
                # Files opened with the app (e.g. from Explorer's context menu): media gets
                # subtitles generated, subtitle files are offered for translation.
                task_ctrls["generateController"].addFiles(self._input_paths)
                task_ctrls["translateController"].addFiles(
                    [p for p in self._input_paths if os.path.splitext(p)[1].lower() in TranslateController.accepted_exts]
                )
                _log.info("Queued %d file(s) from command line", len(self._input_paths))

            engine = QQmlApplicationEngine()
            ctx = engine.rootContext()
            ctx.setContextProperty("appController",    app_ctrl)
            ctx.setContextProperty("prefsController",  prefs_ctrl)
            ctx.setContextProperty("modelsController", assets_ctrl)
            ctx.setContextProperty("performanceController", performance_ctrl)
            for name, controller in task_ctrls.items():
                ctx.setContextProperty(name, controller)

            qml_dir = resource_path("ccgen/qml")
            engine.addImportPath(qml_dir)
            engine.load(os.path.join(qml_dir, "main.qml"))

            if not engine.rootObjects():
                self._on_failed("The user interface failed to load.")
                return

            # Kept alive for the app's lifetime - QML's context properties hold
            # only a weak reference, so a garbage-collected controller here
            # would leave bound QML text empty.
            self._engine = engine
            self._app_ctrl = app_ctrl
            self._task_ctrls = task_ctrls
            self._prefs_ctrl = prefs_ctrl
            self._assets_ctrl = assets_ctrl
            self._performance_ctrl = performance_ctrl
            root = engine.rootObjects()[0]
            self._splash.close()
            if isinstance(root, QQuickWindow):
                root.show()
                _log.info("Window shown - %dx%d at (%d,%d)", root.width(), root.height(), root.x(), root.y())
            else:
                _log.info("Window created (non-QQuickWindow root)")
            # After the window shows: detection imports torch, and its result only refines choices.
            performance_ctrl.detect()
        except Exception as e:
            _log.critical("Failed to build interface: %r", e, exc_info=True)
            self._on_failed(str(e))

    def _on_failed(self, message: str) -> None:
        """Show a real error dialog and quit instead of hanging silently."""
        _log.critical("Startup failed: %s", message)
        self._splash.set_error(message)
        QMessageBox.critical(None, "CC-Gen-Ultimate", f"Failed to start:\n\n{message}")
        self._splash.close()
        self._app.exit(-1)

    def shutdown(self) -> None:
        """Tear down the QML scene and controllers, then stop the API server."""
        try:
            for controller in self._task_ctrls.values():
                controller.shutdown()
            # The controllers' cancel requests need the event loop, which has stopped by now,
            # so running jobs are cancelled in-process and stop at their next safe point.
            if self._api_server is not None:
                from ccgen.api.routers.jobs import cancel_all_jobs

                cancel_all_jobs()
            if self._task_ctrls:
                # A cancelled folder scan exits within milliseconds; wait for it so its
                # thread doesn't outlive the objects it reports to.
                QThreadPool.globalInstance().waitForDone(_SHUTDOWN_WAIT_MS)
            if self._assets_ctrl is not None:
                self._assets_ctrl.close()
            self._engine = None
            self._app_ctrl = None
            self._task_ctrls = {}
            self._prefs_ctrl = None
            self._assets_ctrl = None
            self._performance_ctrl = None
            if self._api_server is not None:
                self._api_server.stop()
        except Exception:
            _log.warning("Error during shutdown", exc_info=True)


def main() -> None:
    """Initialise the Qt application, show the splash, and boot the app in the background.

    `--self-test [REPORT_PATH]` instead verifies the build can load everything it needs and
    exits with 0 or 1 (used by the release workflow on the frozen bundle).
    """
    freeze_support()
    if _SELF_TEST_FLAG in sys.argv:
        from ccgen.utils.self_test import run_self_test

        index = sys.argv.index(_SELF_TEST_FLAG)
        sys.exit(run_self_test(sys.argv[index + 1] if index + 1 < len(sys.argv) else None))
    configure_from_settings(load_settings())
    _log.info("Starting CC-Gen-Ultimate")

    os.environ.setdefault("QT_QPA_PLATFORM", "windows")
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

    QQuickStyle.setStyle("Material")
    _log.debug("QML style set to Material")

    app = QApplication(sys.argv)
    # Qt's automatic quit-on-last-window-closed can misfire the instant the
    # splash (a QWidget) closes while a QML window is the only one left open -
    # main.qml's root window quits explicitly on close instead (see main.qml).
    app.setQuitOnLastWindowClosed(False)
    startup = _Startup(app)
    code = app.exec()
    startup.shutdown()
    sys.exit(code)


if __name__ == "__main__":
    main()
