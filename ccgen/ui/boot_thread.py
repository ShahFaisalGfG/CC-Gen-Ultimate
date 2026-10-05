# boot_thread.py - loads the engine/backend stack off the GUI thread and reports staged
# progress to the startup splash screen.
#
# The imports inside run() below are a deliberate, narrow exception to the project's
# top-of-file import rule: Python fully resolves a file's top-level imports before running
# any other code in it, so live per-dependency progress on screen is only possible if the
# heavy imports happen after the splash is already visible, i.e. inside a function body.

import logging

from PySide6.QtCore import QThread, Signal

_log = logging.getLogger(__name__)


class BootThread(QThread):
    """Imports the engine/backend stack and starts the embedded API server, staged for progress."""

    stage_changed = Signal(str, int)
    boot_ready = Signal(object)
    boot_failed = Signal(str)

    def run(self) -> None:
        """Load each engine family in turn, then start and wait for the embedded API server."""
        try:
            self.stage_changed.emit("Loading transcription engine...", 15)
            import ccgen.engines.captions  # noqa: F401

            self.stage_changed.emit("Loading translation engine...", 35)
            import ccgen.engines.translation  # noqa: F401

            self.stage_changed.emit("Loading transliteration engine...", 55)
            import ccgen.engines.transliteration  # noqa: F401

            self.stage_changed.emit("Starting local server...", 75)
            from ccgen.api.embedded import EmbeddedServer

            api_server = EmbeddedServer()
            api_server.start()
            if not api_server.wait_ready():
                self.boot_failed.emit("The embedded API server did not start in time.")
                return

            self.stage_changed.emit("Preparing interface...", 90)
            import ccgen.controllers.app_ctrl  # noqa: F401
            import ccgen.controllers.assets_ctrl  # noqa: F401
            import ccgen.controllers.prefs_ctrl  # noqa: F401
            import ccgen.controllers.task_tabs  # noqa: F401
            import ccgen.controllers.workflow_ctrl  # noqa: F401

            self.boot_ready.emit(api_server)
        except Exception as e:
            _log.critical("Startup failed: %r", e, exc_info=True)
            self.boot_failed.emit(str(e))
