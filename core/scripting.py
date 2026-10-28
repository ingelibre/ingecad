# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""APPLOAD and SCRIPT: run a Python file over ``actions``, or an AutoCAD
``.scr`` command script (docs/plugins.md, "Scripts").

Python is this project's LISP (CLAUDE.md: scripting = Python over
``actions``). A file loaded with APPLOAD runs once, right away, with the
document and the actions in scope; every Command it executes through the
history is folded into ONE undo step named after the file, so a script that
drew two hundred points goes away with a single U.

A ``.scr`` is what an AutoCAD user already has: one command-line entry per
line, blank line = Enter, ``DELAY ms`` waits, ``RSCRIPT`` repeats from the
top, ``RESUME`` is a no-op here and ``;`` starts a comment. The runner is
headless: the window feeds :meth:`ScriptRunner.step` from a timer so the
screen updates between lines.
"""
from __future__ import annotations

import traceback
from pathlib import Path
from typing import Callable, Optional

from core.commands import CompositeCommand


def script_namespace(host) -> dict:
    """What a loaded Python file sees: the headless API, nothing of Qt."""
    import ezdxf

    from core import actions

    document = getattr(host, "document", None)

    def execute(command) -> None:
        host.tools._execute(command)

    def command(text: str) -> None:
        host._on_command_submitted(text)

    def echo(text: str) -> None:
        host.command_line.echo(str(text))

    return {
        "__name__": "__ingecad_script__",
        "actions": actions,
        "ezdxf": ezdxf,
        "document": document,
        "doc": document.doc if document is not None else None,
        "msp": document.doc.modelspace() if document is not None else None,
        "execute": execute,
        "command": command,
        "echo": echo,
        "host": host,
    }


def run_python(path: Path | str, host) -> tuple[int, Optional[str]]:
    """Run ``path`` with :func:`script_namespace`.

    Returns ``(commands folded, error)``: the number of history entries the
    script produced (now one composite step), and the last line of the
    traceback if it raised -- what ran before the error stays, undoable,
    like AutoCAD keeps what a failing script did.
    """
    path = Path(path)
    history = host.history
    before = len(history._undo)
    error = None
    source = path.read_text(encoding="utf-8")
    code = compile(source, str(path), "exec")
    try:
        exec(code, script_namespace(host))          # noqa: S102 - the user's own file
    except Exception:                                # noqa: BLE001 - reported, not raised
        error = traceback.format_exc().strip().splitlines()[-1]
    added = history._undo[before:]
    if len(added) > 1:
        del history._undo[before:]
        composite = CompositeCommand(path.name, added)
        composite._space = None                      # already done; do() is never re-run here
        history.record(composite)
    return len(added), error


class ScriptRunner:
    """One ``.scr`` file, fed to the command line a line at a time."""

    def __init__(self, lines, submit: Callable[[str], None]) -> None:
        self._lines = [line.rstrip("\r\n") for line in lines]
        self._submit = submit
        self._index = 0
        self.repeats = 0

    @classmethod
    def from_file(cls, path: Path | str, submit) -> "ScriptRunner":
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        return cls(text.splitlines(), submit)

    @property
    def done(self) -> bool:
        return self._index >= len(self._lines)

    def step(self) -> Optional[int]:
        """Feed the next line. Returns the milliseconds to wait before the
        next step, or None when the script has ended."""
        while self._index < len(self._lines):
            raw = self._lines[self._index]
            self._index += 1
            if raw.lstrip().startswith(";"):
                continue                      # a comment line is not an Enter
            line = raw
            upper = line.strip().upper()
            if upper.startswith("DELAY"):
                rest = upper[5:].strip()
                try:
                    return max(0, int(rest))
                except ValueError:
                    return 0
            if upper == "RSCRIPT":
                self._index = 0
                self.repeats += 1
                if self.repeats > 1000:       # a runaway loop: stop
                    return None
                return 0
            if upper == "RESUME":
                continue
            self._submit(line)                # a blank line is Enter
            return 0
        return None
