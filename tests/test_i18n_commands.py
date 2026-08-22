# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Localized command names, and the invariant they may never break.

A Spanish AutoCAD takes LINEA and BORRA. IngeCAD does too now -- but the whole
product exists so that an AutoCAD user's fingers keep working, so a language
pack may only *add* names:

⚠️ **English never stops working, in any language.** ``L``, ``LINE`` and
``_LINE`` all draw a line with Spanish active. The underscore is AutoCAD's
global form, and it is what lets a script or a macro run whatever the
interface language.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import aliases as aliases_mod  # noqa: E402
from core import i18n  # noqa: E402
from core.actions import Dispatcher  # noqa: E402
from core.i18n import commands as localized  # noqa: E402
from core.i18n.packs import LanguagePack  # noqa: E402

#: Every command the real application registers, without building a window.
COMMANDS = sorted({cmd for cmd in aliases_mod.DEFAULT_ALIASES.values()}
                  | set(aliases_mod.DEFAULT_ALIASES))


@pytest.fixture
def dispatcher():
    """A dispatcher registered with every command a language pack may name."""
    disp = Dispatcher()
    names = set(aliases_mod.DEFAULT_ALIASES.values())
    for pack in i18n.language_packs().values():
        names.update(k.upper() for k in pack.load_commands())
    for name in names:
        disp.register(name, lambda: None)
    yield disp
    i18n.set_language("en")


@pytest.fixture
def spanish():
    i18n.set_language("es")
    yield
    i18n.set_language("en")


def test_every_english_alias_survives_every_language(dispatcher) -> None:
    """The sacred invariant, walked over the whole acad.pgp table."""
    for lang in i18n.available_languages():
        i18n.set_language(lang)
        for alias, command in aliases_mod.DEFAULT_ALIASES.items():
            resolved = dispatcher.resolve_name(alias)
            assert resolved == command, (
                f"with {lang!r} active, {alias!r} resolves to {resolved!r} "
                f"instead of {command!r}")
            assert dispatcher.resolve_name(f"_{alias}") == command
            assert dispatcher.resolve_name(command) == command
            assert dispatcher.resolve_name(f"_{command}") == command


def test_the_localized_name_runs_the_command(dispatcher, spanish) -> None:
    assert dispatcher.resolve_name("LINEA") == "LINE"
    assert dispatcher.resolve_name("linea") == "LINE"
    assert dispatcher.resolve_name("BORRA") == "ERASE"
    assert dispatcher.resolve_name("ACOLINEAL") == "DIMLINEAR"


def test_localized_names_are_inert_in_another_language(dispatcher) -> None:
    """LINEA is a Spanish name, not a second English one."""
    i18n.set_language("en")
    assert dispatcher.resolve_name("LINEA") != "LINE"


def test_the_underscore_means_english_only(dispatcher, spanish) -> None:
    assert dispatcher.resolve_name("_LINE") == "LINE"
    assert dispatcher.resolve_name("_LINEA") != "LINE"   # not an English name


def test_autocompletion_offers_both(dispatcher, spanish) -> None:
    names = dispatcher.known_names()
    assert "LINE" in names and "L" in names and "LINEA" in names


def test_prefix_completion_prefers_english(dispatcher, spanish) -> None:
    """LIN completes to LINE, not to LINEA -- English is tried first."""
    assert dispatcher.resolve_name("LIN") == "LINE"


def _pack(tmp_path: Path, data: dict) -> LanguagePack:
    import json
    path = tmp_path / "commands.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return LanguagePack("xx", "Xx", None, commands=path)


def test_a_pack_that_shadows_an_english_alias_is_reported(tmp_path) -> None:
    pack = _pack(tmp_path, {"ERASE": {"name": "BORRA", "aliases": ["B"]}})
    found = localized.problems(pack, {"ERASE", "BLOCK"}, {"B": "BLOCK"})
    assert any("shadow the English alias" in p for p in found), found


def test_a_pack_that_shadows_an_english_command_is_reported(tmp_path) -> None:
    pack = _pack(tmp_path, {"ERASE": {"name": "BLOCK"}})
    found = localized.problems(pack, {"ERASE", "BLOCK"}, {})
    assert any("shadow the English command" in p for p in found), found


def test_a_pack_naming_a_command_that_does_not_exist_is_reported(tmp_path) -> None:
    """A typo would otherwise be a name that simply never fires."""
    pack = _pack(tmp_path, {"ERAES": {"name": "BORRA"}})
    found = localized.problems(pack, {"ERASE"}, {})
    assert any("not a command of this build" in p for p in found), found


def test_a_pack_naming_two_commands_the_same_is_reported(tmp_path) -> None:
    pack = _pack(tmp_path, {"ERASE": {"name": "X"}, "MOVE": {"name": "X"}})
    found = localized.problems(pack, {"ERASE", "MOVE"}, {})
    assert any("names both" in p for p in found), found


def test_notes_in_the_file_are_not_commands(tmp_path) -> None:
    pack = _pack(tmp_path, {"_comment": {"name": "ignored"},
                            "ERASE": {"name": "BORRA"}})
    assert localized.table(pack) == {"BORRA": "ERASE"}


@pytest.fixture
def real_window(qapp):
    """One real window for the checks that need the actual command registry.

    One, not two: every MainWindow left alive costs Qt teardown work, and a
    full-suite run once ended in a shutdown-time fatal dump after this file
    built a second one. It did not reproduce in three further runs, so this is
    prudence, not a diagnosis.
    """
    from views.main_window import MainWindow

    window = MainWindow()
    yield window
    i18n.set_language("en")
    window.close()


def test_the_shipped_packs_are_valid_against_the_real_registry(real_window) -> None:
    """Checked against the commands the application actually registers.

    DEFAULT_ALIASES covers only the aliased ones; a pack may name any of the
    105 the window registers, and a name for one that does not exist would
    simply never fire.
    """
    registry = set(real_window.dispatcher._commands)
    found: list[str] = []
    for pack in i18n.language_packs().values():
        found += localized.problems(pack, registry, real_window.dispatcher.aliases)
    assert not found, "\n".join(found)


def test_every_shipped_localized_name_reaches_its_command(real_window) -> None:
    """Not just valid: actually resolvable through the real dispatcher."""
    for code, pack in i18n.language_packs().items():
        table = localized.table(pack)
        if not table:
            continue
        i18n.set_language(code)
        for token, english in table.items():
            assert real_window.dispatcher.resolve_name(token) == english, (
                f"[{code}] {token!r} does not reach {english!r}")
