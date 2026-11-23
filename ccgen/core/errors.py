# errors.py - plain words for what went wrong, with the next step, for the app and the command line
#
# Engines raise whatever their libraries raise: "CUDA out of memory. Tried to allocate...",
# "[WinError 112] There is not enough space on the disk", "Max retries exceeded with url". The
# app, the API, and the CLI all pass those through describe(), which turns them into one sentence
# saying what happened and what to do, and keeps the original text as the detail for the log and
# "Copy details". Messages this app wrote itself (a ValueError from config validation, a
# RuntimeError such as "movie.mp4 contains no audio.") are already plain and pass through as they are.
#
# Exceptions are recognised by class name and text, so nothing here imports torch, CTranslate2, or
# huggingface_hub, and the CLI can classify an error without loading them.

import errno
import os
import re
from dataclasses import dataclass
from typing import Optional, Union

KIND_CANCELLED = "cancelled"
KIND_INVALID = "invalid"
KIND_GPU_MEMORY = "gpu_memory"
KIND_MEMORY = "memory"
KIND_DISK_FULL = "disk_full"
KIND_ACCESS_DENIED = "access_denied"
KIND_IN_USE = "in_use"
KIND_NETWORK = "network"
KIND_FILE_MISSING = "file_missing"
KIND_UNREADABLE_MEDIA = "unreadable_media"
KIND_LANGUAGE_PAIR = "language_pair"
KIND_UNKNOWN = "unknown"

# Windows error codes that OSError.winerror carries.
_WIN_ACCESS_DENIED = 5
_WIN_SHARING_VIOLATION = 32
_WIN_LOCK_VIOLATION = 33
_WIN_HANDLE_DISK_FULL = 39
_WIN_DISK_FULL = 112
_WIN_FILE_NOT_FOUND = 2
_WIN_PATH_NOT_FOUND = 3

_GPU_MEMORY_TEXT = re.compile(
    r"CUDA out of memory|CUBLAS_STATUS_ALLOC_FAILED|CUDNN_STATUS_(?:ALLOC_FAILED|NOT_ENOUGH_WORKSPACE)"
    r"|out of memory on device|XPU out of memory|cudaErrorMemoryAllocation|CUDA failed with error out of memory",
    re.IGNORECASE,
)
_MEMORY_TEXT = re.compile(
    r"\bout of memory\b|not enough memory|DefaultCPUAllocator: can't allocate|bad allocation|std::bad_alloc"
    r"|Unable to allocate|paging file is too small",
    re.IGNORECASE,
)
_DISK_FULL_TEXT = re.compile(r"No space left on device|not enough space on the disk|disk is full", re.IGNORECASE)
_NETWORK_TEXT = re.compile(
    r"Max retries exceeded|getaddrinfo failed|Name or service not known|Temporary failure in name resolution"
    r"|Failed to establish a new connection|Connection (?:refused|reset|aborted)|timed out|Read timed out"
    r"|SSLError|CERTIFICATE_VERIFY_FAILED|Network is unreachable|No route to host|HTTP Error 5\d\d"
    r"|We couldn't connect to|couldn't connect to 'https://huggingface.co'|offline mode is enabled"
    r"|Cannot find the requested files in the disk cache|LocalEntryNotFoundError",
    re.IGNORECASE,
)
_NETWORK_CLASSES = frozenset({
    "ConnectionError", "ConnectTimeout", "ReadTimeout", "Timeout", "TimeoutError", "URLError", "HTTPError",
    "SSLError", "ProxyError", "MaxRetryError", "NewConnectionError", "RemoteDisconnected", "IncompleteRead",
    "ChunkedEncodingError", "HfHubHTTPError", "LocalEntryNotFoundError", "OfflineModeIsEnabled",
    "ConnectionResetError", "ConnectionAbortedError", "ConnectionRefusedError", "gaierror",
})
_MEDIA_CLASSES = frozenset({"InvalidDataError", "DecoderNotFoundError", "PatchWelcomeError", "FFmpegError"})
_MEDIA_TEXT = re.compile(r"Invalid data found when processing input|moov atom not found|could not find codec",
                         re.IGNORECASE)
# The Hugging Face library's names for model files, which nobody should have to read.
_REPO_ID = re.compile(r"\b[\w.-]+/[\w.-]*(?:whisper|m2m100|opus|nllb|madlad|xtts|omnivoice|wavlm|rekhta|piper|hy-mt)"
                      r"[\w.-]*", re.IGNORECASE)
# Wrappers the engines put around a library's error ("Translation failed: <raw>").
_WRAPPER = re.compile(r"^(?:Model load failed \([^)]*\)|Translation failed|Transliteration failed|Download failed"
                      r"|Remove failed): ", re.IGNORECASE)


