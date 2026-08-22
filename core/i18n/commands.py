# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Localized command names, the way AutoCAD does them.

A Spanish AutoCAD really does take ``LINEA`` and ``BORRA``. What makes that
survivable is the other half of Autodesk's design: **every command also
answers to its English name behind an underscore** (``_LINE``), which is why a
LISP routine written in Spain runs on an English install. English is the
lingua franca underneath the translated surface.

IngeCAD keeps that, and adds one rule of its own that AutoCAD does not need:

⚠️ **English never stops working, in any language, with or without the
underscore.** ``L``, ``LINE`` and ``_LINE`` all draw a line while the
interface is in Spanish. The whole product exists so that an AutoCAD user's
fingers keep working, so a language pack may *add* names, never shadow one.
:func:`problems` enforces that, and a pack that breaks it is rejected whole
rather than silently costing the user a command.

A pack declares them in ``i18n/<code>/commands.json``::

    {"LINE":  {"name": "LINEA"},
     "ERASE": {"name": "BORRA", "aliases": ["BO"]}}

Aliases are optional and rarely worth it: the English one-letter aliases are
the muscle memory the product is built on, so almost every short alias a
language would want is already taken. A colliding one is refused.
"""
from __future__ import annotations

from .packs import LanguagePack


def table(pack: LanguagePack) -> dict[str, str]:
    """``{typed token: English command}`` for one pack, upper-cased."""
    out: dict[str, str] = {}
    for english, spec in pack.load_commands().items():
        english = english.strip().upper()
        if not english:
            continue
        name = str(spec.get("name") or "").strip().upper()
        if name:
            out[name] = english
        for alias in spec.get("aliases") or ():
            alias = str(alias).strip().upper()
            if alias:
                out[alias] = english
    return out


def problems(pack: LanguagePack, commands: set[str],
             aliases: dict[str, str]) -> list[str]:
    """Everything wrong with a pack's command names, in plain words.

    ``commands`` are the registered English command names and ``aliases`` the
    English alias table. A pack must not name a command that does not exist
    (a typo that would simply never fire) and must not claim a token English
    already answers to (which would cost the user that command).
    """
    found: list[str] = []
    localized = table(pack)
    for english, spec in pack.load_commands().items():
        if english.strip().upper() not in commands:
            found.append(f"{pack.code}: {english!r} is not a command of this "
                         f"build, so {spec.get('name')!r} would never fire")
    for token, english in sorted(localized.items()):
        if token in commands:
            found.append(f"{pack.code}: {token!r} would shadow the English "
                         f"command {token!r}")
        elif token in aliases:
            found.append(f"{pack.code}: {token!r} would shadow the English "
                         f"alias {token!r} = {aliases[token]!r}")
    # Duplicates have to come off the raw entries: table() keeps one winner
    # per token, so by then the clash is already gone.
    seen: dict[str, str] = {}
    for english, spec in pack.load_commands().items():
        english = english.strip().upper()
        tokens = [str(spec.get("name") or "").strip().upper()]
        tokens += [str(a).strip().upper() for a in spec.get("aliases") or ()]
        for token in filter(None, tokens):
            if token in seen and seen[token] != english:
                found.append(f"{pack.code}: {token!r} names both "
                             f"{seen[token]!r} and {english!r}")
            seen.setdefault(token, english)
    return found
