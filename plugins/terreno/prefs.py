# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The Terrain plugin's defaults (Options > Terrain): the zone and
hemisphere GEOREF proposes, and the PSAD56 shift it proposes."""
from __future__ import annotations

from core.prefs import int_pref

from .datum import PSAD56_PERU_SHIFT

SETTING_ZONE = "terreno/zone"
SETTING_HEMISPHERE = "terreno/hemisphere"
SETTING_SHIFT = "terreno/psad56_shift"


def _setting(key: str, default: str) -> str:
    try:
        from PySide6.QtCore import QSettings

        return str(QSettings().value(key, default))
    except Exception:
        return default


def default_zone() -> int:
    """19 unless set: Arequipa, and most of Peru's coast and south."""
    return int_pref(SETTING_ZONE, 19, 1, 60)


def default_northern() -> bool:
    return _setting(SETTING_HEMISPHERE, "S").strip().upper().startswith("N")


def default_shift() -> tuple[float, float, float]:
    parts = _setting(SETTING_SHIFT, "").split(",")
    if len(parts) == 3:
        try:
            return tuple(float(p) for p in parts)          # type: ignore[return-value]
        except ValueError:
            pass
    return PSAD56_PERU_SHIFT


def save_defaults(zone: int, northern: bool, shift) -> None:
    try:
        from PySide6.QtCore import QSettings

        settings = QSettings()
        settings.setValue(SETTING_ZONE, int(zone))
        settings.setValue(SETTING_HEMISPHERE, "N" if northern else "S")
        settings.setValue(SETTING_SHIFT, ",".join(f"{float(v):g}" for v in shift))
    except Exception:
        pass