@dataclass(frozen=True)
class Problem:
    """What went wrong, in plain words with the next step, and the original text for the log."""

    kind: str
    message: str
    detail: str = ""


def describe(error: Union[BaseException, str], path: str = "") -> Problem:
    """A plain sentence with a next step for `error`, which a task, a download, or a file action raised.

    `path` is the file the work was on, named in messages that are about it.
    """
    if isinstance(error, str):
        return _from_text(error, path)
    detail = _detail(error)
    for exc in _chain(error):
        problem = _classify(exc, path)
        if problem is not None:
            return Problem(problem.kind, problem.message, detail)
    if _is_plain(error):
        return Problem(_plain_kind(error), _unwrap(str(error)), detail if detail != str(error) else "")
    text = _from_text(detail, path)
    if text.kind != KIND_UNKNOWN:
        return text
    return Problem(KIND_UNKNOWN, unknown_message(), detail)


def unknown_message() -> str:
    """The sentence for an error nothing else explains."""
    return "Something went wrong. Try again; if it happens again, open the log from the file's menu."


def gpu_memory_message() -> str:
    """Out of memory on the graphics card."""
    return ("The graphics card ran out of memory. Close other apps that use it, or choose the Light profile "
            "or a smaller model in Preferences > Performance, then try again.")


def memory_message() -> str:
    """Out of memory on the computer."""
    return ("The computer ran out of memory. Close other apps, or choose the Light profile or a smaller model "
            "in Preferences > Performance, then try again.")


def disk_full_message(needed_bytes: Optional[int] = None, folder: str = "", other_folder: bool = True) -> str:
    """A full drive, with the space needed when it is known.

    `other_folder` False leaves out choosing another folder (models always download to theirs).
    """
    where = f" for {folder}" if folder else ""
    need = f" It needs about {format_size(needed_bytes)} free." if needed_bytes else ""
    action = "Free some space or choose another folder" if other_folder else "Free some space on it"
    return f"The drive{where} is full.{need} {action}, then try again."


def network_message() -> str:
    """A model download that couldn't reach the internet."""
    return ("The model couldn't be downloaded. Check the internet connection and try again; once downloaded, "
            "it works offline.")


def missing_file_message(path: str, queued: bool = True) -> str:
    """A file that isn't where it was; a queued one is added again, a result is only reported."""
    name = os.path.basename(path) if path else "The file"
    text = f"{name} isn't there any more. It may have been moved, renamed, or deleted"
    return text + ("; add it again." if queued else ".")


def format_size(size_bytes: Optional[int]) -> str:
    """Bytes in the largest whole unit people read ("1.4 GB", "350 MB")."""
    if not size_bytes or size_bytes <= 0:
        return "0 MB"
    if size_bytes >= 1_000_000_000:
        return f"{size_bytes / 1_000_000_000:.1f} GB"
    return f"{max(1, round(size_bytes / 1_000_000))} MB"


def _classify(exc: BaseException, path: str) -> Optional[Problem]:
    """The problem one exception in the chain stands for, or None when it isn't one we recognise."""
    name = type(exc).__name__
    text = str(exc)
    if name == "JobCancelled" or name == "DownloadCancelled":
        return Problem(KIND_CANCELLED, "Cancelled.")
    if name == "OutOfMemoryError" or _GPU_MEMORY_TEXT.search(text):
        return Problem(KIND_GPU_MEMORY, gpu_memory_message())
    if isinstance(exc, MemoryError) or _MEMORY_TEXT.search(text):
        return Problem(KIND_MEMORY, memory_message())
    if isinstance(exc, OSError):
        problem = _os_problem(exc, path)
        if problem is not None:
            return problem
    if name in _NETWORK_CLASSES or _NETWORK_TEXT.search(text):
        return Problem(KIND_NETWORK, network_message())
    if name in _MEDIA_CLASSES or _MEDIA_TEXT.search(text):
        name_of = os.path.basename(path) if path else "The file"
        return Problem(KIND_UNREADABLE_MEDIA,
                       f"{name_of} can't be read as audio or video. It may be damaged or in a format this app "
                       "can't open; convert it to MP4 or WAV and try again.")
    if _DISK_FULL_TEXT.search(text):
        return Problem(KIND_DISK_FULL, disk_full_message())
    return None


