# app.py - CC-Gen-Ultimate GUI entry point

import configparser
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
from ccgen.utils.app_mutex import hold_app_mutexes
from ccgen.utils.helpers import resource_path
from ccgen.utils.launch import LaunchRequest, parse_arguments, plan_launch
from ccgen.utils.logging import configure_from_settings
from ccgen.utils.settings import load_settings
from ccgen.utils.single_instance import SingleInstance

# The controllers, API, and self-test pull in torch, CTranslate2, and transformers, which take
# many seconds to import. They are imported where they are used: the boot thread loads them
# behind the splash, so by the time _on_ready runs they are already in memory.

_log = logging.getLogger(__name__)
_SHUTDOWN_WAIT_MS = 2000
_SELF_TEST_FLAG = "--self-test"
# Written next to the exe by scripts\bundle.ps1 (Write-BuildInfo): the build's GPU edition and the
# fingerprint of its bundled runtime, which decide the update package (patch or full installer).
_BUILD_INFO = "build.ini"


class _Startup:
    """Owns the splash screen and boot thread, then builds the main window once ready."""

    def __init__(self, app: QApplication, instance: SingleInstance, launch: LaunchRequest) -> None:
        self._app = app
        self._instance = instance
        self._launch = launch
        self._engine: Optional[QQmlApplicationEngine] = None
        self._api_server = None
        self._app_ctrl = None
        # One TaskController per task tab, keyed by the tab's key ("generate"); QML reaches each
        # as "<key>Controller".
        self._task_ctrls: dict[str, Any] = {}
        self._prefs_ctrl = None
        self._assets_ctrl = None
        self._performance_ctrl = None
        self._update_ctrl = None

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
        from ccgen.controllers.update_ctrl import UpdateController
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
                "generate": GenerateController(api_server.base_url),
                "translate": TranslateController(api_server.base_url),
                "transliterate": TransliterateController(api_server.base_url),
                "dub": DubController(api_server.base_url),
                "workflow": WorkflowController(api_server.base_url),
            }
            prefs_ctrl = PrefsController(api_server.base_url)
            assets_ctrl = AssetsController(api_server.base_url)
            performance_ctrl = PerformanceController(api_server.base_url)
            update_ctrl = UpdateController(_update_config())
            update_ctrl.set_busy_sources([*task_ctrls.values(), assets_ctrl])
            prefs_ctrl.settingsChanged.connect(update_ctrl.preferencesChanged)

            engine = QQmlApplicationEngine()
            ctx = engine.rootContext()
            ctx.setContextProperty("appController",    app_ctrl)
            ctx.setContextProperty("prefsController",  prefs_ctrl)
            ctx.setContextProperty("modelsController", assets_ctrl)
            ctx.setContextProperty("performanceController", performance_ctrl)
            ctx.setContextProperty("updateController", update_ctrl)
            for key, controller in task_ctrls.items():
                ctx.setContextProperty(f"{key}Controller", controller)

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
            self._update_ctrl = update_ctrl
            root = engine.rootObjects()[0]
            self._splash.close()
            if isinstance(root, QQuickWindow):
                root.show()
                app_ctrl.attach_window(root)
                _log.info("Window shown - %dx%d at (%d,%d)", root.width(), root.height(), root.x(), root.y())
            else:
                _log.info("Window created (non-QQuickWindow root)")
            # This launch's files, then those of launches made while the window loaded, then each
            # later launch as it comes.
            self._take_launch(self._launch)
            self._instance.launchReceived.connect(self._on_later_launch)
            self._instance.attach()
            # After the window shows: detection imports torch, and its result only refines choices.
            performance_ctrl.detect()
            update_ctrl.start()
        except Exception as e:
            _log.critical("Failed to build interface: %r", e, exc_info=True)
            self._on_failed(str(e))

    def _take_launch(self, launch: LaunchRequest) -> None:
        """Queue a launch's files in the tabs that take them, then show the tab (appController.openTab)."""
        if self._app_ctrl is None:
            return
        accepted = {key: controller.accepted_exts for key, controller in self._task_ctrls.items()}
        plan = plan_launch(launch, accepted)
        for key, paths in plan.files.items():
            self._task_ctrls[key].addFiles(list(paths))
            _log.info("Queued %d file(s) from a launch in the %s tab", len(paths), key)
        if plan.tab:
            self._app_ctrl.openTab.emit(plan.tab)

    def _on_later_launch(self, launch: object) -> None:
        """Another start of the app handed over its files: bring the window forward and queue them."""
        if self._app_ctrl is not None:
            self._app_ctrl.bring_to_front()
        if isinstance(launch, LaunchRequest):
            self._take_launch(launch)

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
            self._instance.close()
            if self._app_ctrl is not None:
                self._app_ctrl.shutdown()
            if self._update_ctrl is not None:
                self._update_ctrl.shutdown()
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

    def install_update(self) -> None:
        """Hand a downloaded update to its installer; the last step before the process exits."""
        if self._update_ctrl is not None:
            self._update_ctrl.install_on_exit()
            self._update_ctrl = None


