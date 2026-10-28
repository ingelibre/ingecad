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

import os
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
    * ``/run/user/N/doc/...`` (or ``/run/flatpak/doc/...``) — the document
      portal's per-file mount, which is how the chooser may hand a file
      over. It
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
    if _is_portal_path(resolved):
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


def _is_portal_path(path: Path) -> bool:
    """A document-portal mount: ``/run/user/N/doc/...`` or ``/run/flatpak/doc/...``."""
    parts = path.parts
    return (len(parts) > 4 and parts[:3] == ("/", "run", "user") and parts[4] == "doc") \
        or (len(parts) > 3 and parts[:4] == ("/", "run", "flatpak", "doc"))


def host_path(filename: str) -> str:
    """The real path behind a document-portal one, when the app can reach it.

    In the Flatpak the file chooser may hand back ``/run/flatpak/doc/<id>/x.dwg``:
    fine to read now, gone after a restart. Stored in a drawing (an xref's
    path) or a recent-files list, it points nowhere the next day (#66). The
    portal publishes the host path as an extended attribute; with
    ``--filesystem=home`` that path is readable from inside the sandbox too.
    Anything else is returned unchanged.
    """
    if not filename:
        return filename
    path = Path(filename)
    if not _is_portal_path(path):
        return filename
    try:
        raw = os.getxattr(path, "user.document-portal.host-path")
    except (OSError, AttributeError):   # old portal, or no xattr support
        return filename
    real = Path(os.fsdecode(raw.rstrip(b"\0")))
    return str(real) if real.is_file() else filename


def get_open_file(parent, caption: str, name_filter: str,
                  preferred: Path | str | None = None,
                  select_file: Path | str | None = None) -> str:
    """``QFileDialog.getOpenFileName`` that starts somewhere real.

    ``select_file`` opens on that file, already selected, when its folder is
    one the host can show -- AutoCAD's Select Linetype File on acad.lin.
    """
    where = start_dir(preferred if select_file is None else select_file)
    if select_file is not None and Path(select_file).is_file() \
            and Path(where) == Path(select_file).parent.resolve():
        where = str(Path(where) / Path(select_file).name)
    filename, _selected = QFileDialog.getOpenFileName(
        parent, caption, where, name_filter)
    filename = host_path(filename)
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
