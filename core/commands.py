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

    def space(self, document):
        """The space this command works in, PINNED at its first run.

        ``Document.current_space()`` answers "where is the user now", and
        that is right while a command runs — but undo happens later, and by
        then the user may be on another tab. An ERASE on a sheet undone
        from the Model tab put the entity back in the modelspace, because
        the command asked the same question twice and got two answers.
        A command asks once and remembers.
        """
        space = getattr(self, "_space", None)
        if space is None:
            space = document.current_space()
            self._space = space
        return space


class CompositeCommand(Command):
    """Several sub-commands executed as ONE undo step (DIVIDE's n-1 points,
    REVCLOUD Object's erase+add). needs_regen because the members bypass
    the incremental display paths."""

    needs_regen = True

    def __init__(self, name: str, commands) -> None:
        self.name = name
        self.commands = list(commands)

    def do(self, document) -> None:
        for command in self.commands:
            command.do(document)

    def undo(self, document) -> None:
        removed = []
        for command in reversed(self.commands):
            command.undo(document)
            removed.extend(getattr(command, "removed_handles", ()) or ())
        self.removed_handles = removed


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
