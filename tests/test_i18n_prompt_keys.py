# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The rule every language file must obey: what you type stays English.

IngeCAD's command line is English in every language of the interface, because
the whole product thesis is that an AutoCAD user types what their fingers
already know. A prompt option is parsed against its English key, so a
translation that drops the key offers the user a word the parser then rejects
-- reported as https://github.com/ingelibre/ingecad/issues/4 after the Spanish
LAYOUT prompt promised "Suprimir" and only took "D".

A translated option is accepted here when it shows the key one of the three
ways AutoCAD itself uses:

    Suprimir(D)   the key spelled out in parentheses -- what es.json does
    CEntro        the capitals ARE the key, AutoCAD's own convention
    3P / Ttr      the keyword survives untranslated

Options are matched by position, since a translation keeps their order: a
loose "any option matches any" check silently accepted "Definir" (which is
Set) as the translation of "Delete".
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

I18N_DIR = Path(__file__).resolve().parent.parent / "i18n"


def _bracket(text: str) -> str | None:
    match = re.search(r"\[([^\]]+)\]", text)
    return match.group(1) if match else None


def _options(bracket: str) -> list[str]:
    return [part.strip() for part in bracket.split("/") if part.strip()]


def _key(option: str) -> str:
    """AutoCAD spells an option's key with the capitals of the word: CEnter -> CE."""
    capitals = "".join(c for c in option if c.isupper() and c.isascii())
    return capitals or option[0].upper()


def _covered(english: str, translated: str) -> bool:
    key = _key(english)
    if re.search(r"\(%s\)" % re.escape(key), translated, re.IGNORECASE):
        return True
    if _key(translated) == key:
        return True
    if translated.upper() == english.upper():
        return True
    # "Ttr (tan tan radius)" may be shortened, as long as it still starts with it
    return len(translated) >= 2 and english.upper().startswith(translated.upper())


def check(source: str, translation: str) -> list[str]:
    """Every way ``translation`` hides a key the parser of ``source`` wants."""
    english = _bracket(source)
    if english is None:
        return []
    options = _options(english)
    translated_bracket = _bracket(translation)
    if translated_bracket is None:
        return [f"{source!r}\n    -> the translation has no [...] at all"]
    translated = _options(translated_bracket)
    if len(translated) != len(options):
        return [f"{source!r}\n    -> {len(options)} options, the translation "
                f"has {len(translated)}: {translated}"]
    out = []
    for english_option, translated_option in zip(options, translated):
        if english_option == "?" or "{" in english_option:
            continue
        if not _covered(english_option, translated_option):
            out.append(
                f"{source!r}\n    -> {english_option!r} is typed "
                f"{_key(english_option)!r}, but the translation says "
                f"{translated_option!r} with no key in it")
    return out


def _catalogs() -> list[tuple[str, dict[str, str]]]:
    out = []
    for path in sorted(I18N_DIR.glob("*.json")):
        if path.stem == "en":       # identity map, nothing to check
            continue
        out.append((path.stem, json.loads(path.read_text(encoding="utf-8"))))
    return out


@pytest.mark.parametrize("lang,catalog", _catalogs(),
                         ids=lambda v: v if isinstance(v, str) else "")
def test_translated_prompts_keep_english_keys(lang: str, catalog: dict) -> None:
    failures: list[str] = []
    checked = 0
    for source, translation in catalog.items():
        if _bracket(source) is None:
            continue
        checked += 1
        failures.extend(check(source, translation))
    assert checked, f"{lang}: no prompt with options was checked -- is the glob right?"
    assert not failures, (
        f"{lang}.json: {len(failures)} prompt(s) hide the key the parser wants.\n"
        "Translate the word, keep the English key: [Suprimir(D)].\n\n"
        + "\n".join(failures))


LAYOUT = "Enter layout option [Copy/Delete/New/Template/Rename/SAveas/Set/?] <set>:"


def test_the_checker_catches_the_bug_that_was_reported() -> None:
    """Issue #4 exactly: the prompt offered "Suprimir" and only took "D"."""
    reported = ("Indique opción de presentación [Copiar/Suprimir/Nueva/Plantilla/"
                "Renombrar/Guardar/Definir/?] <definir>:")
    problems = check(LAYOUT, reported)
    assert len(problems) == 4        # Delete, Template, SAveas, Set
    assert "'Delete'" in problems[0]

    fixed = ("Indique opción de presentación [Copiar(C)/Suprimir(D)/Nueva(N)/"
             "Plantilla(T)/Renombrar(R)/Guardar(SA)/Definir(S)/?] <definir>:")
    assert check(LAYOUT, fixed) == []


def test_options_are_matched_by_position_not_by_luck() -> None:
    """A loose any-to-any check took "Definir" (Set) as the translation of Delete.

    Both words carry a capital D, so the pair only reads as wrong when the
    options are lined up in order -- which is how a translation keeps them.
    """
    assert _covered("Delete", "Definir")          # pairwise, D matches D
    shuffled = "Indique una opción [Suprimir(D)/Copiar(C)]:"
    assert check("Enter an option [Copy/Delete]:", shuffled)


def test_the_three_accepted_shapes() -> None:
    assert _covered("Delete", "Suprimir(D)")   # key spelled out
    assert _covered("CEnter", "CEntro")        # capitals carry the key
    assert _covered("3P", "3P")                # untranslated keyword
    assert not _covered("Delete", "Suprimir")  # the bug
