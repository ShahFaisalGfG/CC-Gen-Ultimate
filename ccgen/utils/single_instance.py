# single_instance.py - one CC-Gen-Ultimate window per user session; later launches hand their files to it
#
# The first launch listens on a local pipe. A later launch (Explorer's menu, "Open with", a
# shortcut) connects, sends its request as one line of JSON, and exits once the window answers
# "OK", so its files join the open window's queues instead of starting a second copy that loads its
# own models. With no answer within _ANSWER_MS it opens its own window, so its files are never
# lost. The window answers at once but holds the requests until it has loaded (attach()), and
# drops a request whose sender stopped waiting, which has already opened the files itself.
# On Windows two QLocalServers can listen on one pipe name, so a named mutex turns "try to send,
# else listen" into one step: simultaneous launches (several files opened with Enter) end with one
# window. The pipe name carries the user's SID and session id, only this user may connect, and a
# sender writes only to a pipe served by its own account, so another account can't take the name
# and read the paths.
#
# The installers' mutexes (app_mutex.py) are separate: the window holds them while it runs.

from __future__ import annotations

import ctypes
import logging
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from ctypes import wintypes
from functools import partial
from typing import Any

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from ccgen.utils.launch import LaunchRequest

APP_PREFIX = "CC-Gen-Ultimate"
_CONNECT_MS = 2000
_ANSWER_MS = 10_000      # how long a later launch waits for the window to take its request
_LOCK_MS = 30_000        # longer than one sender holds the lock: connect + _ANSWER_MS
_ACK_WRITE_MS = 1000
_ACK = b"OK\n"
_TOKEN_QUERY = 0x0008
_TOKEN_USER = 1
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_WAIT_OBJECT_0 = 0x0
_WAIT_ABANDONED = 0x80
_ASFW_ANY = 0xFFFFFFFF

_log = logging.getLogger(__name__)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
_user32 = ctypes.WinDLL("user32", use_last_error=True)


def _api(dll: ctypes.WinDLL, name: str, restype: Any, *argtypes: Any) -> Any:
    """A function of dll with its result and argument types declared."""
    function = getattr(dll, name)
    function.restype = restype
    function.argtypes = argtypes
    return function


_GetCurrentProcess = _api(_kernel32, "GetCurrentProcess", wintypes.HANDLE)
_GetCurrentProcessId = _api(_kernel32, "GetCurrentProcessId", wintypes.DWORD)
_ProcessIdToSessionId = _api(_kernel32, "ProcessIdToSessionId", wintypes.BOOL,
                             wintypes.DWORD, ctypes.POINTER(wintypes.DWORD))
_OpenProcess = _api(_kernel32, "OpenProcess", wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
_CloseHandle = _api(_kernel32, "CloseHandle", wintypes.BOOL, wintypes.HANDLE)
_LocalFree = _api(_kernel32, "LocalFree", wintypes.HLOCAL, wintypes.HLOCAL)
_CreateMutexW = _api(_kernel32, "CreateMutexW", wintypes.HANDLE, wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
_WaitForSingleObject = _api(_kernel32, "WaitForSingleObject", wintypes.DWORD, wintypes.HANDLE, wintypes.DWORD)
_ReleaseMutex = _api(_kernel32, "ReleaseMutex", wintypes.BOOL, wintypes.HANDLE)
_GetNamedPipeServerProcessId = _api(_kernel32, "GetNamedPipeServerProcessId", wintypes.BOOL,
                                    wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG))
_OpenProcessToken = _api(_advapi32, "OpenProcessToken", wintypes.BOOL,
                         wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE))
_GetTokenInformation = _api(_advapi32, "GetTokenInformation", wintypes.BOOL, wintypes.HANDLE, ctypes.c_int,
                            wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD))
_ConvertSidToStringSidW = _api(_advapi32, "ConvertSidToStringSidW", wintypes.BOOL,
                               wintypes.LPVOID, ctypes.POINTER(wintypes.LPWSTR))
