# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""One IngeCAD per user: a drawing opened from the file manager while
IngeCAD runs becomes a tab of the running window, as AutoCAD does.

Without this, every double-click started a second program with a window
of its own, and the drawing tabs (#71) were only reachable through
File > Open.

The first IngeCAD listens on a local socket. A later one with drawings
to open hands them over the socket and quits; one started from the menu,
with nothing to open, gets a window of its own as before. Two started at
once both find no listener; the socket file decides which one listens,
and the other hands over to it. A socket that refuses the connection was
left by an IngeCAD that crashed, and is replaced. (No lock file: inside
the Flatpak every instance has its own process numbers, so a dead
instance's lock would look alive.)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QStandardPaths
from PySide6.QtNetwork import QLocalServer, QLocalSocket

#: a running IngeCAD answers from its event loop; one still starting up
#: (building its window) can take a few seconds to
ANSWER_MS = 15000


def _runtime_dir() -> Path:
    """Where the socket lives: shared by every IngeCAD of this
    user -- inside the Flatpak, by every instance of the app (its /tmp is
    not, so a socket there would not be found)."""
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    flatpak = os.environ.get("FLATPAK_ID")
    if runtime and flatpak:
        return Path(runtime) / "app" / flatpak
    if runtime:
        return Path(runtime)
    return Path(QStandardPaths.writableLocation(
        QStandardPaths.TempLocation))


def server_name() -> str:
    if sys.platform == "win32":
        return f"ingecad-{os.environ.get('USERNAME', 'user')}"  # a named pipe
    return str(_runtime_dir() / "ingecad.sock")


def _connect(name: str) -> QLocalSocket | None:
    socket = QLocalSocket()
    socket.connectToServer(name)
    return socket if socket.waitForConnected(1000) else None


def running(name: str | None = None) -> bool:
    """Is an IngeCAD listening (not just a crashed one's socket file)?"""
    socket = _connect(name or server_name())
    if socket is None:
        return False
    socket.disconnectFromServer()
    return True


def forward(paths: list[str], name: str | None = None,
            answer_ms: int = ANSWER_MS) -> bool:
    """Hand ``paths`` to the running IngeCAD. True when it took them."""
    socket = _connect(name or server_name())
    if socket is None:
        return False
    payload = json.dumps({"open": [str(p) for p in paths]}) + "\n"
    socket.write(payload.encode("utf-8"))
    if not socket.waitForBytesWritten(answer_ms):
        return False
    answer = b""
    while not answer.endswith(b"\n"):
        if not socket.waitForReadyRead(answer_ms):
            break
        answer += bytes(socket.readAll().data())
    socket.disconnectFromServer()
    return answer.strip() == b"ok"


class InstanceServer(QObject):
    """The running IngeCAD's end. Drawings that arrive before a window can
    take them (the start-up dialogs are still up) wait in ``pending``."""

    def __init__(self, name: str | None = None, parent=None) -> None:
        super().__init__(parent)
        self.name = name or server_name()
        self.pending: list[str] = []
        self._deliver = None
        self._buffers: dict[QLocalSocket, bytes] = {}
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_connection)

    def listen(self, replace: bool = False) -> bool:
        if replace:
            QLocalServer.removeServer(self.name)    # a crashed one's socket
        return self._server.listen(self.name)

    def close(self) -> None:
        self._server.close()

    def set_target(self, deliver) -> None:
        """``deliver(paths)`` opens them; whatever waited goes now."""
        self._deliver = deliver
        self._flush()

    def _flush(self) -> None:
        if self._deliver is None or not self.pending:
            return
        paths, self.pending = self.pending, []
        self._deliver(paths)

    def _on_connection(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            self._buffers[socket] = b""
            socket.readyRead.connect(self._on_ready_read)
            socket.disconnected.connect(self._on_disconnected)
            if socket.bytesAvailable():
                self._read(socket)

    def _on_ready_read(self) -> None:
        socket = self.sender()
        if isinstance(socket, QLocalSocket):
            self._read(socket)

    def _on_disconnected(self) -> None:
        socket = self.sender()
        if isinstance(socket, QLocalSocket):
            self._buffers.pop(socket, None)
            socket.deleteLater()

    def _read(self, socket: QLocalSocket) -> None:
        data = self._buffers.get(socket, b"") + bytes(socket.readAll().data())
        self._buffers[socket] = data
        if not data.endswith(b"\n"):
            return
        try:
            paths = [str(p) for p in json.loads(data.decode("utf-8"))["open"]]
        except (ValueError, KeyError, TypeError):
            socket.write(b"bad\n")
            return
        socket.write(b"ok\n")
        socket.flush()
        self.pending.extend(paths)
        self._flush()


def claim(paths: list[str], name: str | None = None):
    """At start-up: the server if this is the first IngeCAD, or None after
    handing ``paths`` to the one already running (the caller then quits).
    One with nothing to open, while another runs, is left on its own.

    Anything unexpected -- no runtime directory, a socket that cannot be
    made -- leaves this IngeCAD on its own too: a second window is better
    than no window."""
    name = name or server_name()
    try:
        if sys.platform != "win32":
            Path(name).parent.mkdir(parents=True, exist_ok=True)
        if paths and forward(paths, name):
            return None
        server = InstanceServer(name)
        if server.listen():
            return server
        # taken: by an IngeCAD that started a moment ago, or by a crashed
        # one's socket file, which refuses the connection
        if running(name):
            if paths and forward(paths, name):
                return None
            return _Alone()
        if server.listen(replace=True):
            return server
    except Exception:
        pass
    return _Alone()


class _Alone:
    """No single instance this time: takes the calls, does nothing."""

    pending: list[str] = []

    def set_target(self, deliver) -> None:
        pass

    def close(self) -> None:
        pass
