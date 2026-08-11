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


# -- AutoComplete: a prefix runs the command it completes to --------------------

def _autocomplete_dispatcher():
    ran = []
    d = Dispatcher(echo=lambda text: ran.append(("echo", text)))
    for name in ("OFFSET", "OPEN", "LINE", "LAYER", "LAYOUT", "LIST",
                 "RECTANG", "REDO", "REGEN", "MOVE", "MATCHPROP", "MEASURE",
                 "MIRROR", "STRETCH", "SAVE", "SAVEAS"):
        d.register(name, lambda *a, n=name: ran.append(n))
    return d, ran


def test_a_prefix_runs_the_command_it_completes_to():
    """Typing OFF and Enter runs OFFSET, as AutoCAD's AutoComplete does."""
    d, ran = _autocomplete_dispatcher()
    for typed, expected in (("OFF", "OFFSET"), ("off", "OFFSET"),
                            ("REC", "RECTANG"), ("MEA", "MEASURE"),
                            ("STRE", "STRETCH"), ("LAYO", "LAYOUT")):
        ran.clear()
        d.submit(typed)
        assert ran and ran[0] == expected, f"{typed} ran {ran}"


def test_an_alias_always_beats_a_prefix():
    """L must stay LINE even though LAYER, LAYOUT and LIST all start with L.

    This is the one that would rot silently: add a command that sorts ahead
    of LINE and the muscle memory of every AutoCAD user breaks.
    """
    d, ran = _autocomplete_dispatcher()
    for typed, expected in (("L", "LINE"), ("M", "MOVE"), ("O", "OFFSET"),
                            ("MA", "MATCHPROP"), ("RE", "REGEN")):
        ran.clear()
        d.submit(typed)
        assert ran and ran[0] == expected, f"{typed} ran {ran}"


def test_an_ambiguous_prefix_takes_the_first_alphabetically():
    """The one AutoCAD appends — and the one the prompt showed inline."""
    d, ran = _autocomplete_dispatcher()
    d.submit("SAV")
    assert ran and ran[0] == "SAVE"        # SAVE before SAVEAS


def test_an_exact_command_name_still_wins_over_anything_shorter():
    d, ran = _autocomplete_dispatcher()
    d.submit("SAVEAS")
    assert ran and ran[0] == "SAVEAS"


def test_a_prefix_that_matches_nothing_is_still_unknown():
    d, ran = _autocomplete_dispatcher()
    d.submit("XYZZY")
    assert ran and ran[0][0] == "echo" and "Unknown" in ran[0][1]


def test_arguments_survive_the_completion():
    d, ran = _autocomplete_dispatcher()
    captured = []
    d.register("LTSCALE", lambda *args: captured.append(args))
    d.submit("LTS 25")
    assert captured == [("25",)]
    captured.clear()
    d.submit("LTSC 0.5")               # completed from a prefix
    assert captured == [("0.5",)]


def test_the_completion_does_not_hijack_a_pending_prompt():
    """Inside a command, "O" is that command's option, not OFFSET."""
    d, ran = _autocomplete_dispatcher()
    answers = []
    d.register("ARRAY", lambda *a: Prompt("type?", lambda t: answers.append(t)))
    d.submit("ARRAY")
    d.submit("O")
    assert answers == ["O"]
    assert "OFFSET" not in ran
