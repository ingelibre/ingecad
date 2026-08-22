# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Localized prompt keywords, without a keyword table per language.

The rule the resolver implements is AutoCAD's: a localized install takes the
localized keyword *and* the English one behind an underscore, so a script
written in one language runs in another. Here the mapping is read out of the
translation itself -- ``Suprimir(D)`` says "this option is typed D" -- so a
new language brings its keywords along in its ``ui.json`` and no Python
changes. Reported as https://github.com/ingelibre/ingecad/issues/4.

The invariant that must never break: **English always works**, whatever the
interface language, because the command line is English by design.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import i18n  # noqa: E402
from core.i18n import keywords  # noqa: E402

LAYOUT = "Enter layout option [Copy/Delete/New/Template/Rename/SAveas/Set/?] <set>:"


@pytest.fixture
def spanish():
    i18n.set_language("es")
    yield
    i18n.set_language("en")


def test_english_answers_in_english() -> None:
    i18n.set_language("en")
    assert keywords.match("D", LAYOUT) == "D"
    assert keywords.match("delete", LAYOUT) == "D"
    assert keywords.match("SA", LAYOUT) == "SA"
    assert keywords.match("zzz", LAYOUT) is None


def test_the_localized_word_answers_too(spanish) -> None:
    """The reported bug: the prompt offered "Suprimir" and only took "D"."""
    assert keywords.match("Suprimir", LAYOUT) == "D"
    assert keywords.match("suprimir", LAYOUT) == "D"
    assert keywords.match("Guardar", LAYOUT) == "SA"


def test_english_still_answers_with_another_language_active(spanish) -> None:
    """The sacred invariant: muscle memory never stops working."""
    for typed in ("D", "DELETE", "d", "sa", "SAVEAS"):
        assert keywords.match(typed, LAYOUT) is not None, typed
    assert keywords.match("D", LAYOUT) == "D"


def test_the_underscore_forces_the_global_form(spanish) -> None:
    assert keywords.match("_D", LAYOUT) == "D"
    assert keywords.match("_DELETE", LAYOUT) == "D"
    # ...and it means English only, so it ignores the localized word
    assert keywords.match("_Suprimir", LAYOUT) is None


def test_accents_are_optional(spanish) -> None:
    source = "Specify point on side to offset or [Exit/Multiple/Undo] <Exit>:"
    assert keywords.match("Múltiple", source) == "M"
    assert keywords.match("MULTIPLE", source) == "M"


def test_capitals_carry_the_key_when_no_hint_is_given() -> None:
    """AutoCAD's own convention: CEnter is typed CE, and es.json writes CEntro."""
    source = "Specify endpoint of arc or [CEnter/Radius]:"
    i18n.set_language("es")
    try:
        assert keywords.match("CE", source) == "CE"
        assert keywords.match("CEntro", source) == "CE"
        assert keywords.match("Centro", source) == "CE"
    finally:
        i18n.set_language("en")


def test_options_are_paired_by_position() -> None:
    """Definir is Set, not Delete -- both merely carry a capital D."""
    translation = ("Indique opción [Copiar(C)/Suprimir(D)/Definir(S)]:")
    source = "Enter an option [Copy/Delete/Set]:"
    assert keywords.match("Definir", source, translation) == "S"
    assert keywords.match("Suprimir", source, translation) == "D"


def test_a_broken_translation_falls_back_to_english() -> None:
    """A pack whose bracket lost an option must not silently mis-map the rest."""
    source = "Enter an option [Copy/Delete/Set]:"
    assert keywords.match("D", source, "Indique opción [Copiar/Suprimir]:") == "D"
    assert keywords.match("Suprimir", source,
                          "Indique opción [Copiar/Suprimir]:") is None
    # ...and the global form works even with no usable translation at all
    assert keywords.match("_DELETE", source, "sin corchetes") == "D"


def test_a_prompt_without_options_matches_nothing() -> None:
    assert keywords.match("D", "Specify next point:") is None
    assert keywords.options("Specify next point:") == []


def _prompts_with_options(catalog: dict) -> list[str]:
    return [source for source in catalog if "[" in source and "]" in source]


@pytest.mark.parametrize(
    "lang", [p.code for p in i18n.language_packs().values() if p.catalog is not None])
def test_every_prompt_of_every_language_answers_english(lang: str) -> None:
    """Table-driven over the real catalogs: no language may shadow English."""
    pack = i18n.language_packs()[lang]
    catalog = pack.load()
    i18n.set_language(lang)
    try:
        broken = []
        for source in _prompts_with_options(catalog):
            for option in keywords.options(source):
                if keywords.match(option.key, source) != option.key:
                    broken.append(f"{source!r}: typing {option.key!r} no longer "
                                  f"selects {option.english!r}")
        assert not broken, "\n".join(broken)
    finally:
        i18n.set_language("en")


@pytest.mark.parametrize(
    "lang", [p.code for p in i18n.language_packs().values() if p.catalog is not None])
def test_no_language_makes_two_options_answer_to_one_word(lang: str) -> None:
    pack = i18n.language_packs()[lang]
    catalog = pack.load()
    i18n.set_language(lang)
    try:
        clashes = []
        for source in _prompts_with_options(catalog):
            for clash in keywords.collisions(source):
                clashes.append(f"{source!r}: {clash}")
        assert not clashes, "\n".join(clashes)
    finally:
        i18n.set_language("en")
