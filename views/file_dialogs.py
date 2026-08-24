# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Where a file dialog opens, and what it remembers between drawings.

Every dialog used to be handed ``""`` as its starting directory, and Qt
resolves that against the process's working directory. That was harmless
from a terminal and fatal in the Flatpak: the launcher works in
``/app/ingecad``, but the file chooser runs *outside* the sandbox through
the desktop portal, where no such path exists — so choosing File ▸ Open put
up "No se pudo encontrar «/app/ingecad»" instead of a file chooser.

So the rule is: a dialog is never given an empty or relative location. It is
given a directory that exists on the user's own filesystem, chosen the way
AutoCAD chooses it — the folder you were last in, then the folder of the
drawing you have open, then Documents, then home.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths
from PySide6.QtWidgets import QFileDialog

SETTING_LAST_DIR = "paths/last_dir"


def _usable(candidate: Path | str | None) -> Path | None:
    """A directory the *host* can show, or None.

    Two kinds of path are rejected by name, because both look perfectly
    real from inside the process:

    * ``/app`` — the sandbox's own read-only prefix. ``is_dir()`` says yes,
      and it means nothing to the portal that draws the dialog outside the
      sandbox. That is exactly how the original bug slipped through.
    * ``/run/user/N/doc/...`` — the document portal's per-file mount, which
      is how a file chosen outside ``--filesystem=home`` is handed over. It
      is a fine path to *open*, and a useless folder to reopen in: it holds
      that one file and disappears.
    """
    if not candidate:
        return None
    try:
        path = Path(candidate).expanduser()
        if not path.is_dir():
            path = path.parent
        if not path.is_dir():
            return None
        resolved = path.resolve()
    except (OSError, ValueError):
        return None
    if resolved == Path("/app") or Path("/app") in resolved.parents:
        return None
    parts = resolved.parts
    if parts[:2] == ("/", "run") and len(parts) > 4 and parts[2] == "user" \
            and parts[4] == "doc":
        return None
    return resolved


def _documents() -> Path | None:
    where = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
    return _usable(where)


def _last_drawing() -> Path | None:
    """The folder of the most recent drawing, if it is still there."""
    try:
        from core import recent
        for entry in recent.load():
            found = _usable(Path(entry).parent)
            if found:
                return found
    except Exception:      # a missing or unreadable list must never block Open
        pass
    return None


def start_dir(preferred: Path | str | None = None) -> str:
    """The directory a dialog should open in. Never empty, never relative."""
    for candidate in (
        preferred,
        QSettings().value(SETTING_LAST_DIR, None),
        _last_drawing(),
        _documents(),
        Path.home(),
    ):
        found = _usable(candidate)
        if found:
            return str(found)
    return str(Path.home())    # home exists even when it is not readable


def remember(path: Path | str | None) -> None:
    """Record the folder of ``path`` as where the next dialog opens."""
    found = _usable(path)
    if found:
        QSettings().setValue(SETTING_LAST_DIR, str(found))


def get_open_file(parent, caption: str, name_filter: str,
                  preferred: Path | str | None = None) -> str:
    """``QFileDialog.getOpenFileName`` that starts somewhere real."""
    filename, _selected = QFileDialog.getOpenFileName(
        parent, caption, start_dir(preferred), name_filter)
    remember(filename)
    return filename


def get_save_file(parent, caption: str, suggested_name: str,
                  name_filter: str,
                  preferred: Path | str | None = None) -> tuple[str, str]:
    """``QFileDialog.getSaveFileName`` with the suggestion placed in a folder.

    A bare "plano.pdf" is a relative path, and relative means the working
    directory again — the same trap as an empty one.
    """
    where = Path(start_dir(preferred))
    suggestion = Path(suggested_name)
    target = suggestion if suggestion.is_absolute() else where / suggestion.name
    filename, selected = QFileDialog.getSaveFileName(
        parent, caption, str(target), name_filter)
    remember(filename)
    return filename, selected
