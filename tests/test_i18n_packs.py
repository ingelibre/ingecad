# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A language is a folder: dropping one in must need no Python change.

The Language menu used to carry a hard-coded ``(("en", "English"), ("es",
"Español"))``, so the first outside translation had to patch
``views/main_window.py`` just to appear in it. These tests pin the property
that replaced it, including the promise that the **old flat layout still
loads** -- a translation written against ``i18n/<code>.json`` keeps working
and can be converted whenever its author gets to it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.i18n.packs import discover  # noqa: E402
from core import i18n  # noqa: E402


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_a_new_folder_is_a_new_language(tmp_path: Path) -> None:
    _write(tmp_path / "qu" / "meta.json",
           {"code": "qu", "name": "Runa Simi", "maintainer": "someone"})
    _write(tmp_path / "qu" / "ui.json", {"File": "Qillqa"})

    packs = discover(tmp_path)
    assert set(packs) == {"qu", "en"}          # English is always offered
    assert packs["qu"].name == "Runa Simi"     # the menu label, from meta.json
    assert packs["qu"].maintainer == "someone"
    assert packs["qu"].maintained is False     # community packs never enforced
    assert packs["qu"].load() == {"File": "Qillqa"}


def test_the_old_flat_file_still_loads(tmp_path: Path) -> None:
    """Michal's cs.json, and anything else written before the folder layout."""
    _write(tmp_path / "cs.json", {"File": "Soubor"})

    packs = discover(tmp_path)
    assert packs["cs"].legacy is True
    assert packs["cs"].load() == {"File": "Soubor"}
    assert packs["cs"].name == "cs"            # no meta.json to read a name from


def test_a_folder_wins_over_a_leftover_flat_file(tmp_path: Path) -> None:
    """During a conversion both may exist; the language must not appear twice."""
    _write(tmp_path / "cs.json", {"File": "old"})
    _write(tmp_path / "cs" / "meta.json", {"code": "cs", "name": "Čeština"})
    _write(tmp_path / "cs" / "ui.json", {"File": "Soubor"})

    packs = discover(tmp_path)
    assert packs["cs"].name == "Čeština"
    assert packs["cs"].load() == {"File": "Soubor"}
    assert packs["cs"].legacy is False


def test_a_broken_pack_degrades_to_english_instead_of_crashing(tmp_path: Path) -> None:
    (tmp_path / "xx").mkdir()
    (tmp_path / "xx" / "meta.json").write_text("{ not json", encoding="utf-8")
    _write(tmp_path / "yy" / "meta.json", {"code": "yy", "name": "Yy"})
    (tmp_path / "yy" / "ui.json").write_text("{ not json", encoding="utf-8")

    packs = discover(tmp_path)
    assert "xx" not in packs                   # unreadable metadata: not offered
    assert packs["yy"].load() == {}            # unreadable catalog: English


def test_an_empty_tree_still_offers_english(tmp_path: Path) -> None:
    assert set(discover(tmp_path)) == {"en"}
    assert discover(tmp_path / "nope")["en"].name == "English"


def test_the_shipped_languages_are_discovered() -> None:
    packs = i18n.language_packs()
    assert "en" in packs and "es" in packs
    assert packs["es"].name == "Español"       # what the menu shows
    assert packs["es"].maintained is True
    assert packs["en"].catalog is None         # source language, no catalog
    assert len(packs["es"].load()) > 1000


def test_switching_language_uses_the_pack() -> None:
    try:
        i18n.set_language("es")
        assert i18n.tr("File") == "Archivo"
        i18n.set_language("zz")                # unknown: English, no crash
        assert i18n.tr("File") == "File"
    finally:
        i18n.set_language("en")
