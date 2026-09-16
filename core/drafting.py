# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Drafting settings: polar tracking, and the grid and snap spacings.

What AutoCAD's Drafting Settings dialog (DSETTINGS, reference p. 664) rules
and where each value lives -- the same places AutoCAD keeps them, so a
colleague's drawing brings its own grid and ours travels with the file:

* **GRIDUNIT, SNAPUNIT, GRIDMAJOR** are saved in the drawing, in the
  ``*Active`` entry of the VPORT table (groups 15, 14 and 61). A file with
  none carries AutoCAD's metric or imperial default, by its unit.
* **POLARANG, POLARADDANG, POLARMODE** and the grid *behaviour* bits of
  GRIDDISPLAY (adaptive, subdivision) are per user (QSettings), as in the
  registry.

The grid itself is *nested*, as AutoCAD's adaptive grid is: every level is
the base spacing times a power of GRIDMAJOR, so zooming adds or removes
lines and never moves one -- major lines stay where they were and the
minor ones fill in between. The old 1-2-5 ladder re-flowed the whole
lattice at each step (1 to 2 drops the major at 15), which a tester saw as
"la rejilla salta de escala al acercarse".

Polar tracking locks the cursor onto an alignment path only when the
cursor is *near* it (within the tracking aperture), the way AutoCAD does;
elsewhere the cursor is free. Rounding every point to the nearest polar
angle -- what POLAR used to do here -- made a 30° line impossible with
POLAR on.
"""
from __future__ import annotations

import math
from typing import Optional

from core.commands import Command

# -- polar tracking ----------------------------------------------------------------

#: The increments the dialog's list offers (POLARANG), AutoCAD's.
POLAR_INCREMENTS = (90.0, 45.0, 30.0, 22.5, 18.0, 15.0, 10.0, 5.0)
DEFAULT_POLAR_INCREMENT = 90.0

#: POLARMODE bits.
POLAR_RELATIVE = 1        # measure angles from the last segment
POLAR_OTRACK_ALL = 2      # object snap tracking uses all polar angles
POLAR_ADDITIONAL = 4      # the additional angles are in use

SETTING_POLARANG = "polar/ang"
SETTING_POLARADDANG = "polar/addang"
SETTING_POLARMODE = "polar/mode"


def _settings():
    from PySide6.QtCore import QSettings

    return QSettings()


def polar_increment() -> float:
    """POLARANG: the polar increment angle in degrees."""
    try:
        value = float(_settings().value(SETTING_POLARANG, DEFAULT_POLAR_INCREMENT))
    except Exception:
        return DEFAULT_POLAR_INCREMENT
    return value if 0.0 < value <= 90.0 and math.isfinite(value) \
        else DEFAULT_POLAR_INCREMENT


def set_polar_increment(degrees: float) -> None:
    _settings().setValue(SETTING_POLARANG, float(degrees))


def parse_angles(text: str) -> list[float]:
    """POLARADDANG's list: angles in degrees separated by ``;`` or ``,``
    (AutoCAD writes ``;``), each normalised into [0, 360). Rubbish is
    dropped rather than refused; the dialog validates its own entries."""
    angles: list[float] = []
    for token in str(text).replace(",", ";").split(";"):
        token = token.strip()
        if not token:
            continue
        try:
            value = float(token) % 360.0
        except ValueError:
            continue
        if value not in angles:
            angles.append(value)
    return angles[:10]         # AutoCAD's "up to 10 additional angles"


def polar_additional() -> list[float]:
    """POLARADDANG: the additional (absolute) angles, degrees."""
    try:
        return parse_angles(str(_settings().value(SETTING_POLARADDANG, "")))
    except Exception:
        return []


def set_polar_additional(angles) -> None:
    _settings().setValue(SETTING_POLARADDANG,
                         ";".join(f"{a:g}" for a in parse_angles(
                             ";".join(str(a) for a in angles))))


def polar_mode() -> int:
    """POLARMODE bits (see POLAR_RELATIVE and friends)."""
    try:
        return int(_settings().value(SETTING_POLARMODE, 0)) & 7
    except Exception:
        return 0


def set_polar_mode(bits: int) -> None:
    _settings().setValue(SETTING_POLARMODE, int(bits) & 7)


def polar_angles(increment: float, additional=(), use_additional: bool = False
                 ) -> list[float]:
    """The alignment angles in degrees, [0, 180): a path is a full line
    through its point, so an angle and its opposite are the same path."""
    angles: list[float] = []
    if increment and increment > 0:
        n = int(round(180.0 / increment))
        if abs(n * increment - 180.0) < 1e-9 and n > 0:
            angles = [i * increment for i in range(n)]
        else:
            # an increment that does not divide 180 (say 22.5 does, 7 does
            # not): every multiple around the full circle, folded
            k = 0
            while k * increment < 360.0 - 1e-9:
                angles.append((k * increment) % 180.0)
                k += 1
    if use_additional:
        angles += [a % 180.0 for a in additional]
    out: list[float] = []
    for a in angles:
        if not any(abs(a - b) < 1e-9 for b in out):
            out.append(a)
    return sorted(out)


def polar_lock(anchor, cursor, angles_deg, tolerance: float,
               base_deg: float = 0.0) -> Optional[tuple]:
    """Where polar tracking puts the cursor, or None when it is free.

    The nearest alignment path through ``anchor`` (angles measured from
    ``base_deg``, which is 0 for absolute measurement and the last
    segment's direction for relative) catches the cursor when it lies
    within ``tolerance`` of it. Returns ``(point, angle_deg)`` with the
    angle of the locked direction in [0, 360), for the tooltip.
    """
    ax, ay = anchor
    dx, dy = cursor[0] - ax, cursor[1] - ay
    if dx * dx + dy * dy < 1e-18:
        return None
    best = None
    for a in angles_deg:
        rad = math.radians(a + base_deg)
        ux, uy = math.cos(rad), math.sin(rad)
        along = dx * ux + dy * uy
        px, py = ax + along * ux, ay + along * uy
        dist = math.hypot(cursor[0] - px, cursor[1] - py)
        if dist <= tolerance and (best is None or dist < best[0]):
            direction = (a + base_deg) % 360.0
            if along < 0:
                direction = (direction + 180.0) % 360.0
            best = (dist, (px, py), direction)
    if best is None:
        return None
    return best[1], best[2]


# -- grid and snap (in the drawing) ---------------------------------------------------

#: AutoCAD's initial GRIDUNIT/SNAPUNIT: 10 metric, 0.5 imperial -- by the
#: drawing's unit, since a metres plan with a 10-metre grid is not it.
_DEFAULT_UNIT_BY_INSUNITS = {
    1: 0.5, 2: 1.0, 4: 10.0, 5: 1.0, 6: 1.0, 7: 0.1, 14: 1.0, 0: 10.0,
}
DEFAULT_GRID_MAJOR = 5
SETTING_GRID_ADAPTIVE = "grid/adaptive"
SETTING_GRID_SUBDIVIDE = "grid/subdivide"

#: Pixels a grid cell must have on screen before the next level kicks in.
GRID_MIN_PX = 25.0
#: Below this the grid is not drawn at all when it may not adapt
#: (AutoCAD's "Grid too dense to display").
GRID_TOO_DENSE_PX = 4.0


def default_grid_unit(drawing) -> float:
    try:
        return _DEFAULT_UNIT_BY_INSUNITS.get(
            int(drawing.header.get("$INSUNITS", 0)), 10.0)
    except Exception:
        return 10.0


def active_vport(drawing):
    """The ``*Active`` VPORT entry, where AutoCAD keeps the grid and snap
    of the drawing, or None when the file has none."""
    try:
        entries = drawing.viewports.get("*Active")
    except Exception:
        return None
    if not entries:
        return None
    return entries[0] if isinstance(entries, (list, tuple)) else entries


def _vport_xy(drawing, attr: str) -> Optional[float]:
    vport = active_vport(drawing)
    if vport is None:
        return None
    try:
        value = vport.dxf.get(attr, None)
        if value is None:
            return None
        x = float(value[0])
    except Exception:
        return None
    return x if math.isfinite(x) and x > 0.0 else None


def grid_unit(drawing) -> float:
    """GRIDUNIT (x): the grid's base spacing in drawing units."""
    return _vport_xy(drawing, "grid_spacing") or default_grid_unit(drawing)


def snap_unit(drawing) -> float:
    """SNAPUNIT (x): the snap spacing, or 0 for "follow the grid on screen"
    -- IngeCAD's default, BricsCAD's adaptive snap; AutoCAD's own is a fixed
    spacing, which a drawing that carries one gets."""
    return _vport_xy(drawing, "snap_spacing") or 0.0


def grid_major(drawing) -> int:
    """GRIDMAJOR: minor lines per major line (2-100)."""
    vport = active_vport(drawing)
    if vport is None:
        return DEFAULT_GRID_MAJOR
    try:
        value = int(vport.dxf.get("major_grid_lines", DEFAULT_GRID_MAJOR))
    except Exception:
        return DEFAULT_GRID_MAJOR
    return value if 2 <= value <= 100 else DEFAULT_GRID_MAJOR


def grid_adaptive() -> bool:
    try:
        return str(_settings().value(SETTING_GRID_ADAPTIVE, True)).lower() \
            not in ("false", "0")
    except Exception:
        return True


def grid_subdivide() -> bool:
    try:
        return str(_settings().value(SETTING_GRID_SUBDIVIDE, True)).lower() \
            not in ("false", "0")
    except Exception:
        return True


def set_grid_behaviour(adaptive: bool, subdivide: bool) -> None:
    s = _settings()
    s.setValue(SETTING_GRID_ADAPTIVE, bool(adaptive))
    s.setValue(SETTING_GRID_SUBDIVIDE, bool(subdivide))


class SetGridCommand(Command):
    """GRIDUNIT / SNAPUNIT / GRIDMAJOR into the drawing's *Active VPORT --
    a mutation of the file like any other, so undoable. Nothing drawn
    changes (the grid is display), so no regen."""

    _ATTRS = {"grid": "grid_spacing", "snap": "snap_spacing",
              "major": "major_grid_lines"}

    def __init__(self, grid: Optional[float] = None,
                 snap: Optional[float] = None,
                 major: Optional[int] = None) -> None:
        self.name = "DSETTINGS"
        self.values = {"grid": grid, "snap": snap, "major": major}
        self._old = None

    @staticmethod
    def _dxf_value(key: str, value):
        if key == "major":
            return int(value)
        return (float(value), float(value))

    def _write(self, vport, key: str, raw) -> None:
        """Put a raw DXF value back (None = the attribute absent)."""
        attr = self._ATTRS[key]
        if raw is None:
            vport.dxf.discard(attr)
        else:
            vport.dxf.set(attr, raw)

    def do(self, document) -> None:
        drawing = document.doc
        vport = active_vport(drawing)
        if vport is None:
            vport = drawing.viewports.new("*Active")
        if self._old is None:
            self._old = {key: vport.dxf.get(attr, None)
                         for key, attr in self._ATTRS.items()}
        for key, value in self.values.items():
            if value is not None:
                self._write(vport, key, self._dxf_value(key, value))
        document.mark_dirty_no_revision()

    def undo(self, document) -> None:
        vport = active_vport(document.doc)
        if vport is None or self._old is None:
            return
        for key, value in self.values.items():
            if value is not None:
                self._write(vport, key, self._old[key])
        document.mark_dirty_no_revision()


def grid_level(unit: float, major: int, px_per_unit: float,
               adaptive: bool = True, subdivide: bool = True,
               current: Optional[int] = None) -> tuple[Optional[float], int]:
    """The grid spacing to draw at this zoom, and its level.

    Level 0 is GRIDUNIT; level k is ``unit * major**k`` (k < 0 subdivides).
    Zooming out climbs while a cell would be under GRID_MIN_PX (adaptive);
    zooming in descends while a cell would hold a whole finer level
    (subdivision). Every level's lines are a subset of the finer one's, so
    nothing on screen moves between levels.

    ``current`` is the level on screen: it is kept while its cell is
    within a band around the thresholds, so a wheel notch at the boundary
    does not flip the grid back and forth. Returns ``(None, level)`` when
    the grid is too dense to draw and may not adapt.
    """
    if not (unit > 0.0 and px_per_unit > 0.0 and math.isfinite(px_per_unit)):
        return None, 0
    major = max(2, int(major))

    def cell(level: int) -> float:
        return unit * (major ** level) * px_per_unit

    def allowed(level: int) -> bool:
        return (level >= 0 or subdivide) and (level <= 0 or adaptive)

    if current is not None and allowed(current):
        c = cell(current)
        low = GRID_MIN_PX * 0.8 if (adaptive or current > 0) else GRID_TOO_DENSE_PX
        high = GRID_MIN_PX * major * 1.25 if (subdivide or current < 0) else math.inf
        if low <= c <= high:
            return unit * (major ** current), current
    level = 0
    if adaptive:
        while cell(level) < GRID_MIN_PX and level < 40:
            level += 1
    elif cell(0) < GRID_TOO_DENSE_PX:
        return None, 0
    if subdivide:
        while cell(level - 1) >= GRID_MIN_PX and level > -40:
            level -= 1
    return unit * (major ** level), level
