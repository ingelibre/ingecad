# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Lightweight JSON-based UI translation (ported from IngeTrazo).

English is the *source* language: the keys passed to :func:`tr` are the English
strings themselves, so any untranslated string falls back to readable English
instead of a cryptic key. A language ships as a folder under ``i18n/`` -- see
:mod:`core.i18n.packs` for the layout and for the flat files it still reads.

⚠️ **What you read is translatable; what you type is English.** The command
line stays English in every language, so the option keys inside a prompt are
never translated away: ``[Suprimir(D)]`` keeps the ``D`` the parser wants.
``tests/test_i18n_prompt_keys.py`` enforces that on every language file.

This deliberately avoids Qt's ``.ts``/``.qm`` + Linguist toolchain to stay
dependency-free, matching the project's minimal stack.

Usage::

    from core.i18n import tr
    label = tr("File")                         # -> "Archivo" in Spanish
    msg = tr("Opened {name}", name="plan.dxf")  # interpolates after lookup
"""
from __future__ import annotations

from pathlib import Path

from core.paths import app_root

from . import commands as _commands
from .packs import LanguagePack, discover

__all__ = ["tr", "set_language", "current_language", "available_languages",
           "language_packs", "language_name", "command_names", "LanguagePack",
           "i18n_dir"]

_catalog: dict[str, str] = {}
_command_names: dict[str, str] = {}
_lang = "en"


def i18n_dir() -> Path:
    """Where the language packs live (resolved late, for frozen bundles)."""
    return app_root() / "i18n"


def language_packs() -> dict[str, LanguagePack]:
    """Every installed language, keyed by code. Read from disk each call.

    Cheap (a directory listing and a few small files) and always current, so
    a language dropped in while the app runs shows up on the next menu build.
    """
    return discover(i18n_dir())


def available_languages() -> list[str]:
    """Installed language codes, sorted (e.g. ``["en", "es"]``)."""
    return sorted(language_packs())


def language_name(code: str) -> str:
    """The language's own name, for a menu that reads in any active language."""
    pack = language_packs().get(code)
    return pack.name if pack else code


def set_language(lang: str) -> None:
    """Activate ``lang`` for subsequent :func:`tr` calls.

    English, an unknown code or a broken file all load an empty catalog, so
    ``tr`` returns the source string unchanged.
    """
    global _catalog, _command_names, _lang
    _lang = lang or "en"
    pack = language_packs().get(_lang)
    _catalog = pack.load() if pack is not None else {}
    _command_names = _commands.table(pack) if pack is not None else {}


def current_language() -> str:
    return _lang


def command_names() -> dict[str, str]:
    """``{typed token: English command}`` for the active language.

    Empty for English, and empty for any language that ships no
    ``commands.json`` -- which is most of them, and perfectly fine.
    """
    return _command_names


def tr(text: str, /, **kwargs) -> str:
    """Translate ``text`` into the active language; interpolate ``kwargs``.

    ``.format`` runs only when keyword arguments are given, so source strings
    that contain literal braces are safe when called without kwargs.
    """
    out = _catalog.get(text, text)
    if kwargs:
        try:
            out = out.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            out = text.format(**kwargs)
    return out
