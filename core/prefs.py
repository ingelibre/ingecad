# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Reading a bounded integer preference: one helper, not one per setting.

CURSORSIZE, PICKBOX, VIEWRES and GRIPOBJLIMIT each read QSettings, coerce to
int, and fall back to their default when the stored value is missing,
malformed or out of range. Four copies of that rule had drifted in what
they caught; this is the one they share.
"""
from __future__ import annotations


def int_pref(key: str, default: int, low: int, high: int) -> int:
    """The stored integer under ``key`` when it lies in ``[low, high]``,
    else ``default`` -- also when QSettings itself is unavailable."""
    try:
        from PySide6.QtCore import QSettings

        value = int(QSettings().value(key, default))
    except Exception:
        return default
    return value if low <= value <= high else default
