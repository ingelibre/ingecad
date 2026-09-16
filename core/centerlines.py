# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""CENTERMARK / CENTERLINE: the norm's centre marks and centrelines.

DIMCENTER draws what DIMCEN says -- a plain cross, or the cross plus four
short continuous segments past the circle -- and that is all a pre-2017
AutoCAD had. The norm (ISO 128 / UNE 1-032) wants the axes of a circle as
thin **chain lines** (long dash, dot) extending a little past the outline,
and AutoCAD 2017 added CENTERMARK and CENTERLINE for exactly that, ruled by:

* ``CENTERLTYPE``     linetype of the mark, ``CENTER2`` by default;
* ``CENTEREXE``       how far the lines extend past the circle (3.5 mm
                      metric, 0.12 in imperial) -- kept here as millimetres
                      on the plotted sheet and converted through the
                      current dimension style (its text height times its
                      scale is 2.5 mm of sheet), so a metres plan at 1:100
                      gets 0.35 m and a millimetre detail at 1:1 gets 3.5;
* ``CENTERCROSSSIZE`` the central cross, ``0.1x`` = a tenth of the diameter;
* ``CENTERCROSSGAP``  the gap between the cross and the lines, ``0.05x``;
* ``CENTERMARKEXE``   whether the lines are drawn at all (on);
* ``CENTERLAYER``     the layer, ``.`` meaning the current one.

They are preferences here (QSettings, typed like PICKBOX) rather than
header variables, because DXF has none for them. What gets drawn is plain
LINE entities on the chosen linetype: AutoCAD's own CENTERMARK object is a
2017 entity that older CADs and LibreDWG carry only as a proxy, and a plan
has to open in the colleague's AutoCAD. The linetype is loaded from the
library when the drawing lacks it, inside the same undo step.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace

from core.commands import CompositeCommand

SETTING_EXE = "center/exe"
SETTING_LTYPE = "center/ltype"
SETTING_CROSSSIZE = "center/crosssize"
SETTING_CROSSGAP = "center/crossgap"
SETTING_LAYER = "center/layer"
SETTING_MARKEXE = "center/markexe"

DEFAULT_EXE = 3.5              # acadiso: 3.5 mm past the circle, on paper
PAPER_TEXT_MM = 2.5            # ISO text height the annotation scale is read from

#: Millimetres in one drawing unit, by $INSUNITS.
_MM_PER_UNIT = {
    0: 1.0, 1: 25.4, 2: 304.8, 3: 1609344.0, 4: 1.0, 5: 10.0, 6: 1000.0,
    7: 1e6, 8: 2.54e-5, 9: 0.0254, 10: 914.4, 11: 1e-7, 12: 1e-6, 13: 1e-3,
    14: 100.0, 15: 1e4, 16: 1e5,
}
DEFAULT_LTYPE = "CENTER2"
DEFAULT_CROSSSIZE = "0.1x"
DEFAULT_CROSSGAP = "0.05x"
DEFAULT_LAYER = "."            # the current layer
DEFAULT_MARKEXE = True

#: The current layer, as CENTERLAYER spells it.
CURRENT_LAYER = "."

Point = tuple[float, float]
Segment = tuple[Point, Point]


@dataclass(frozen=True)
class CenterSettings:
    exe: float = DEFAULT_EXE
    ltype: str = DEFAULT_LTYPE
    crosssize: str = DEFAULT_CROSSSIZE
    crossgap: str = DEFAULT_CROSSGAP
    layer: str = DEFAULT_LAYER
    markexe: bool = DEFAULT_MARKEXE


def parse_size(text: str, diameter: float, default: str) -> float:
    """A CENTERCROSSSIZE/GAP value: ``0.1x`` is a multiple of the diameter,
    a bare number is drawing units. Anything else reads as ``default``."""
    for candidate in (text, default):
        value = str(candidate).strip().lower().replace(",", ".")
        try:
            if value.endswith("x"):
                return float(value[:-1]) * diameter
            return float(value)
        except ValueError:
            continue
    return 0.0


