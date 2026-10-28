# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""TRIMMODE: whether CHAMFER and FILLET trim the edges they join.

One setting for both commands, as in AutoCAD (TRIMMODE, saved in the
registry, initial value 1): changing Trim in FILLET changes it in CHAMFER.
"""
from __future__ import annotations

_KEY = "drafting/trimmode"
_value: bool | None = None


def trimmode() -> bool:
    global _value
    if _value is None:
        try:
            from PySide6.QtCore import QSettings

            _value = str(QSettings().value(_KEY, 1)) not in ("0", "false")
        except Exception:  # noqa: BLE001 -- no Qt settings: the default
            _value = True
    return _value


def set_trimmode(on: bool) -> None:
    global _value
    _value = bool(on)
    try:
        from PySide6.QtCore import QSettings

        QSettings().setValue(_KEY, 1 if _value else 0)
    except Exception:  # noqa: BLE001
        pass


# -- TRIMEXTENDMODE --------------------------------------------------------------
#
# AutoCAD 2021's mode for TRIM and EXTEND (saved in the registry): 1 Quick --
# no edges to pick, every object is one, and a pick with nothing to cut
# erases -- or 0 Standard, the classic flow (pick the edges, Enter for all).
# AutoCAD's new installs start in Quick; IngeCAD starts in Standard (Marco,
# 2026-10-10): the Enter a classic user presses for "all edges" would end a
# Quick TRIM. The mOde option switches, and the choice is remembered.

_TE_KEY = "drafting/trimextendmode"
_te_value: int | None = None


def trimextendmode() -> int:
    global _te_value
    if _te_value is None:
        try:
            from PySide6.QtCore import QSettings

            _te_value = 1 if str(QSettings().value(_TE_KEY, 0)) in ("1", "true") \
                else 0
        except Exception:  # noqa: BLE001 -- no Qt settings: the default
            _te_value = 0
    return _te_value


def set_trimextendmode(value: int) -> None:
    global _te_value
    _te_value = 1 if value else 0
    try:
        from PySide6.QtCore import QSettings

        QSettings().setValue(_TE_KEY, _te_value)
    except Exception:  # noqa: BLE001
        pass
