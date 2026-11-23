# helpers.py - path and formatting utilities for CC-Gen-Ultimate
#
# Standard library only: the command line and the engine use these too, without Qt.

import os
import sys
from typing import Any
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname


def resource_path(relative: str) -> str:
    """Return absolute path to a resource; works in dev and PyInstaller builds."""
    try:
        base = getattr(sys, "_MEIPASS", None)
        if base is None:
            here = os.path.dirname(os.path.abspath(__file__))
            base = os.path.dirname(os.path.dirname(here))
        return os.path.normpath(os.path.join(base, relative))
    except Exception:
        return relative


def plural(count: int, noun: str) -> str:
    """Return "1 file" / "3 files" style counts for user-facing messages."""
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def to_local_path(value: Any) -> str:
    """Convert a QUrl, file:// URL string, or plain path into a normalized local path."""
    if hasattr(value, "toLocalFile"):
        text = value.toLocalFile() or value.toString()
    else:
        text = str(value)
        if text.startswith("file:"):
            text = file_url_path(text)
    return os.path.normpath(text) if text else ""


def file_url_path(url: str) -> str:
    r"""The local path of a file:// URL ("file:///C:/a%20b.mp4" -> "C:\a b.mp4"), UNC shares included."""
    parsed = urlparse(url)
    # Windows' url2pathname decodes %xx itself.
    path = url2pathname(parsed.path) if os.name == "nt" else unquote(parsed.path)
    if parsed.netloc and parsed.netloc.lower() != "localhost":
        return "\\\\" + parsed.netloc + path if os.name == "nt" else f"//{parsed.netloc}{path}"
    return path


def duration_text(seconds: float) -> str:
    """A duration as people say it: "45 s", "3 min", "1 h 05 min"."""
    seconds = max(0, int(round(seconds)))
    if seconds < 60:
        return f"{seconds} s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60:02d} min"


def format_seconds(seconds: float) -> str:
    """Format float seconds into a human-readable duration string."""
    try:
        secs = int(seconds)
        if secs < 60:
            return f"{secs}s"
        mins, secs = divmod(secs, 60)
        if mins < 60:
            return f"{mins}m {secs}s"
        hrs, mins = divmod(mins, 60)
        return f"{hrs}h {mins}m {secs}s"
    except Exception:
        return "0s"


def ensure_dir(path: str) -> str:
    """Create directory (and parents) if it does not exist. Returns path."""
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass
    return path


def safe_stem(path: str) -> str:
    """Return filename without extension from a full path."""
    try:
        return os.path.splitext(os.path.basename(path))[0]
    except Exception:
        return path


def format_bytes(num_bytes: float) -> str:
    """Format a byte count into a human-readable string (e.g. '45.2 MB')."""
    try:
        for unit in ("B", "KB", "MB", "GB"):
            if abs(num_bytes) < 1024.0:
                return f"{num_bytes:.1f} {unit}"
            num_bytes /= 1024.0
        return f"{num_bytes:.1f} TB"
    except Exception:
        return "0 B"


def format_duration_ms(seconds: float) -> str:
    """Format float seconds into HH:MM:SS for subtitle segment timestamps."""
    try:
        total = int(seconds)
        hrs, remainder = divmod(total, 3600)
        mins, secs = divmod(remainder, 60)
        return f"{hrs:02d}:{mins:02d}:{secs:02d}"
    except Exception:
        return "00:00:00"