def valid_size(text: str) -> bool:
    """Is ``text`` a value CENTERCROSSSIZE / CENTERCROSSGAP accept?"""
    value = str(text).strip().lower().replace(",", ".")
    try:
        float(value[:-1] if value.endswith("x") else value)
    except ValueError:
        return False
    return not value.startswith("-")


def settings() -> CenterSettings:
    """The CENTER* preferences, defaults for whatever is missing or bad."""
    try:
        from PySide6.QtCore import QSettings

        s = QSettings()
        exe = float(s.value(SETTING_EXE, DEFAULT_EXE))
        ltype = str(s.value(SETTING_LTYPE, DEFAULT_LTYPE)) or DEFAULT_LTYPE
        crosssize = str(s.value(SETTING_CROSSSIZE, DEFAULT_CROSSSIZE))
        crossgap = str(s.value(SETTING_CROSSGAP, DEFAULT_CROSSGAP))
        layer = str(s.value(SETTING_LAYER, DEFAULT_LAYER)) or DEFAULT_LAYER
        markexe = str(s.value(SETTING_MARKEXE, DEFAULT_MARKEXE)).lower() \
            not in ("false", "0")
    except Exception:
        return CenterSettings()
    if not (exe >= 0.0):
        exe = DEFAULT_EXE
    if not valid_size(crosssize):
        crosssize = DEFAULT_CROSSSIZE
    if not valid_size(crossgap):
        crossgap = DEFAULT_CROSSGAP
    return CenterSettings(exe, ltype, crosssize, crossgap, layer, markexe)


def annotation_scale(drawing) -> float:
    """Drawing units in one millimetre of plotted sheet.

    Read off the current dimension style: its text height times its overall
    scale is what 2.5 mm of ISO text measures in this drawing, whatever the
    drawing's unit -- and that holds for a colleague's metres plan that says
    $INSUNITS 0 with 0.20-unit text just as well as for a template of ours.
    Only a style with no text height falls back to $INSUNITS.
    """
    try:
        name = drawing.header.get("$DIMSTYLE", "Standard")
        style = drawing.dimstyles.get(name) if name in drawing.dimstyles else None
    except Exception:
        style = None
    height = float(style.dxf.get("dimtxt", 2.5)) if style is not None else 2.5
    scale = float(style.dxf.get("dimscale", 1.0)) if style is not None else 1.0
    if not scale > 0.0:            # 0 is AutoCAD's "work it out": 1 here
        scale = 1.0
    if height > 0.0:
        return height * scale / PAPER_TEXT_MM
    try:
        mm_per_unit = _MM_PER_UNIT.get(
            int(drawing.header.get("$INSUNITS", 4)), 1.0)
    except Exception:
        mm_per_unit = 1.0
    return scale / mm_per_unit


# -- geometry ------------------------------------------------------------------

def center_mark_segments(center: Point, radius: float,
                         prefs: CenterSettings | None = None) -> list[Segment]:
    """The lines of a centre mark on a circle: the central cross, and --
    with CENTERMARKEXE -- four segments from a gap past the cross out to
    CENTEREXE beyond the circle, along both axes. A circle too small for
    the gap gets the cross alone."""
    prefs = prefs or CenterSettings()
    cx, cy = center
    diameter = 2.0 * radius
    arm = parse_size(prefs.crosssize, diameter, DEFAULT_CROSSSIZE)
    gap = parse_size(prefs.crossgap, diameter, DEFAULT_CROSSGAP)
    segments: list[Segment] = [
        ((cx - arm, cy), (cx + arm, cy)),
        ((cx, cy - arm), (cx, cy + arm)),
    ]
    if not prefs.markexe:
        return segments
    inner = arm + gap
    outer = radius + prefs.exe
    if outer <= inner:
        return segments
    segments += [
        ((cx + inner, cy), (cx + outer, cy)),
        ((cx - inner, cy), (cx - outer, cy)),
        ((cx, cy + inner), (cx, cy + outer)),
        ((cx, cy - inner), (cx, cy - outer)),
    ]
    return segments


