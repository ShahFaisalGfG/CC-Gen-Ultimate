"""Collect QtNetwork without Qt's OpenSSL backend or any OpenSSL DLLs.

PyInstaller's own hook looks up libssl-3-x64.dll and libcrypto-3-x64.dll on PATH, since the
PySide6 wheel ships none, and so bundles whatever copies the build machine has (for example Git
for Windows'). The first QtNetwork object loads Qt's OpenSSL backend, which loads libssl by name
from System32 before the bundle, pairing a foreign libssl with the bundled libcrypto and crashing
at startup. Choosing another backend at runtime comes too late, so the backend is left out. The
app only uses QtNetwork for its local API, so Schannel (Windows' TLS) is enough. The build's
self-test (ccgen/utils/self_test.py) fails if either the backend or the DLLs come back.
"""

from pathlib import Path

from PyInstaller.utils.hooks.qt import add_qt6_dependencies

_OPENSSL_BACKEND = "qopensslbackend.dll"

hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
binaries = [entry for entry in binaries if Path(entry[0]).name.casefold() != _OPENSSL_BACKEND]
