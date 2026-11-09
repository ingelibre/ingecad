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


class DeferredCommand(Command):
    """A step of a composite that can only be built once an earlier step
    has run -- clip and tag the IMAGE that the step before just created,
    send it to the back. ``factory(document)`` returns the real command;
    it is called afresh on every ``do`` (a redo recreates the entity, so
    the command must be rebuilt for the new one)."""

    def __init__(self, name: str, factory) -> None:
        self.name = name
        self._factory = factory
        self._inner = None

    def do(self, document) -> None:
        self._inner = self._factory(document)
        if self._inner is not None:
            self._inner.do(document)

    def undo(self, document) -> None:
        if self._inner is not None:
            self._inner.undo(document)


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
            # a member recorded by History brings its associative
            # dimensions along (a script folded into one step, #90), and
            # what the plugins' reactors did after it
            followup = getattr(command, "dimassoc_followup", None)
            if followup is not None:
                followup.do(document)
            for followup in getattr(command, "plugin_followups", ()):
                followup.do(document)

    def undo(self, document) -> None:
        removed = []
        for command in reversed(self.commands):
            for followup in reversed(getattr(command, "plugin_followups", ())):
                followup.undo(document)
            followup = getattr(command, "dimassoc_followup", None)
            if followup is not None:
                followup.undo(document)
            command.undo(document)
            removed.extend(getattr(command, "removed_handles", ()) or ())
        self.removed_handles = removed


# -- plugins' follow-up reactors (PluginSpec.reactors) ------------------------
#
# The associative dimensions' reactor (core.dimassoc) made general: a
# reactor has ``before(document)`` -> a state, or None when it has nothing
# to watch (a command then pays nothing), and ``react(document, state)`` ->
# a Command NOT yet done, or None. History runs it after the command, in
# the same undo step: a plugin keeps its derived geometry and its XDATA
# true after a MOVE, COPY, MIRROR or grip edit it does not own. Per
# process and counted per plugin, since several windows activate the same
# plugin. Proposed by the architecture plugin.
_REACTORS: list = []                 # [[owner, reactor, count]]


def register_reactor(reactor, owner: str) -> None:
    for entry in _REACTORS:
        if entry[0] == owner and entry[1] is reactor:
            entry[2] += 1
            return
    _REACTORS.append([owner, reactor, 1])


def unregister_reactors(owner: str) -> None:
    for entry in list(_REACTORS):
        if entry[0] == owner:
            entry[2] -= 1
            if entry[2] <= 0:
                _REACTORS.remove(entry)


def _log_reactor_error(what: str, reactor) -> None:
    import logging

    logging.getLogger("ingecad.plugins").exception(
        "a plugin's reactor %r failed in %s()", reactor, what)


class _States:
    """What ``record`` compares after a command: the associative
    dimensions' state and each plugin reactor's."""

    __slots__ = ("dimassoc", "plugins")

    def __init__(self, dimassoc, plugins) -> None:
        self.dimassoc = dimassoc
        self.plugins = plugins


def _plugin_states(document) -> list:
    states = []
    for _owner, reactor, _count in list(_REACTORS):
        try:
            state = reactor.before(document)
        except Exception:                 # noqa: BLE001 - a plugin's fault
            _log_reactor_error("before", reactor)
            continue
        if state is not None:
            states.append((reactor, state))
    return states


