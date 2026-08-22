# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Which words answer a prompt's ``[Option/Option]`` list, in any language.

AutoCAD's rule, which this follows: a localized AutoCAD takes the localized
keyword **and** the English one prefixed with an underscore (``_C``), so a
script written in Spain runs on an English install. IngeCAD gets the same
without a hand-written keyword table per language, because **the translation
already carries the mapping**::

    "Enter layout option [Copy/Delete/New/…]"
    "Indique opción de presentación [Copiar(C)/Suprimir(D)/Nueva(N)/…]"

``Suprimir(D)`` says "this option is typed D". So one resolver reads the
prompt it is about to display and accepts, for every language at once:

===============  ==========================================================
``D``            the English key -- always, whatever the interface language
``DELETE``       the English word -- always
``SUPRIMIR``     the translated word, accents optional
``_D``           the explicit global form, as AutoCAD writes it
===============  ==========================================================

Everything resolves back to the **English key**, so call sites keep comparing
against ``"D"`` and never learn that other languages exist.

Options are paired by position, since a translation keeps their order. A
loose any-to-any match reads ``Definir`` (which is Set) as the translation of
``Delete``, because both carry a capital D.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

_BRACKET = re.compile(r"\[([^\]]+)\]")
_HINT = re.compile(r"\(([A-Za-z]{1,3})\)")


def _fold(text: str) -> str:
    """Upper-case and strip accents: a user typing MULTIPLE means Múltiple."""
    stripped = unicodedata.normalize("NFD", text)
    return "".join(c for c in stripped if not unicodedata.combining(c)).upper()


def _capital_key(word: str) -> str:
    """The key AutoCAD spells with the word's capitals: CEnter -> CE.

    Digits count as part of the key, or ``2P`` would resolve to ``P`` and
    collide with ``3P`` in CIRCLE's very first prompt.
    """
    key = "".join(c for c in word if c.isascii() and (c.isupper() or c.isdigit()))
    return key or (word[:1].upper() if word else "")


def _split(bracket: str) -> list[str]:
    return [part.strip() for part in bracket.split("/") if part.strip()]


@dataclass(frozen=True)
class Option:
    """One entry of a prompt's ``[...]`` list, and everything that types it."""

    key: str                                   # "D" -- what call sites compare
    english: str                               # "Delete"
    localized: str                             # "Suprimir(D)", or "" if none
    accepts: frozenset[str] = field(default_factory=frozenset)

    def takes(self, folded: str) -> bool:
        return folded in self.accepts


def options(source: str, translation: str | None = None) -> list[Option]:
    """The options ``source`` offers, each with the words that answer it.

    ``translation`` defaults to the active language's rendering of ``source``.
    Passing it explicitly is for tests and for callers that already have it.
    """
    match = _BRACKET.search(source)
    if match is None:
        return []
    english_options = _split(match.group(1))

    if translation is None:
        from core.i18n import tr
        translation = tr(source)
    translated_match = _BRACKET.search(translation)
    translated = _split(translated_match.group(1)) if translated_match else []
    if len(translated) != len(english_options):
        translated = []                        # mismatched: English only

    out: list[Option] = []
    for index, english in enumerate(english_options):
        if english == "?" or "{" in english:
            continue                           # a literal ? and placeholders
        key = _capital_key(english)
        accepts = {_fold(key), _fold(english)}
        localized = translated[index] if index < len(translated) else ""
        if localized:
            hint = _HINT.search(localized)
            word = _HINT.sub("", localized).strip()
            accepts.add(_fold(word))
            if hint:
                accepts.add(_fold(hint.group(1)))
            else:
                accepts.add(_fold(_capital_key(word)))
        accepts.discard("")
        out.append(Option(key=key, english=english, localized=localized,
                          accepts=frozenset(accepts)))
    return out


def match(text: str, source: str, translation: str | None = None) -> str | None:
    """The English key ``text`` selects in ``source``, or None.

    A leading underscore forces the global form, so ``_D`` answers Delete even
    in a language whose own word for it starts with something else -- and even
    if that language's translation is missing or broken.
    """
    token = text.strip()
    if not token:
        return None
    global_form = token.startswith("_")
    if global_form:
        token = token.lstrip("_")
        if not token:
            return None
    folded = _fold(token)

    parsed = options(source, translation)
    for option in parsed:
        if global_form:
            if folded in (_fold(option.key), _fold(option.english)):
                return option.key
        elif option.takes(folded):
            return option.key
    return None


def collisions(source: str, translation: str | None = None) -> list[str]:
    """Words that would answer two options at once. Empty when the prompt is sane."""
    seen: dict[str, str] = {}
    clashing: list[str] = []
    for option in options(source, translation):
        for word in option.accepts:
            if word in seen and seen[word] != option.key:
                clashing.append(f"{word!r} answers both "
                                f"{seen[word]!r} and {option.key!r}")
            seen.setdefault(word, option.key)
    return clashing
