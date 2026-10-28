# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Where the application's data files live, running from the repo or frozen.

A PyInstaller build unpacks the bundled data under ``sys._MEIPASS`` and
synthesises ``__file__`` for modules inside the archive, so every path derived
from ``__file__`` alone points somewhere that does not exist in a bundle. Each
place that reads a shader, a translation, an icon or a converter goes through
``app_root()`` instead, so there is one answer to "where am I installed".
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def app_root() -> Path:
    """The directory holding ``resources/``, ``i18n/`` and ``vendor/``."""
    frozen = getattr(sys, "_MEIPASS", None)
    if frozen:
        return Path(frozen)
    return Path(__file__).resolve().parent.parent


def is_frozen() -> bool:
    """True in a PyInstaller bundle. For messages that differ when packaged."""
    return getattr(sys, "frozen", False) is True


def on_windows() -> bool:
    """One question for every platform branch of this module (and a seam
    the tests can set: faking os.name breaks pathlib)."""
    return os.name == "nt"


def user_config_dir() -> Path:
    """Where the user's own settings files live (recent drawings, acad.pgp,
    plot style tables, plugins). One answer for every module (#28):
    ``$XDG_CONFIG_HOME/IngeCAD`` (``~/.config/IngeCAD``) on Linux,
    ``%APPDATA%\\IngeCAD`` on Windows."""
    if on_windows():
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "IngeCAD"


def user_cache_dir() -> Path:
    """Where regenerable files go (thumbnails): ``$XDG_CACHE_HOME/IngeCAD``
    on Linux, ``%LOCALAPPDATA%\\IngeCAD\\cache`` on Windows."""
    if on_windows():
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "IngeCAD" / "cache"
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "IngeCAD"