class History:
    """Undo/redo stacks. ``execute`` runs and records a command."""

    def __init__(self, document=None) -> None:
        self.document = document
        self._undo: list[Command] = []
        self._redo: list[Command] = []
        #: Called before anything mutates the document, if set. The window
        #: uses it to let a running automatic save finish first: writing a
        #: real plan takes a second or two on a worker thread, and the
        #: drawing must not change under the writer's feet.
        self.before_mutation = None

    def _gate(self) -> None:
        if self.before_mutation is not None:
            self.before_mutation()

    def execute(self, command: Command) -> None:
        self._gate()
        state = self.dimassoc_state()
        command.do(self.document)
        self.record(command, state)

    def dimassoc_state(self):
        """The associative dimensions as they are now (core.dimassoc), to
        hand to ``record`` once the command has mutated the drawing."""
        from core import dimassoc

        if self.document is None:
            return None
        state = dimassoc.before(self.document)
        if not _REACTORS:
            return state                  # no plugin reacts: as it always was
        plugins = _plugin_states(self.document)
        return _States(state, plugins) if plugins else state

    def record(self, command: Command, dimassoc_state=None) -> None:
        """Put an already-applied command on the undo stack (execute's last
        step; grips and in-place edits, which mutate first, call it alone).

        With the ``dimassoc_state`` taken before the mutation, associative
        dimensions follow their objects in the same undo step. Grips called
        this without one and a dimension stayed behind its line (#90)."""
        plugin_states = []
        if isinstance(dimassoc_state, _States):
            dimassoc_state, plugin_states = (dimassoc_state.dimassoc,
                                             dimassoc_state.plugins)
        if dimassoc_state is not None:
            from core import dimassoc

            command.dimassoc_followup = dimassoc.react(self.document,
                                                       dimassoc_state)
            if command.dimassoc_followup is not None:
                command.dimassoc_followup.do(self.document)
        followups = []
        for reactor, state in plugin_states:
            try:
                followup = reactor.react(self.document, state)
                if followup is not None:
                    followup.do(self.document)
                    followups.append(followup)
            except Exception:             # noqa: BLE001 - a plugin's fault
                _log_reactor_error("react", reactor)
        if followups:
            command.plugin_followups = followups
            # what a follow-up changed is not among the command's own
            # entities: only a regen shows it
            command.needs_regen = True
        self._undo.append(command)
        self._redo.clear()
        self._mark_blocks(command, applied=True)

    def _mark_blocks(self, command: Command, applied: bool = False) -> None:
        """Tell the document a block definition changed: anything done in
        the Block Editor, or by a command that says it redefines blocks.
        What caches a definition's geometry (the snap engine) keys on
        ``blocks_revision``. Decided when the command is applied and kept
        on it, so its undo after BCLOSE still counts."""
        document = self.document
        if document is None:
            return
        if applied:
            command._touched_blocks = bool(
                getattr(command, "touches_blocks", False)
                or getattr(document, "edit_block", None) is not None
                or any(getattr(c, "_touched_blocks", False)
                       for c in getattr(command, "commands", ())))
        if getattr(command, "_touched_blocks", False):
            document.blocks_revision = getattr(document, "blocks_revision", 0) + 1

    def fold(self, since: int, name: str) -> int:
        """Fold everything recorded after undo-stack depth ``since`` into
        ONE step called ``name``: an APPLOAD script, a turn of the AI
        assistant -- what it did goes away with a single U. Returns how
        many entries there were."""
        added = self._undo[since:]
        if len(added) > 1:
            del self._undo[since:]
            composite = CompositeCommand(name, added)
            composite._space = None          # already done; do() is not re-run here
            self.record(composite)
        return len(added)

    @property
    def depth(self) -> int:
        """How many steps there are to undo: a mark for :meth:`fold` and
        :meth:`undo_to`."""
        return len(self._undo)

    def undo_to(self, depth: int) -> list:
        """Undo back to ``depth`` and forget those steps (they cannot be
        redone): an operation of several commands that gave up half-way
        leaves no trace. Returns the commands undone, latest first."""
        undone = []
        while len(self._undo) > max(0, depth):
            command = self.undo()
            if command is None:
                break
            undone.append(command)
        for command in reversed(undone):   # the last undone is on top
            if self._redo and self._redo[-1] is command:
                self._redo.pop()
        return undone

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> Command | None:
        if not self._undo:
            return None
        self._gate()
        command = self._undo.pop()
        for followup in reversed(getattr(command, "plugin_followups", ())):
            followup.undo(self.document)
        followup = getattr(command, "dimassoc_followup", None)
        if followup is not None:
            followup.undo(self.document)
        command.undo(self.document)
        self._redo.append(command)
        self._mark_blocks(command)
        return command

    def redo(self) -> Command | None:
        self._gate()
        if not self._redo:
            return None
        command = self._redo.pop()
        command.do(self.document)
        followup = getattr(command, "dimassoc_followup", None)
        if followup is not None:
            followup.do(self.document)
        for followup in getattr(command, "plugin_followups", ()):
            followup.do(self.document)
        self._undo.append(command)
        self._mark_blocks(command)
        return command

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()
