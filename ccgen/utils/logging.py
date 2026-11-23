# logging.py - log file location and runtime configuration for CC-Gen-Ultimate
#
# The "logging" settings section decides whether a rotating log file is written and how much
# goes into it: "critical" keeps warnings and errors only, "all" records full debug detail.
# Console output (when a console exists) always stays at debug level for development.

import glob
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from typing import Any, Optional

from ccgen.config.defaults import AppInfo, LoggingDefaults

_FORMAT = "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s"
_LEVELS = {"critical": logging.WARNING, "all": logging.DEBUG}
# Third-party libraries that log every HTTP request or tensor op at debug level.
_NOISY_LOGGERS = (
    "urllib3", "httpx", "httpcore", "filelock", "huggingface_hub", "matplotlib", "PIL", "argostranslate", "stanza",
)

_file_handler: Optional[RotatingFileHandler] = None


def get_logs_dir() -> str:
    """Return the logs directory path, creating it if needed."""
    if getattr(sys, "frozen", False):
        appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
        logs_dir = os.path.join(appdata, AppInfo.APP_NAME, "logs")
    else:
        here = os.path.dirname(os.path.abspath(__file__))
        logs_dir = os.path.join(os.path.dirname(os.path.dirname(here)), "logs")
    os.makedirs(logs_dir, exist_ok=True)
    return logs_dir


def get_log_file() -> str:
    """Return the path of the active log file."""
    return os.path.join(get_logs_dir(), LoggingDefaults.LOG_FILE_NAME)


def configure_logging(
    enabled: bool = LoggingDefaults.ENABLE_LOGS, level: str = LoggingDefaults.DEFAULT_LOG_LEVEL, console: bool = True,
) -> None:
    """Apply the logging preferences: attach, retune, or detach the rotating log file.

    Safe to call repeatedly; the settings service calls it again whenever a logging
    preference changes, so the new choice applies without restarting the app. `console` False
    leaves the console alone (the command line keeps it for its own words).
    """
    global _file_handler
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    has_console = any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
                      for h in root.handlers)
    if console and not has_console:
        if sys.stderr is not None:
            handler = logging.StreamHandler(sys.stderr)
            handler.setFormatter(logging.Formatter(_FORMAT, "%H:%M:%S"))
            root.addHandler(handler)
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    if not enabled:
        _detach_file_handler()
        return
    if _file_handler is None:
        try:
            _file_handler = RotatingFileHandler(
                get_log_file(),
                maxBytes=LoggingDefaults.MAX_LOG_BYTES,
                backupCount=LoggingDefaults.LOG_BACKUP_COUNT,
                encoding="utf-8",
                delay=True,
            )
            _file_handler.setFormatter(logging.Formatter(_FORMAT))
            root.addHandler(_file_handler)
        except OSError:
            logging.getLogger(__name__).warning("Could not open the log file", exc_info=True)
            _file_handler = None
            return
    _file_handler.setLevel(_LEVELS.get(level, logging.WARNING))


def configure_from_settings(settings: dict[str, Any], console: bool = True) -> None:
    """Apply the "logging" section of a settings dictionary (`console` as for configure_logging)."""
    prefs = settings.get("logging", {})
    configure_logging(
        bool(prefs.get("enable_logs", LoggingDefaults.ENABLE_LOGS)),
        str(prefs.get("log_level", LoggingDefaults.DEFAULT_LOG_LEVEL)),
        console,
    )


def clear_logs() -> bool:
    """Empty the current log file and delete rotated backups. Returns True on success."""
    try:
        if _file_handler is not None:
            _file_handler.acquire()
            try:
                if _file_handler.stream is not None:
                    _file_handler.stream.seek(0)
                    _file_handler.stream.truncate()
            finally:
                _file_handler.release()
        elif os.path.exists(get_log_file()):
            open(get_log_file(), "w", encoding="utf-8").close()
        for backup in glob.glob(f"{get_log_file()}.*"):
            os.remove(backup)
        return True
    except OSError:
        logging.getLogger(__name__).warning("Could not clear log files", exc_info=True)
        return False


def _detach_file_handler() -> None:
    """Remove and close the log file handler, if attached."""
    global _file_handler
    if _file_handler is not None:
        logging.getLogger().removeHandler(_file_handler)
        _file_handler.close()
        _file_handler = None
