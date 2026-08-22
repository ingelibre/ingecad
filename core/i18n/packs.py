# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Discovering the language packs shipped in ``i18n/``.

A language is a **folder**, not a patch: dropping ``i18n/<code>/`` into the
tree adds it to the Language menu with no Python change anywhere. That is the
whole point of this module -- the menu used to carry a hard-coded list, so the
first outside translation had to edit ``views/main_window.py`` to appear.

    i18n/
      en/  meta.json                       <- the source language, no catalog
      es/  meta.json  ui.json  commands.json
      cs/  meta.json  ui.json              <- commands.json is optional

``meta.json`` carries what the code used to hard-code::

    {"code": "es", "name": "Español", "maintainer": "…", "maintained": true}

``name`` is the language's own name, so the menu is readable whichever
language is currently active. ``maintained`` marks the languages this project
keeps complete (the coverage test enforces those and only reports the rest).

The **old flat layout** (``i18n/<code>.json``) still loads, so a translation
written against it keeps working and can be converted later. Such a pack has
no metadata to read, so it is listed by its code.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LanguagePack:
    """One installed language: where its catalog is and how to name it."""

    code: str
    name: str
    catalog: Path | None          # None for the source language
    maintained: bool = False
    maintainer: str = ""
    legacy: bool = False          # came from the flat i18n/<code>.json layout
    commands: Path | None = None  # optional localized command names

    def load(self) -> dict[str, str]:
        """The ``{english: translation}`` map, or empty if unreadable.

        A broken or missing file is not an error worth crashing over: an empty
        catalog makes :func:`~core.i18n.tr` return the English source, which is
        exactly the degraded behaviour the project promises for an incomplete
        translation.
        """
        if self.catalog is None:
            return {}
        try:
            data = json.loads(self.catalog.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {str(k): str(v) for k, v in data.items()}


    def load_commands(self) -> dict[str, dict]:
        """``{"LINE": {"name": "LINEA", "aliases": [...]}}``, or empty.

        Keys starting with ``_`` are notes for whoever edits the file, not
        commands, and are dropped here.
        """
        if self.commands is None:
            return {}
        try:
            data = json.loads(self.commands.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {str(k): v for k, v in data.items()
                if not str(k).startswith("_") and isinstance(v, dict)}


def _folder_pack(folder: Path) -> LanguagePack | None:
    meta_path = folder / "meta.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(meta, dict):
        return None
    code = str(meta.get("code") or folder.name)
    catalog = folder / "ui.json"
    commands = folder / "commands.json"
    return LanguagePack(
        code=code,
        name=str(meta.get("name") or code),
        catalog=catalog if catalog.is_file() else None,
        maintained=bool(meta.get("maintained")),
        maintainer=str(meta.get("maintainer") or ""),
        commands=commands if commands.is_file() else None,
    )


def discover(i18n_dir: Path) -> dict[str, LanguagePack]:
    """Every language installed under ``i18n_dir``, keyed by code.

    A folder wins over a flat file of the same code, so a converted language
    does not appear twice while the old file is still around.
    """
    packs: dict[str, LanguagePack] = {}
    if not i18n_dir.is_dir():
        return {"en": LanguagePack("en", "English", None)}

    for path in sorted(i18n_dir.glob("*.json")):       # legacy flat layout
        code = path.stem
        packs[code] = LanguagePack(
            code=code,
            name=code if code != "en" else "English",
            catalog=path if code != "en" else None,
            maintained=code == "en",
            legacy=True,
        )
    for folder in sorted(p for p in i18n_dir.iterdir() if p.is_dir()):
        pack = _folder_pack(folder)
        if pack is not None:
            packs[pack.code] = pack

    packs.setdefault("en", LanguagePack("en", "English", None, maintained=True))
    return packs
