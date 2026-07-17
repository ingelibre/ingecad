# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Command pattern + undo history (ported concept from IngeTrazo).

Every document mutation goes through a Command so undo/redo is exact —
the AI-native invariant of the ecosystem. Drawing/editing commands arrive
in Phases 4-5; the history machinery lands now so U/REDO exist from the
first day of the command line.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class Command(ABC):
    """One reversible document mutation."""

    name = "command"

    @abstractmethod
    def do(self, document) -> None: ...

    @abstractmethod
    def undo(self, document) -> None: ...


class History:
    """Undo/redo stacks. ``execute`` runs and records a command."""

    def __init__(self, document=None) -> None:
        self.document = document
        self._undo: list[Command] = []
        self._redo: list[Command] = []

    def execute(self, command: Command) -> None:
        command.do(self.document)
        self._undo.append(command)
        self._redo.clear()

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> Command | None:
        if not self._undo:
            return None
        command = self._undo.pop()
        command.undo(self.document)
        self._redo.append(command)
        return command

    def redo(self) -> Command | None:
        if not self._redo:
            return None
        command = self._redo.pop()
        command.do(self.document)
        self._undo.append(command)
        return command

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()