def _os_problem(exc: OSError, path: str) -> Optional[Problem]:
    """A full drive, a refused or locked file, or a missing one."""
    winerror = getattr(exc, "winerror", None)
    target = exc.filename if isinstance(exc.filename, str) else path
    name = os.path.basename(target) if target else "the file"
    if exc.errno == errno.ENOSPC or winerror in (_WIN_DISK_FULL, _WIN_HANDLE_DISK_FULL):
        return Problem(KIND_DISK_FULL, disk_full_message())
    if winerror in (_WIN_SHARING_VIOLATION, _WIN_LOCK_VIOLATION):
        return Problem(KIND_IN_USE, f"{name} is open in another app. Close it there, then try again.")
    if isinstance(exc, PermissionError) or winerror == _WIN_ACCESS_DENIED or exc.errno == errno.EACCES:
        return Problem(KIND_ACCESS_DENIED,
                       f"Windows didn't allow access to {name}. Choose another output folder, or check that "
                       "the file isn't read-only, then try again.")
    if isinstance(exc, FileNotFoundError) or winerror in (_WIN_FILE_NOT_FOUND, _WIN_PATH_NOT_FOUND):
        return Problem(KIND_FILE_MISSING, missing_file_message(target))
    return None


def _from_text(text: str, path: str) -> Problem:
    """Classify a message that arrived as text (from the API, or a result's error field)."""
    if _GPU_MEMORY_TEXT.search(text):
        return Problem(KIND_GPU_MEMORY, gpu_memory_message(), text)
    if _MEMORY_TEXT.search(text):
        return Problem(KIND_MEMORY, memory_message(), text)
    if _DISK_FULL_TEXT.search(text) or re.search(r"\[(?:WinError|Errno) (?:112|39|28)\]", text):
        return Problem(KIND_DISK_FULL, disk_full_message(), text)
    if re.search(r"\[WinError (?:32|33)\]", text):
        name = os.path.basename(path) if path else "The file"
        return Problem(KIND_IN_USE, f"{name} is open in another app. Close it there, then try again.", text)
    if re.search(r"\[(?:WinError 5|Errno 13)\]", text):
        name = os.path.basename(path) if path else "the file"
        return Problem(KIND_ACCESS_DENIED,
                       f"Windows didn't allow access to {name}. Choose another output folder, or check that the "
                       "file isn't read-only, then try again.", text)
    if _NETWORK_TEXT.search(text):
        return Problem(KIND_NETWORK, network_message(), text)
    if _MEDIA_TEXT.search(text):
        name = os.path.basename(path) if path else "The file"
        return Problem(KIND_UNREADABLE_MEDIA,
                       f"{name} can't be read as audio or video. It may be damaged or in a format this app can't "
                       "open; convert it to MP4 or WAV and try again.", text)
    if text.startswith("File not found:"):
        return Problem(KIND_FILE_MISSING, missing_file_message(text.partition(":")[2].strip() or path), text)
    return Problem(KIND_UNKNOWN, text, text)


def _chain(error: BaseException) -> list[BaseException]:
    """The error and the ones it was raised from, outermost first, without loops."""
    seen: list[BaseException] = []
    current: Optional[BaseException] = error
    while current is not None and all(current is not e for e in seen) and len(seen) < 8:
        seen.append(current)
        current = current.__cause__ or current.__context__
    return seen


def _is_plain(error: BaseException) -> bool:
    """True for the app's own messages: config validation and the tasks' plain RuntimeErrors."""
    if not isinstance(error, (ValueError, RuntimeError, FileNotFoundError)) or type(error).__module__ not in (
            "builtins", "exceptions"):
        return False
    text = _unwrap(str(error))
    # A wrapped library error keeps its cause, and raw library text reads like code, not a sentence.
    return bool(text) and error.__cause__ is None and _reads_plain(text)


def _plain_kind(error: BaseException) -> str:
    """The kind of one of the app's own messages."""
    text = str(error)
    if isinstance(error, FileNotFoundError) or text.startswith("File not found"):
        return KIND_FILE_MISSING
    lowered = text.lower()
    if ("translat" in lowered or "transliterat" in lowered) and any(
            phrase in lowered for phrase in ("can't", "isn't", "doesn't", "has no model", "already in")):
        return KIND_LANGUAGE_PAIR
    return KIND_INVALID


def _reads_plain(text: str) -> bool:
    """A sentence a person wrote: starts with a capital letter or a file name and ends with punctuation."""
    stripped = text.strip()
    return stripped[:1].isupper() and stripped[-1:] in ".!?)" and "Traceback" not in stripped \
        and not _REPO_ID.search(stripped)


def _unwrap(text: str) -> str:
    """Drop the engines' "Translation failed: " style prefixes."""
    return _WRAPPER.sub("", text.strip())


def _detail(error: BaseException) -> str:
    """The original text of the error and its causes, for the log and "Copy details"."""
    parts = []
    for exc in _chain(error):
        text = str(exc) or type(exc).__name__
        line = f"{type(exc).__name__}: {text}"
        if line not in parts:
            parts.append(line)
    return " <- ".join(parts)
