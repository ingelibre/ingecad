# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Topography, headless: every operation is an undoable Command over the
ezdxf document, and every object it makes is a plain DXF entity.

A survey point is a POINT at (E, N, Z) on ``TOPO-PUNTOS`` with its number
and description in XDATA under the ``INGECAD`` APPID, plus up to three
TEXT labels (number, elevation, description) on their own layers, each
label carrying the handle of its point so renumbering can find it. Any
CAD opens the result; only IngeCAD reads the XDATA back.
"""
from __future__ import annotations

from dataclasses import dataclass

from core.actions import AddEntityCommand
from core.commands import Command, CompositeCommand
from core.layers import NewLayerCommand

from .points import SurveyPoint

APPID = "INGECAD"
POINT_TAG = "TOPO-POINT"
LABEL_TAG = "TOPO-LABEL"

#: (layer, ACI colour) for the point and each label kind.
LAYERS = {
    "point": ("TOPO-PUNTOS", 7),
    "number": ("TOPO-NUMEROS", 2),
    "elevation": ("TOPO-COTAS", 3),
    "description": ("TOPO-DESC", 4),
}
ALL_LABELS = ("number", "elevation", "description")


@dataclass
class LabelStyle:
    text_height: float = 1.0
    labels: tuple = ALL_LABELS
    decimals: int = 2            # of the elevation label


def ensure_appid(doc) -> None:
    if APPID not in doc.appids:
        doc.appids.add(APPID)


class SetHeaderCommand(Command):
    """One header variable, with exact undo ($PDMODE, $PDSIZE)."""

    name = "header variable"

    def __init__(self, key: str, value) -> None:
        self.key = key
        self.value = value
        self._old = None
        self._had = False

    def do(self, document) -> None:
        header = document.doc.header
        self._had = self.key in header
        self._old = header.get(self.key) if self._had else None
        header[self.key] = self.value
        document.dirty = True

    def undo(self, document) -> None:
        header = document.doc.header
        if self._had:
            header[self.key] = self._old
        else:
            try:
                del header[self.key]
            except KeyError:
                pass
        document.dirty = True


#: AutoCAD's PDMODE 3: an X. A new drawing draws a POINT as one pixel
#: (mode 0), which no surveyor can see on a plan; the first import switches
#: the drawing to X markers sized against the labels, and leaves a drawing
#: that already chose a marker alone.
PDMODE_X = 3


def point_display_commands(document, style: "LabelStyle") -> list[Command]:
    header = document.doc.header
    if int(header.get("$PDMODE", 0)) != 0:
        return []
    return [SetHeaderCommand("$PDMODE", PDMODE_X),
            SetHeaderCommand("$PDSIZE", float(style.text_height) * 0.8)]


def layer_commands(document, kinds=("point",) + ALL_LABELS) -> list[Command]:
    """NewLayerCommands for the topography layers still missing."""
    out = []
    for kind in kinds:
        name, color = LAYERS[kind]
        if name not in document.doc.layers:
            out.append(NewLayerCommand(name, color=color))
    return out


def _point_factory(point: SurveyPoint):
    def make(msp):
        ensure_appid(msp.doc)
        entity = msp.add_point((point.east, point.north, point.z))
        entity.set_xdata(APPID, [(1000, POINT_TAG), (1000, point.name),
                                 (1000, point.desc)])
        return entity
    return make


def _label_factory(point_cmd: AddEntityCommand, kind: str, text: str,
                   offset, style: LabelStyle):
    def make(msp):
        ensure_appid(msp.doc)
        anchor = point_cmd.entity
        loc = anchor.dxf.location
        entity = msp.add_text(text, height=style.text_height)
        entity.set_placement((loc.x + offset[0] * style.text_height,
                              loc.y + offset[1] * style.text_height))
        entity.set_xdata(APPID, [(1000, LABEL_TAG), (1000, kind),
                                 (1005, anchor.dxf.handle)])
        return entity
    return make


_OFFSETS = {"number": (0.3, 0.3), "elevation": (0.3, -1.3),
            "description": (0.3, -2.9)}


def label_text(point: SurveyPoint, kind: str, style: LabelStyle) -> str:
    if kind == "number":
        return point.name
    if kind == "elevation":
        return f"{point.z:.{style.decimals}f}"
    return point.desc


def point_commands(point: SurveyPoint, style: LabelStyle) -> list[Command]:
    """The POINT and its labels, as commands in the order they must run."""
    point_cmd = AddEntityCommand("TOPO-POINT", _point_factory(point),
                                 layer=LAYERS["point"][0])
    out: list[Command] = [point_cmd]
    for kind in style.labels:
        text = label_text(point, kind, style)
        if not text:
            continue
        out.append(AddEntityCommand(
            "TOPO-LABEL", _label_factory(point_cmd, kind, text, _OFFSETS[kind], style),
            layer=LAYERS[kind][0]))
    return out


def import_points(document, points, style: LabelStyle | None = None) -> CompositeCommand:
    """All the points, their labels and any missing layer as ONE undo step."""
    style = style or LabelStyle()
    commands = layer_commands(document) + point_display_commands(document, style)
    for point in points:
        commands.extend(point_commands(point, style))
    return CompositeCommand("import points", commands)


def add_point(document, point: SurveyPoint, style: LabelStyle | None = None) -> CompositeCommand:
    """One surveyed point, drawn by hand (PBY)."""
    style = style or LabelStyle()
    return CompositeCommand("survey point",
                            layer_commands(document)
                            + point_display_commands(document, style)
                            + point_commands(point, style))


# -- reading back ----------------------------------------------------------------

def _xdata(entity):
    try:
        return [value for _code, value in entity.get_xdata(APPID)]
    except Exception:
        return None


def is_survey_point(entity) -> bool:
    if entity.dxftype() != "POINT":
        return False
    data = _xdata(entity)
    return bool(data) and data[0] == POINT_TAG


def survey_point(entity) -> SurveyPoint:
    """The point an entity stands for; a bare POINT has no name."""
    loc = entity.dxf.location
    data = _xdata(entity) or []
    name = str(data[1]) if len(data) > 1 and data[0] == POINT_TAG else ""
    desc = str(data[2]) if len(data) > 2 and data[0] == POINT_TAG else ""
    return SurveyPoint(name, loc.x, loc.y, loc.z, desc)


def survey_points(document, entities=None) -> list[SurveyPoint]:
    """The survey points among ``entities`` (or in the current space), in
    drawing order. Bare POINTs count too, numbered by position."""
    source = entities if entities is not None else document.current_space()
    out = []
    for entity in source:
        if entity.dxftype() != "POINT":
            continue
        point = survey_point(entity)
        if not point.name:
            point.name = str(len(out) + 1)
        out.append(point)
    return out


def find_point(document, name: str):
    """The POINT entity numbered ``name``, or None."""
    wanted = name.strip().upper()
    for entity in document.current_space():
        if is_survey_point(entity) and survey_point(entity).name.upper() == wanted:
            return entity
    return None


def next_number(document) -> str:
    """One past the highest numeric point name in the current space."""
    highest = 0
    for entity in document.current_space():
        if is_survey_point(entity):
            name = survey_point(entity).name
            if name.isdigit():
                highest = max(highest, int(name))
    return str(highest + 1)


def labels_of(document, point_entity) -> dict:
    """{kind: TEXT} of the labels hanging from ``point_entity``."""
    handle = point_entity.dxf.handle
    out = {}
    for entity in document.current_space():
        if entity.dxftype() != "TEXT":
            continue
        data = _xdata(entity)
        if data and data[0] == LABEL_TAG and len(data) > 2 and data[2] == handle:
            out[str(data[1])] = entity
    return out


class RenumberCommand(Command):
    """Give the points new numbers (``start``, ``start+step``...) in the
    order given, rewriting their XDATA and their number labels; undo puts
    the old numbers back."""

    name = "renumber points"

    def __init__(self, entities, start: int, step: int = 1) -> None:
        self.handles = [e.dxf.handle for e in entities]
        self.start = start
        self.step = step
        self._old: dict[str, str] = {}

    def _apply(self, document, names: dict[str, str]) -> None:
        space = document.current_space()
        for entity in space:
            if entity.dxf.handle not in names or not is_survey_point(entity):
                continue
            point = survey_point(entity)
            entity.set_xdata(APPID, [(1000, POINT_TAG), (1000, names[entity.dxf.handle]),
                                     (1000, point.desc)])
            label = labels_of(document, entity).get("number")
            if label is not None:
                label.dxf.text = names[entity.dxf.handle]
        document.dirty = True

    def do(self, document) -> None:
        by_handle = {e.dxf.handle: e for e in document.current_space()
                     if e.dxf.handle in self.handles}
        new = {}
        number = self.start
        for handle in self.handles:
            entity = by_handle.get(handle)
            if entity is None or not is_survey_point(entity):
                continue
            self._old.setdefault(handle, survey_point(entity).name)
            new[handle] = str(number)
            number += self.step
        self._apply(document, new)

    def undo(self, document) -> None:
        self._apply(document, dict(self._old))


def renumber(entities, start: int, step: int = 1) -> RenumberCommand:
    return RenumberCommand(entities, start, step)
