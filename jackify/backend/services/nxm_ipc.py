"""Unix socket IPC for single-instance NXM URL routing.

The running Jackify instance listens on a QLocalServer. A second instance
launched by the OS protocol handler connects, sends the nxm:// URL, and exits.
"""

import logging
from typing import Optional

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

logger = logging.getLogger(__name__)

_SOCKET_NAME = "jackify-nxm-ipc"
_CONNECT_TIMEOUT_MS = 1000


class NxmIpcServer(QObject):
    """Listens for nxm:// URLs from secondary Jackify instances."""

    url_received = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._server: Optional[QLocalServer] = None

    def start(self) -> bool:
        QLocalServer.removeServer(_SOCKET_NAME)
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_connection)
        if not self._server.listen(_SOCKET_NAME):
            logger.warning("NXM IPC server failed to start: %s", self._server.errorString())
            return False
        logger.debug("NXM IPC server listening on %s", _SOCKET_NAME)
        return True

    def stop(self) -> None:
        if self._server:
            self._server.close()
            QLocalServer.removeServer(_SOCKET_NAME)
            self._server = None

    def _on_connection(self) -> None:
        conn = self._server.nextPendingConnection()
        if conn:
            conn.readyRead.connect(lambda: self._read(conn))

    def _read(self, conn: QLocalSocket) -> None:
        data = bytes(conn.readAll()).decode(errors="replace").strip()
        conn.disconnectFromServer()
        if data.startswith("nxm://"):
            logger.info("NXM IPC received URL: %s", data)
            self.url_received.emit(data)
        else:
            logger.warning("NXM IPC received unexpected data: %r", data[:80])


def send_to_running_instance(url: str) -> bool:
    """Send an nxm:// URL to the running Jackify instance.

    Returns True if a running instance was found and the URL was delivered.
    """
    socket = QLocalSocket()
    socket.connectToServer(_SOCKET_NAME)
    if not socket.waitForConnected(_CONNECT_TIMEOUT_MS):
        return False
    socket.write(url.encode())
    socket.flush()
    socket.waitForBytesWritten(500)
    socket.disconnectFromServer()
    logger.debug("NXM URL handed off to running instance")
    return True
