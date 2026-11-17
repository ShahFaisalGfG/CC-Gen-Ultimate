# app_mutex.py - the mutexes the installers wait on, held while CC-Gen-Ultimate runs
#
# Inno Setup's AppMutex (installer/*.iss) asks the user to close CC-Gen-Ultimate before files are
# replaced, and an update's silent installer waits for them to go (installer/update_support.iss).
# Every running copy opens the same two mutexes, so they exist while any copy is open.

import ctypes
import logging
from ctypes import wintypes
from typing import Any

# Keep in step with AppMutexes in installer/ccgenultimate_*_installer.iss.
APP_MUTEXES = ("CCGenUltimateAppMutex", "Global\\CCGenUltimateAppMutex")
# Everyone may wait on them (SYNCHRONIZE), so Setup sees them from any account and another copy
# in another session can open the Global one.
_APP_MUTEX_SDDL = "D:(A;;0x00100000;;;WD)"
_SDDL_REVISION_1 = 1
_SYNCHRONIZE = 0x00100000

_log = logging.getLogger(__name__)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)


def _api(dll: ctypes.WinDLL, name: str, restype: Any, *argtypes: Any) -> Any:
    function = getattr(dll, name)
    function.restype = restype
    function.argtypes = list(argtypes)
    return function


_CloseHandle = _api(_kernel32, "CloseHandle", wintypes.BOOL, wintypes.HANDLE)
_LocalFree = _api(_kernel32, "LocalFree", wintypes.HLOCAL, wintypes.HLOCAL)
_CreateMutexExW = _api(_kernel32, "CreateMutexExW", wintypes.HANDLE,
                       wintypes.LPVOID, wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD)
_ConvertSddl = _api(_advapi32, "ConvertStringSecurityDescriptorToSecurityDescriptorW", wintypes.BOOL,
                    wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(wintypes.LPVOID), ctypes.POINTER(wintypes.ULONG))


class _SecurityAttributes(ctypes.Structure):
    """SECURITY_ATTRIBUTES for CreateMutexExW."""

    _fields_ = [("nLength", wintypes.DWORD), ("lpSecurityDescriptor", wintypes.LPVOID),
                ("bInheritHandle", wintypes.BOOL)]


_held: list[int] = []


def hold_app_mutexes() -> None:
    """Create the installer mutexes and keep them until release_app_mutexes() or exit.

    Creating the Global one can be refused in some sessions; the installers then see the other one.
    """
    descriptor = wintypes.LPVOID()
    if not _ConvertSddl(_APP_MUTEX_SDDL, _SDDL_REVISION_1, ctypes.byref(descriptor), None):
        _log.warning("Could not build the installer mutex access rules: %s", ctypes.WinError(ctypes.get_last_error()))
    attributes = _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), descriptor, False)
    security = ctypes.cast(ctypes.pointer(attributes), wintypes.LPVOID) if descriptor else None
    try:
        for name in APP_MUTEXES:
            # Asking only for SYNCHRONIZE (what the access rules grant) also opens one another copy made.
            handle = _CreateMutexExW(security, name, 0, _SYNCHRONIZE)
            if handle:
                _held.append(handle)
            else:
                _log.warning("Could not create the mutex %s: %s", name, ctypes.WinError(ctypes.get_last_error()))
    finally:
        if descriptor:
            _LocalFree(descriptor)


def release_app_mutexes() -> None:
    """Let go of the mutexes early: an update's installer waits for them as the app exits."""
    while _held:
        _CloseHandle(_held.pop())
