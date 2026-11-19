# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The window's end of the MCP bridge: a local socket the ``--mcp``
process (core/ai/mcp_server.py) talks to.

Only while the bridge is on (Options > AI Assistant, or MCPSTART). No
network port: a Unix socket in the user's runtime folder (a named pipe on
Windows), and a token in a file only the user can read -- the first line
a client sends must carry it, or the connection is closed. Another user
on the machine, or a program of this user that has not read the file,
gets nothing.

One JSON object per line, both ways:

    -> {"token": "..."}                      <- {"ok": true}
    -> {"id": 1, "call": "draw_line", "arguments": {...}}
    <- {"id": 1, "result": {...}}            (a picture: {"image": b64, "note"})

Every call runs on the GUI thread through core.ai.tools -- the same
Commands as the keyboard -- and is one undo step.
"""
from __future__ import annotations

import json
import os
import secrets as _random
from pathlib import Path

from PySide6.QtCore import QObject
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from core.ai.mcp_server import server_name, token_path

#: a request bigger than this is not a drawing command: drop the client
MAX_LINE = 4 * 1024 * 1024


def _write_token(path: Path, token: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as handle:
        handle.write(token)
    if os.name == "posix":
        os.chmod(path, 0o600)


def encode(result) -> dict:
    """A tool's result as it travels: an Image becomes base64."""
    from core.ai.tools import Image

    if isinstance(result, Image):
        return {"image": result.base64(), "note": result.note}
    return result


class Bridge(QObject):
    """Serves core.ai.tools to ``--mcp`` processes for ``window``."""

    def __init__(self, window, name: str | None = None,
                 token_file: Path | None = None) -> None:
        super().__init__(window)
        self.window = window
        self.name = name or server_name()
        self.token_file = token_file or token_path()
        self.token = ""
        self._buffers: dict[QLocalSocket, bytes] = {}
        self._trusted: set = set()
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.UserAccessOption)
        self._server.newConnection.connect(self._on_connection)

    # -- asking the user (a method, so tests can answer) --------------------------
    def confirm(self, question: str) -> bool:
        from PySide6.QtWidgets import QMessageBox

        from core.i18n import tr

        answer = QMessageBox.question(self.window, tr("AI Assistant"),
                                      question + "\n\n" + tr("Allow it?"))
        return answer == QMessageBox.Yes

    # -- on and off ------------------------------------------------------------------
    def listen(self) -> bool:
        """Start serving. False when another IngeCAD already does."""
        from core.single_instance import running

        if running(self.name):
            return False
        QLocalServer.removeServer(self.name)     # a crashed one's socket
        if not self._server.listen(self.name):
            return False
        self.token = _random.token_hex(32)
        _write_token(self.token_file, self.token)
        return True

    def is_listening(self) -> bool:
        return self._server.isListening()

    def close(self) -> None:
        for socket in list(self._buffers):
            socket.disconnectFromServer()
        self._buffers.clear()
        self._trusted.clear()
        if self._server.isListening():
            self._server.close()
            try:
                if self.token_file.read_text(encoding="ascii") == self.token:
                    self.token_file.unlink()
            except OSError:
                pass
        self.token = ""

    # -- the conversation -----------------------------------------------------------
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
            self._trusted.discard(socket)
            socket.deleteLater()

    def _send(self, socket: QLocalSocket, message: dict) -> None:
        socket.write((json.dumps(message) + "\n").encode("utf-8"))
        socket.flush()

    def _read(self, socket: QLocalSocket) -> None:
        if socket not in self._buffers:
            return
        data = self._buffers[socket] + bytes(socket.readAll().data())
        if len(data) > MAX_LINE:
            self._drop(socket)
            return
        *lines, rest = data.split(b"\n")
        self._buffers[socket] = rest
        for line in lines:
            if socket not in self._buffers:     # dropped by an earlier line
                return
            if line.strip():
                self._handle(socket, line)

    def _drop(self, socket: QLocalSocket) -> None:
        self._buffers.pop(socket, None)
        self._trusted.discard(socket)
        socket.disconnectFromServer()

    def _handle(self, socket: QLocalSocket, line: bytes) -> None:
        try:
            message = json.loads(line.decode("utf-8"))
            if not isinstance(message, dict):
                raise ValueError
        except ValueError:
            self._drop(socket)
            return
        if socket not in self._trusted:
            if self.token and _random.compare_digest(
                    str(message.get("token", "")), self.token):
                self._trusted.add(socket)
                self._send(socket, {"ok": True})
            else:
                self._send(socket, {"error": "bad token"})
                self._drop(socket)
            return
        if message.get("list") is True:
            # the catalogue of this window: the core's tools and those of
            # its active plugins, which the MCP process cannot know
            from core.ai import tools as ai

            self._send(socket, {"id": message.get("id"),
                                "result": {"tools": ai.tool_list()}})
            return
        self._send(socket, {"id": message.get("id"),
                            "result": self._call(message)})

    def _call(self, message: dict):
        from core.ai import tools as ai
        from core.i18n import tr

        name = str(message.get("call", ""))
        args = message.get("arguments") or {}
        if not isinstance(args, dict):
            return {"error": "arguments must be an object"}
        if self.window.document is None:
            self.window.new_document()
        with ai.Turn(self.window, tr("AI")):
            result = ai.call(self.window, name, args, confirm=self.confirm)
        return encode(result)