def centerline_between(a: Segment, b: Segment, exe: float) -> Segment | None:
    """The centreline of two lines: the locus midway between them, run over
    the span they share and extended ``exe`` past each end.

    The ends are paired nearest-to-nearest, so two parallel lines drawn in
    opposite directions still give the midline and not a diagonal; two
    non-parallel lines give the bisector through their midpoints. None
    when the lines are degenerate."""
    (a1, a2), (b1, b2) = a, b
    if math.dist(a1, a2) < 1e-9 or math.dist(b1, b2) < 1e-9:
        return None
    if math.dist(a1, b1) + math.dist(a2, b2) > math.dist(a1, b2) + math.dist(a2, b1):
        b1, b2 = b2, b1
    p1 = ((a1[0] + b1[0]) / 2.0, (a1[1] + b1[1]) / 2.0)
    p2 = ((a2[0] + b2[0]) / 2.0, (a2[1] + b2[1]) / 2.0)
    length = math.dist(p1, p2)
    if length < 1e-9:
        return None
    ux, uy = (p2[0] - p1[0]) / length, (p2[1] - p1[1]) / length
    return ((p1[0] - ux * exe, p1[1] - uy * exe),
            (p2[0] + ux * exe, p2[1] + uy * exe))


# -- commands --------------------------------------------------------------------

def _resolve_linetype(drawing, wanted: str):
    """(name to draw with, load command or None). A name the drawing lacks
    is loaded from the library; one the library lacks either falls back to
    CENTER2 or, failing that too, to the continuous line."""
    from core import linetypes as lt_ops

    have = {lt.dxf.name.upper(): lt.dxf.name for lt in drawing.linetypes}
    library = lt_ops.library()
    for name in (wanted, DEFAULT_LTYPE):
        key = name.upper()
        if key in have:
            return have[key], None
        if key in library:
            return key, lt_ops.LoadLinetypesCommand([key])
    return "Continuous", None


def _layer_commands(drawing, layer: str):
    """(layer name for the lines, [commands that create it])."""
    from core import layers as layer_ops

    if layer.strip() in ("", CURRENT_LAYER):
        return drawing.header.get("$CLAYER", "0"), []
    if layer in drawing.layers:
        return layer, []
    return layer, [layer_ops.NewLayerCommand(layer)]


def _lines_command(drawing, name: str, segments: list[Segment],
                   prefs: CenterSettings) -> CompositeCommand | None:
    """The undo step: the layer if it has to be made, the linetype if it
    has to be loaded, then the lines. ``drawing`` is the ezdxf document the
    entities belong to (what a tool has in hand); the commands themselves
    run against the Document wrapper like any other."""
    from core import actions

    if not segments:
        return None
    ltype, load = _resolve_linetype(drawing, prefs.ltype)
    layer, commands = _layer_commands(drawing, prefs.layer)
    if load is not None:
        commands.append(load)
    for p1, p2 in segments:
        commands.append(actions.AddEntityCommand(
            "LINE",
            lambda msp, a=p1, b=p2, lt=ltype: msp.add_line(
                a, b, dxfattribs={"linetype": lt}),
            layer=layer))
    return CompositeCommand(name, commands)


def _in_drawing_units(prefs: CenterSettings, drawing) -> CenterSettings:
    """The preferences with CENTEREXE converted from sheet millimetres."""
    return replace(prefs, exe=prefs.exe * annotation_scale(drawing))


def center_mark(entity, prefs: CenterSettings | None = None):
    """CENTERMARK on a circle or arc, as one undo step."""
    prefs = _in_drawing_units(prefs or settings(), entity.doc)
    c = entity.dxf.center
    segments = center_mark_segments((c.x, c.y), float(entity.dxf.radius),
                                    prefs)
    return _lines_command(entity.doc, "CENTERMARK", segments, prefs)


def centerline(line1, line2, prefs: CenterSettings | None = None):
    """CENTERLINE between two LINE entities, as one undo step (None when
    the two lines give no centreline)."""
    prefs = _in_drawing_units(prefs or settings(), line1.doc)

    def seg(line) -> Segment:
        s, e = line.dxf.start, line.dxf.end
        return ((s.x, s.y), (e.x, e.y))

    result = centerline_between(seg(line1), seg(line2), prefs.exe)
    if result is None:
        return None
    return _lines_command(line1.doc, "CENTERLINE", [result], prefs)