def _build_info() -> tuple[str, str]:
    """(GPU edition, runtime fingerprint) from build.ini next to the exe; ("", "") from source."""
    parser = configparser.ConfigParser()
    try:
        parser.read(os.path.join(os.path.dirname(os.path.abspath(sys.executable)), _BUILD_INFO), encoding="utf-8")
    except (configparser.Error, OSError, UnicodeDecodeError) as error:
        _log.warning("Could not read %s: %s", _BUILD_INFO, error)
        return "", ""
    return parser.get("build", "edition", fallback=""), parser.get("build", "runtime_id", fallback="")


def _update_config():
    """The updater's settings for this copy: feed and keys, edition, state, preferences, and log.

    The update modules were imported by the boot thread. A local staging build (scripts\\bundle.ps1
    -UpdateFeed) adds ccgen\\config\\update_staging.py, which points the feed at a test server with
    a test key; release builds never contain it.
    """
    from ccgen.config.defaults import AppInfo, UpdateDefaults, UpdateInfo
    from ccgen.controllers.update_ctrl import UpdaterConfig
    from ccgen.services.update_feed import UpdateSource
    from ccgen.services.update_install import STATE_FILE, SYSTEM
    from ccgen.utils.app_mutex import release_app_mutexes
    from ccgen.utils.settings import get_settings_file, get_updates_dir

    try:
        from ccgen.config import update_staging  # type: ignore[attr-defined]
    except ImportError:
        update_staging = None

    def read_prefs() -> tuple[bool, bool]:
        updates = load_settings().get("updates", {})
        return (bool(updates.get("auto_check", UpdateDefaults.AUTO_CHECK)),
                bool(updates.get("auto_install", UpdateDefaults.AUTO_INSTALL)))

    def log(message: str, error: bool) -> None:
        _log.log(logging.WARNING if error else logging.INFO, message)

    def extra_args(kind: str, package) -> list[str]:
        # The patch installer serves both install kinds: it takes the kind and folder of this copy.
        if package.kind != "patch":
            return []
        folder = os.path.dirname(os.path.abspath(sys.executable))
        return ["/ALLUSERS" if kind == SYSTEM else "/CURRENTUSER", f'/DIR="{folder}"']

    edition, runtime_id = _build_info()
    source = UpdateSource(
        app=AppInfo.APP_NAME,
        version=AppInfo.APP_VERSION,
        base_url=getattr(update_staging, "BASE_URL", UpdateInfo.REPO_URL),
        public_keys=tuple(getattr(update_staging, "PUBLIC_KEYS", UpdateInfo.PUBLIC_KEYS)),
        allow_local_http=update_staging is not None,
    )
    return UpdaterConfig(
        source=source,
        state_path=os.path.join(os.path.dirname(get_settings_file()), STATE_FILE),
        downloads_dir=get_updates_dir(),
        read_prefs=read_prefs,
        log=log,
        release_locks=release_app_mutexes,
        edition=edition,
        runtime_id=runtime_id,
        extra_args=extra_args,
    )


def main() -> None:
    """Hand a later launch's files to the open window, or show the splash and boot the app.

    `[--tab KEY] [PATH ...]` queues files (Explorer's menu names the tab). `--self-test
    [REPORT_PATH]` instead verifies the build can load everything it needs and exits with 0 or 1
    (used by the release workflow on the frozen bundle).
    """
    freeze_support()
    if _SELF_TEST_FLAG in sys.argv:
        from ccgen.utils.self_test import run_self_test

        index = sys.argv.index(_SELF_TEST_FLAG)
        sys.exit(run_self_test(sys.argv[index + 1] if index + 1 < len(sys.argv) else None))
    configure_from_settings(load_settings())

    os.environ.setdefault("QT_QPA_PLATFORM", "windows")
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

    QQuickStyle.setStyle("Material")
    _log.debug("QML style set to Material")

    app = QApplication(sys.argv)
    launch = parse_arguments(sys.argv[1:])
    instance = SingleInstance()
    if instance.try_forward(launch):
        _log.info("Handed %d file(s) to the open CC-Gen-Ultimate window", len(launch.paths))
        sys.exit(0)
    _log.info("Starting CC-Gen-Ultimate")
    hold_app_mutexes()  # the installers wait while CC-Gen-Ultimate runs
    # Qt's automatic quit-on-last-window-closed can misfire the instant the
    # splash (a QWidget) closes while a QML window is the only one left open -
    # main.qml's root window quits explicitly on close instead (see main.qml).
    app.setQuitOnLastWindowClosed(False)
    startup = _Startup(app, instance, launch)
    code = app.exec()
    startup.shutdown()
    startup.install_update()
    sys.exit(code)


if __name__ == "__main__":
    main()
