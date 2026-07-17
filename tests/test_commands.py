# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Phase 3 headless tests: alias table, prompt parser, AutoCAD semantics."""
from __future__ import annotations

from core.actions import Dispatcher, Prompt
from core.aliases import DEFAULT_ALIASES, load_aliases, parse_pgp, resolve
from core.commands import Command, History


# -- aliases -------------------------------------------------------------------

def test_stock_acad_aliases():
    for alias, command in (("L", "LINE"), ("M", "MOVE"), ("CO", "COPY"),
                           ("CP", "COPY"), ("Z", "ZOOM"), ("TR", "TRIM"),
                           ("LA", "LAYER"), ("AA", "AREA"), ("F", "FILLET")):
        assert resolve(alias, DEFAULT_ALIASES) == command
    # Full names and unknown tokens pass through, case-insensitive.
    assert resolve("line", DEFAULT_ALIASES) == "LINE"
    assert resolve("weird", DEFAULT_ALIASES) == "WEIRD"


def test_pgp_parsing_and_user_override(tmp_path):
    pgp = tmp_path / "acad.pgp"
    pgp.write_text(
        "; my custom aliases\n"
        "ZZ,      *ZOOM\n"
        "L,       *PLINE   ; overrides stock L\n"
        "NOTEPAD, START NOTEPAD\n"  # external command: ignored
    )
    aliases = load_aliases(pgp)
    assert aliases["ZZ"] == "ZOOM"
    assert aliases["L"] == "PLINE"       # user wins over stock
    assert aliases["M"] == "MOVE"        # stock still there
    assert "NOTEPAD" not in aliases
    assert parse_pgp("") == {}


# -- dispatcher ----------------------------------------------------------------

def make_dispatcher():
    echoes: list[str] = []
    d = Dispatcher(echo=echoes.append)
    calls: list[tuple] = []
    d.register("ZOOM", lambda *a: calls.append(("ZOOM", a)) or None)
    d.register("MOVE", lambda *a: calls.append(("MOVE", a)) or None)
    return d, calls, echoes


def test_alias_dispatch_and_case():
    d, calls, _ = make_dispatcher()
    d.submit("m")
    d.submit("MOVE")
    d.submit("  z  ")
    assert [c[0] for c in calls] == ["MOVE", "MOVE", "ZOOM"]


def test_empty_enter_repeats_last_command():
    d, calls, _ = make_dispatcher()
    d.submit("")          # nothing ran yet: no-op
    assert calls == []
    d.submit("m")
    d.submit("")          # repeats MOVE
    d.submit("")          # and again
    assert [c[0] for c in calls] == ["MOVE", "MOVE", "MOVE"]


def test_unknown_command_reports():
    d, _calls, echoes = make_dispatcher()
    d.submit("FOO")
    assert any("FOO" in e for e in echoes)


def test_future_command_reports_phase():
    d, _calls, echoes = make_dispatcher()
    d.aliases = dict(DEFAULT_ALIASES)
    d.register_future("TRIM", 5)
    d.submit("tr")
    assert any("5" in e for e in echoes)


def test_multi_step_prompt_and_cancel():
    picked: list[str] = []
    echoes: list[str] = []
    d = Dispatcher(echo=echoes.append)
    d.register("ZOOM", lambda *a: Prompt("option?", lambda t: picked.append(t)))

    d.submit("z")
    assert d.pending_prompt == "option?"
    d.submit("e")                    # continuation consumes the input
    assert picked == ["e"]
    assert d.pending_prompt is None

    d.submit("z")
    d.cancel()                       # Esc
    assert d.pending_prompt is None
    d.submit("m")                    # unknown here: MOVE not registered
    assert picked == ["e"]           # continuation did not eat it


def test_command_args_pass_through():
    d, calls, _ = make_dispatcher()
    d.submit("z e")
    assert calls == [("ZOOM", ("e",))]


# -- history -------------------------------------------------------------------

class _Toggle(Command):
    name = "toggle"

    def __init__(self):
        self.state = False

    def do(self, _doc):
        self.state = True

    def undo(self, _doc):
        self.state = False


def test_history_undo_redo():
    h = History()
    assert h.undo() is None and h.redo() is None
    cmd = _Toggle()
    h.execute(cmd)
    assert cmd.state and h.can_undo
    assert h.undo() is cmd and not cmd.state
    assert h.redo() is cmd and cmd.state
    h.execute(_Toggle())
    h.undo()
    h.execute(_Toggle())   # new branch clears redo
    assert not h.can_redo
