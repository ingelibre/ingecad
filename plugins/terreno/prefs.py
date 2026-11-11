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
SETTING_CRS = "terreno/crs"


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


def default_crs() -> str:
    """The coordinate system GEOREF proposes first (``EPSG:2154`` for a
    French office), or "" for the UTM questions."""
    return _setting(SETTING_CRS, "").strip()


def save_defaults(zone: int, northern: bool, shift, crs: str | None = None) -> None:
    try:
        from PySide6.QtCore import QSettings

        settings = QSettings()
        settings.setValue(SETTING_ZONE, int(zone))
        settings.setValue(SETTING_HEMISPHERE, "N" if northern else "S")
        settings.setValue(SETTING_SHIFT, ",".join(f"{float(v):g}" for v in shift))
        if crs is not None:
            settings.setValue(SETTING_CRS, crs.strip())
    except Exception:
        pass


# -- the DEM (G2) ---------------------------------------------------------------------------

SETTING_DEM_URL = "terreno/dem_url"
SETTING_DEM_ENCODING = "terreno/dem_encoding"
SETTING_DEM_ZOOM = "terreno/dem_zoom"
DEM_ZOOM_DEFAULT = 13          # ~18 m per pixel at Peru's latitudes: the 30 m data, not oversampled


def dem_source():
    """The tile source Options names, AWS Terrain Tiles unless changed."""
    from .dem import AWS_TERRAIN, ENCODINGS, DemSource

    url = _setting(SETTING_DEM_URL, "").strip()
    encoding = _setting(SETTING_DEM_ENCODING, "terrarium").strip().lower()
    if not url or url == AWS_TERRAIN.url_template:
        return AWS_TERRAIN
    if encoding not in ENCODINGS:
        encoding = "terrarium"
    return DemSource("custom", "custom DEM tiles", url, encoding, 15, "")


def dem_zoom() -> int:
    return int_pref(SETTING_DEM_ZOOM, DEM_ZOOM_DEFAULT, 8, 15)


def save_dem(url: str, encoding: str, zoom: int) -> None:
    try:
        from PySide6.QtCore import QSettings

        settings = QSettings()
        settings.setValue(SETTING_DEM_URL, url.strip())
        settings.setValue(SETTING_DEM_ENCODING, encoding)
        settings.setValue(SETTING_DEM_ZOOM, int(zoom))
    except Exception:
        pass


# -- imagery (G3) ---------------------------------------------------------------------------

SETTING_IMG_SOURCE = "terreno/imagery_source"
SETTING_IMG_URL = "terreno/imagery_url"
SETTING_IMG_MAXZOOM = "terreno/imagery_maxzoom"


def is_french(georef) -> bool:
    """Whether the drawing declares one of IGN's systems (Lambert-93, a CC
    zone, NTF Lambert, the overseas departments)."""
    from .datum import FRENCH_SYSTEMS

    return bool(georef is not None and getattr(georef, "crs", "")
                and georef.crs in set(FRENCH_SYSTEMS.values()))


def imagery_source(georef=None):
    """The tile source Options names: a preset, or the user's own XYZ.
    Unset, a drawing in a French system gets IGN's BD ORTHO HR."""
    from .tiles import DEFAULT_SOURCE_ID, FRANCE_SOURCE_ID, PRESETS, custom_source

    default = FRANCE_SOURCE_ID if is_french(georef) else DEFAULT_SOURCE_ID
    chosen = _setting(SETTING_IMG_SOURCE, "auto").strip()
    if chosen in ("", "auto"):
        chosen = default
    if chosen == "custom":
        url = _setting(SETTING_IMG_URL, "").strip()
        if url:
            return custom_source(url, int_pref(SETTING_IMG_MAXZOOM, 19, 1, 22))
    return PRESETS.get(chosen, PRESETS[DEFAULT_SOURCE_ID])


def save_imagery(source_id: str, url: str, max_zoom: int) -> None:
    try:
        from PySide6.QtCore import QSettings

        settings = QSettings()
        settings.setValue(SETTING_IMG_SOURCE, source_id)
        settings.setValue(SETTING_IMG_URL, url.strip())
        settings.setValue(SETTING_IMG_MAXZOOM, int(max_zoom))
    except Exception:
        pass
