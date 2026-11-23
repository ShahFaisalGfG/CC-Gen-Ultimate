# taskbar.py - a run's progress on the app's taskbar button (Windows ITaskbarList3)
#
# Qt 6 dropped QWinTaskbarProgress, so this calls the COM interface directly with ctypes. Qt has
# already initialized COM on the GUI thread, which is the only thread that calls in here.

from __future__ import annotations

import ctypes
import logging
import sys
import uuid

NO_PROGRESS, INDETERMINATE, NORMAL, ERROR, PAUSED = 0, 0x1, 0x2, 0x4, 0x8
_SCALE = 1000

_log = logging.getLogger(__name__)


class _Guid(ctypes.Structure):
    _fields_ = [("data", ctypes.c_ubyte * 16)]

    @classmethod
    def parse(cls, text: str) -> _Guid:
        """The GUID written as text, in the byte order COM expects."""
        guid = cls()
        ctypes.memmove(guid.data, uuid.UUID(text).bytes_le, 16)
        return guid


_CLSID_TASKBAR_LIST = "56FDF344-FD6D-11d0-958A-006097C9A090"
_IID_ITASKBAR_LIST3 = "EA1AFB91-9E28-4B86-90E9-9E9F8A5EEFAF"
_CLSCTX_INPROC_SERVER = 1
# vtable slots: IUnknown 0-2, ITaskbarList HrInit 3, ..., ITaskbarList3 SetProgressValue 9, SetProgressState 10
_RELEASE, _HR_INIT, _SET_VALUE, _SET_STATE = 2, 3, 9, 10


class TaskbarProgress:
    """Progress on one window's taskbar button; every call quietly does nothing off Windows."""

    def __init__(self) -> None:
        self._pointer = ctypes.c_void_p()
        self._hwnd = 0
        self._state = -1
        if sys.platform != "win32":
            return
        try:
            clsid = _Guid.parse(_CLSID_TASKBAR_LIST)
            iid = _Guid.parse(_IID_ITASKBAR_LIST3)
            result = ctypes.windll.ole32.CoCreateInstance(ctypes.byref(clsid), None, _CLSCTX_INPROC_SERVER,
                                                          ctypes.byref(iid), ctypes.byref(self._pointer))
            if result != 0 or not self._pointer:
                self._pointer = ctypes.c_void_p()
                return
            self._method(_HR_INIT)(self._pointer)
        except OSError as error:
            _log.info("Taskbar progress unavailable: %s", error)
            self._pointer = ctypes.c_void_p()

    def _method(self, slot: int, *argtypes: object):
        """The COM method in vtable slot `slot`, taking the interface pointer and `argtypes`."""
        vtable = ctypes.cast(self._pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        prototype = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, *argtypes)  # type: ignore[attr-defined]
        return prototype(vtable[slot])

    def attach(self, hwnd: int) -> None:
        """Show progress on this window's button."""
        self._hwnd = hwnd

    def update(self, fraction: float | None, state: int = NORMAL) -> None:
        """Set progress (0..1), or None to clear it; state picks the colour (normal, paused, error)."""
        if not self._pointer or not self._hwnd:
            return
        try:
            if fraction is None:
                if self._state != NO_PROGRESS:
                    self._method(_SET_STATE, ctypes.c_void_p, ctypes.c_int)(self._pointer, self._hwnd, NO_PROGRESS)
                    self._state = NO_PROGRESS
                return
            if state != self._state:
                self._method(_SET_STATE, ctypes.c_void_p, ctypes.c_int)(self._pointer, self._hwnd, state)
                self._state = state
            if state != INDETERMINATE:
                value = int(max(0.0, min(fraction, 1.0)) * _SCALE)
                self._method(_SET_VALUE, ctypes.c_void_p, ctypes.c_ulonglong, ctypes.c_ulonglong)(
                    self._pointer, self._hwnd, value, _SCALE)
        except OSError as error:
            _log.info("Taskbar progress failed: %s", error)

    def close(self) -> None:
        """Clear the button and release the COM object."""
        if self._pointer:
            self.update(None)
            self._method(_RELEASE)(self._pointer)
            self._pointer = ctypes.c_void_p()