_AllowSetForegroundWindow = _api(_user32, "AllowSetForegroundWindow", wintypes.BOOL, wintypes.DWORD)


class SingleInstance(QObject):
    """Routes later launches to the first CC-Gen-Ultimate window of this user session."""

    # Every later launch, with or without files, as its LaunchRequest: the window comes to the
    # front and queues the files.
    launchReceived = Signal(object)

    def __init__(self, prefix: str = APP_PREFIX, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._sid = _own_sid()
        account = self._sid or os.environ.get("USERNAME", "user")
        self._pipe_name = f"{prefix}-{account}-{_session_id()}"
        self._mutex_name = f"Local\\{prefix}-instance-{account}"
        self._server: QLocalServer | None = None
        self._inboxes: dict[QLocalSocket, bytearray] = {}
        self._pending: list[LaunchRequest] = []
        self._attached = False

    def try_forward(self, request: LaunchRequest) -> bool:
        """Hand the launch to the open window and return True, or return False to open a window.

        With no window to hand it to, this process starts listening for later launches.
        """
        with _named_mutex(self._mutex_name):
            sock = QLocalSocket()
            sock.connectToServer(self._pipe_name)
            if not sock.waitForConnected(_CONNECT_MS):
                if sock.error() == QLocalSocket.LocalSocketError.ServerNotFoundError:
                    self._listen()
                else:
                    _log.warning("The open CC-Gen-Ultimate window can't be reached (%s); opening a new window",
                                 sock.errorString())
                return False
            try:
                return self._send(sock, request)
            finally:
                sock.abort()

    def attach(self) -> None:
        """Deliver the launches that arrived while the window was loading, in order, then each as it comes."""
        self._attached = True
        pending, self._pending = self._pending, []
        for request in pending:
            self.launchReceived.emit(request)

    def close(self) -> None:
        """Stop listening for later launches (on exit)."""
        if self._server is not None:
            self._server.close()
            self._server = None

    # ── Sending (a later launch) ─────────────────────────────────────────────

    def _send(self, sock: QLocalSocket, request: LaunchRequest) -> bool:
        """Write the request and wait for the window's answer; False when it doesn't come in time."""
        if not self._sid or _pipe_owner(sock) != self._sid:
            _log.warning("The CC-Gen-Ultimate pipe isn't served by this account; opening a new window")
            return False
        _AllowSetForegroundWindow(_ASFW_ANY)  # lets the open window come to the front
        deadline = time.monotonic() + _ANSWER_MS / 1000
        sock.write(request.encode())
        while sock.bytesToWrite() > 0:
            if not sock.waitForBytesWritten(_left_ms(deadline)):
                return _gave_up(sock)
        # The answer can arrive while the write is still being waited on; it is then already
        # buffered, and waitForReadyRead() only waits for more, so read before every wait.
        answer = bytearray(sock.readAll().data())
        while b"\n" not in answer:
            if not sock.waitForReadyRead(_left_ms(deadline)):
                return _gave_up(sock)
            answer += sock.readAll().data()
        return bytes(answer).startswith(_ACK)

    # ── Receiving (the window) ───────────────────────────────────────────────

    def _listen(self) -> None:
        """Start the server later launches connect to; only this user's processes may connect."""
        server = QLocalServer(self)
        server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        server.newConnection.connect(self._accept)
        if server.listen(self._pipe_name):
            self._server = server
        else:
            _log.warning("Could not listen for later CC-Gen-Ultimate launches: %s", server.errorString())
            server.deleteLater()

    def _accept(self) -> None:
        """Take every waiting connection; each one carries a single request line."""
        server = self._server
        while server is not None and server.hasPendingConnections():
            sock = server.nextPendingConnection()
            self._inboxes[sock] = bytearray()
            sock.readyRead.connect(partial(self._read, sock))
            sock.disconnected.connect(partial(self._closed, sock))

    def _read(self, sock: QLocalSocket) -> None:
        """Collect bytes until the request line is complete, then answer and queue it."""
        inbox = self._inboxes.get(sock)
        if inbox is None:
            return
        inbox += sock.readAll().data()
        line, complete, _rest = inbox.partition(b"\n")
        if not complete:
            return
        del self._inboxes[sock]
        try:
            request = LaunchRequest.decode(bytes(line))
        except ValueError as error:
            _log.warning("Could not read a message from another CC-Gen-Ultimate launch: %s", error)
            sock.disconnectFromServer()
            return
        sock.write(_ACK)
        if not sock.waitForBytesWritten(_ACK_WRITE_MS):
            _log.info("A later CC-Gen-Ultimate launch stopped waiting and opened its own window")
            return
        if self._attached:
            self.launchReceived.emit(request)
        else:
            self._pending.append(request)

    def _closed(self, sock: QLocalSocket) -> None:
        """Handle what a sender wrote just before hanging up, then free its socket."""
        self._read(sock)
        self._inboxes.pop(sock, None)
        sock.deleteLater()


@contextmanager
def _named_mutex(name: str) -> Iterator[None]:
    """Hold the named mutex for a with-block, waiting up to _LOCK_MS for another launch to release it."""
    handle = _CreateMutexW(None, False, name)
    owned = bool(handle) and _WaitForSingleObject(handle, _LOCK_MS) in (_WAIT_OBJECT_0, _WAIT_ABANDONED)
    if not owned:
        _log.warning("Could not take the mutex %s; going on without it", name)
    try:
        yield
    finally:
        if owned:
            _ReleaseMutex(handle)
        if handle:
            _CloseHandle(handle)


def _left_ms(deadline: float) -> int:
    """Milliseconds until deadline (0 once it has passed)."""
    return max(0, int((deadline - time.monotonic()) * 1000))


def _gave_up(sock: QLocalSocket) -> bool:
    """Log that the window didn't take the request in time and return False (open a new window)."""
    _log.warning("The open CC-Gen-Ultimate window didn't answer in %d s (%s); opening a new window",
                 _ANSWER_MS // 1000, sock.errorString())
    return False


def _session_id() -> int:
    """This process's Windows session id (0 if it can't be read)."""
    session = wintypes.DWORD()
    if _ProcessIdToSessionId(_GetCurrentProcessId(), ctypes.byref(session)):
        return session.value
    _log.warning("Could not read the session id: %s", ctypes.WinError(ctypes.get_last_error()))
    return 0


def _own_sid() -> str:
    """The SID of the account this process runs as, or "" (logged) if it can't be read."""
    try:
        return _process_sid(_GetCurrentProcess())
    except OSError as error:
        _log.warning("Could not read this account's SID: %s", error)
        return ""


def _pipe_owner(sock: QLocalSocket) -> str:
    """The SID of the account whose process serves the pipe sock is connected to, or "" if unknown."""
    pid = wintypes.ULONG()
    if not _GetNamedPipeServerProcessId(int(sock.socketDescriptor()), ctypes.byref(pid)):
        return ""
    process = _OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not process:
        return ""
    try:
        return _process_sid(process)
    except OSError:
        return ""
    finally:
        _CloseHandle(process)


def _process_sid(process: int) -> str:
    """The string SID ("S-1-5-21-...") of the account a process runs as; raises OSError on failure."""
    token = wintypes.HANDLE()
    if not _OpenProcessToken(process, _TOKEN_QUERY, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        size = wintypes.DWORD()
        _GetTokenInformation(token, _TOKEN_USER, None, 0, ctypes.byref(size))
        buffer = ctypes.create_string_buffer(size.value)
        if not _GetTokenInformation(token, _TOKEN_USER, buffer, size, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        sid = ctypes.cast(buffer, ctypes.POINTER(wintypes.LPVOID))[0]  # TOKEN_USER starts with the SID pointer
        text = wintypes.LPWSTR()
        if not _ConvertSidToStringSidW(sid, ctypes.byref(text)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return text.value or ""
        finally:
            _LocalFree(ctypes.cast(text, wintypes.HLOCAL))
    finally:
        _CloseHandle(token)
