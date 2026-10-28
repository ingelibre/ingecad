# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A Spanish AutoCAD acad.pgp works in IngeCAD (#23).

Its lines point at Spanish command names (``DE, *DESPLAZA``) and it is
usually saved in ANSI (cp1252). The alias must run the command its target
names -- whatever the interface language -- and never a different command
that happens to start with the letters typed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import aliases as aliases_mod, i18n  # noqa: E402
from core.actions import Dispatcher  # noqa: E402

PGP = """; acad.pgp de AutoCAD en español -- configuración de alias
; Los comentarios llevan tildes y eñes, como los del fabricante.
DE,       *DESPLAZA
CO,       *COPIA
AÑ,       *LINEA
DD,       *NOEXISTE
"""


@pytest.fixture(params=["cp1252", "utf-8"])
def pgp(tmp_path, request):
    path = tmp_path / "acad.pgp"
    path.write_bytes(PGP.encode(request.param))
    return path


def _dispatcher(pgp_path):
    ran = []
    d = Dispatcher(aliases=aliases_mod.load_aliases(pgp_path))
    for name in ("MOVE", "COPY", "LINE", "DELAY", "DDEDIT", "XLINE", "XREF"):
        d.register(name, lambda *a, name=name: ran.append(name))
    return d, ran


@pytest.mark.parametrize("language", ["en", "es"])
def test_spanish_targets_run_their_command_whatever_the_language(pgp, language):
    i18n.set_language(language)
    try:
        d, ran = _dispatcher(pgp)
        for typed in ("DE", "CO", "AÑ", "añ"):
            d.submit(typed)
        assert ran == ["MOVE", "COPY", "LINE", "LINE"]
    finally:
        i18n.set_language("en")


def test_an_alias_to_an_unknown_command_is_reported_not_completed(pgp):
    d, ran = _dispatcher(pgp)
    echoes = []
    d.echo = echoes.append
    d.submit("DD")                       # would complete to DDEDIT
    assert ran == []
    assert any("NOEXISTE" in e for e in echoes)


def test_english_aliases_still_win(pgp):
    d, ran = _dispatcher(pgp)
    d.submit("M")
    d.submit("L")
    assert ran == ["MOVE", "LINE"]


def test_the_starter_file_holds_the_stock_aliases():
    assert aliases_mod.parse_pgp(aliases_mod.starter_pgp()) == \
        aliases_mod.DEFAULT_ALIASES


def test_edit_program_parameters_creates_the_file_and_reinit_reads_it(
        qapp, tmp_path, monkeypatch):
    from PySide6.QtGui import QDesktopServices
    from views.main_window import MainWindow

    pgp_path = tmp_path / "IngeCAD" / "acad.pgp"
    monkeypatch.setattr(aliases_mod, "user_pgp_path", lambda: pgp_path)
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl",
                        staticmethod(lambda url: opened.append(url) or True))
    win = MainWindow()
    win.new_document()
    try:
        bar_actions = win._menu_bar.actions()
        tools = next(a for a in bar_actions
                     if a.text().replace("&", "") == "Tools").menu()
        tools_actions = tools.actions()
        customize = next(a for a in tools_actions
                         if a.text().replace("&", "") == "Customize").menu()
        customize_actions = customize.actions()
        customize_actions[0].trigger()
        assert pgp_path.is_file()
        assert opened and Path(opened[0].toLocalFile()) == pgp_path
        # the user adds a Spanish line, saves, and types REINIT
        pgp_path.write_bytes(pgp_path.read_bytes()
                             + "DE, *DESPLAZA\n".encode("cp1252"))
        assert win.dispatcher.resolve_name("DE") != "MOVE"
        # REINIT shows the Re-initialization dialog; the user ticks
        # PGP File and presses OK
        import views.reinit_dialog as reinit_mod
        from PySide6.QtCore import QTimer

        class Ticking(reinit_mod.ReinitDialog):
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                self.pgp.setChecked(True)
                QTimer.singleShot(0, self.accept)

        monkeypatch.setattr(reinit_mod, "ReinitDialog", Ticking)
        win.dispatcher.submit("REINIT")
        assert win.dispatcher.resolve_name("DE") == "MOVE"
    finally:
        win.document.dirty = False
        win.close()


def test_reinit_without_pgp_file_ticked_changes_nothing(qapp, tmp_path,
                                                         monkeypatch):
    from PySide6.QtCore import QTimer

    import views.reinit_dialog as reinit_mod
    from views.main_window import MainWindow

    pgp_path = tmp_path / "acad.pgp"
    pgp_path.write_text("DE, *DESPLAZA\n", encoding="utf-8")
    monkeypatch.setattr(aliases_mod, "user_pgp_path", lambda: pgp_path)

    class Accepting(reinit_mod.ReinitDialog):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            assert not self.pgp.isChecked()        # AutoCAD: unticked
            QTimer.singleShot(0, self.accept)

    monkeypatch.setattr(reinit_mod, "ReinitDialog", Accepting)
    win = MainWindow()
    win.new_document()
    try:
        win.dispatcher.aliases = {}
        win.dispatcher.submit("REINIT")
        assert win.dispatcher.aliases == {}
    finally:
        win.document.dirty = False
        win.close()


def test_a_spanish_user_gets_pol_for_polyline_through_acad_pgp(tmp_path):
    """POL is PLINE in a Spanish AutoCAD but POLYGON in the English
    acad.pgp, and English wins -- so the Spanish name is not in the pack.
    One line in the user's acad.pgp gives it back."""
    path = tmp_path / "acad.pgp"
    path.write_text("POL, *PLINE\n", encoding="utf-8")
    d = Dispatcher(aliases=aliases_mod.load_aliases(path))
    ran = []
    for name in ("PLINE", "POLYGON"):
        d.register(name, lambda *a, name=name: ran.append(name))
    d.submit("POL")
    assert ran == ["PLINE"]
    assert Dispatcher(aliases=aliases_mod.load_aliases(tmp_path / "none")) \
        .aliases["POL"] == "POLYGON"                  # the stock alias
