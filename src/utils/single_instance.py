"""
Single running instance per user.

The first instance listens on a local socket (a named pipe on Windows, released
automatically when the process dies, so there are no stale lock files). A second
start just asks the running instance to show its window and exits.
"""

import getpass
import logging
import re
import sys

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from src.core.paths import APP_ID

LOGGER = logging.getLogger(__name__)
MESSAGE_SHOW = b"show"


def allow_foreground_switch() -> None:
    """Windows only lets the process the user just started bring a window to the
    front; pass that right on, so the running instance can raise its window
    instead of only flashing its taskbar button."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        allow = user32.AllowSetForegroundWindow
        allow.argtypes = [ctypes.c_uint32]
        allow.restype = ctypes.c_int
        allow(0xFFFFFFFF)  # ASFW_ANY
    except (OSError, AttributeError):
        LOGGER.debug("AllowSetForegroundWindow failed", exc_info=True)


def server_name() -> str:
    try:
        user = getpass.getuser()
    except Exception:
        user = "user"
    return f"{APP_ID}-{re.sub(r'[^A-Za-z0-9_.-]', '_', user)}"


class SingleInstance(QObject):
    activationRequested = Signal()

    def __init__(self, name: str | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._name = name or server_name()
        self._server: QLocalServer | None = None

    def notify_running_instance(self, timeout_ms: int = 400) -> bool:
        """True if another instance is running (and was asked to show itself)."""
        socket = QLocalSocket()
        socket.connectToServer(self._name)
        if not socket.waitForConnected(timeout_ms):
            return False
        allow_foreground_switch()
        socket.write(MESSAGE_SHOW)
        socket.flush()
        socket.waitForBytesWritten(timeout_ms)
        socket.disconnectFromServer()
        return True

    def listen(self) -> bool:
        QLocalServer.removeServer(self._name)  # stale socket file after a crash (Unix only)
        server = QLocalServer(self)
        server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        if not server.listen(self._name):
            LOGGER.warning("Single-instance server could not listen: %s", server.errorString())
            return False
        server.newConnection.connect(self._on_connection)
        self._server = server
        return True

    def _on_connection(self) -> None:
        while self._server is not None and self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            socket.readyRead.connect(lambda s=socket: self._read(s))
            socket.disconnected.connect(socket.deleteLater)
            if socket.bytesAvailable():
                self._read(socket)

    def _read(self, socket: QLocalSocket) -> None:
        if MESSAGE_SHOW in bytes(socket.readAll().data()):
            self.activationRequested.emit()

    def close(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None
