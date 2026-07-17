# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Headless command dispatch — every prompt keystroke ends up here.

The dispatcher owns the AutoCAD prompt semantics that the UI must not
reimplement: alias resolution, Enter-on-empty repeats the last command,
multi-step prompts (``Z`` then ``E``), Esc cancels. Handlers are plain
callables registered by the application, so the whole flow is testable
without a GUI (the AI-native invariant: every command is a headless
action first).

A handler may return a :class:`Prompt` to ask for more input; the next
submitted line goes to its callback instead of starting a new command.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from core import aliases as aliases_mod
from core.i18n import tr


@dataclass
class Prompt:
    """A continuation: show ``text`` and send the next input line to ``on_input``."""

    text: str
    on_input: Callable[[str], Optional["Prompt"]]


@dataclass
class _Entry:
    handler: Callable[..., Optional[Prompt]]
    phase: int = 0  # 0 = implemented; else "arrives in Phase N"


@dataclass
class Dispatcher:
    """Parses prompt input and routes it to registered command handlers."""

    aliases: dict[str, str] = field(default_factory=aliases_mod.load_aliases)
    echo: Callable[[str], None] = lambda text: None

    def __post_init__(self) -> None:
        self._commands: dict[str, _Entry] = {}
        self._pending: Optional[Prompt] = None
        self.last_command: str = ""

    # -- registration ---------------------------------------------------------
    def register(self, name: str, handler: Callable[..., Optional[Prompt]]) -> None:
        self._commands[name.upper()] = _Entry(handler)

    def register_future(self, name: str, phase: int) -> None:
        """A command in scope but not implemented yet: answer honestly."""
        self._commands[name.upper()] = _Entry(handler=None, phase=phase)

    def known_names(self) -> list[str]:
        """Commands + aliases, for prompt autocompletion."""
        names = set(self._commands)
        names.update(a for a, cmd in self.aliases.items() if cmd in self._commands)
        return sorted(names)

    # -- prompt state ---------------------------------------------------------
    @property
    def pending_prompt(self) -> Optional[str]:
        return self._pending.text if self._pending else None

    def cancel(self) -> None:
        """Esc: abandon any pending multi-step prompt."""
        if self._pending is not None:
            self._pending = None
            self.echo(tr("*Cancel*"))

    # -- input ----------------------------------------------------------------
    def submit(self, raw: str) -> None:
        """One line from the prompt (Enter or Space already stripped)."""
        text = raw.strip()

        if self._pending is not None:
            prompt = self._pending
            self._pending = None
            self._continue(prompt.on_input(text))
            return

        if not text:
            # AutoCAD: Enter on an empty prompt repeats the last command.
            if self.last_command:
                self._run(self.last_command, [])
            return

        tokens = text.split()
        name = aliases_mod.resolve(tokens[0], self.aliases)
        self._run(name, tokens[1:])

    def _run(self, name: str, args: list[str]) -> None:
        entry = self._commands.get(name)
        if entry is None:
            self.echo(tr('Unknown command "{name}".', name=name))
            return
        self.last_command = name
        if entry.handler is None:
            self.echo(tr("{name}: not available yet (arrives in Phase {phase}).",
                         name=name, phase=entry.phase))
            return
        self._continue(entry.handler(*args) if args else entry.handler())

    def _continue(self, result: Optional[Prompt]) -> None:
        if isinstance(result, Prompt):
            self._pending = result
            self.echo(result.text)
