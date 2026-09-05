# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The drawing's georeference: which UTM zone, hemisphere and datum its
coordinates are in. One place answers that question, for every plugin
and for the core (docs/plan-complementos.md, G1).

It travels inside the drawing as plain DXF: the root dictionary holds an
``INGECAD`` dictionary, and that one an XRECORD ``GEOREF`` of ``key=value``
strings (group 1). Every CAD preserves dictionaries and XRECORDs it does
not know, LibreDWG writes them into a DWG, and a colleague's AutoCAD shows
nothing odd -- the same conservative round trip the whole product rests on.
The maths that turns a zone into latitudes lives in the Terrain plugin;
the core only keeps the declaration.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from core.commands import Command

DICT_NAME = "INGECAD"
RECORD_NAME = "GEOREF"

#: The datums a drawing may declare. WGS84 is what GPS and Google Earth
#: use; PSAD56 (Provisional South American Datum 1956, International 1924
#: ellipsoid) is what Peru's older plans and IGN sheets are in.
DATUMS = ("WGS84", "PSAD56")


@dataclass(frozen=True)
class Georef:
    """UTM zone, hemisphere, datum -- and, for a datum other than WGS84,
    the geocentric translation (dX, dY, dZ in metres) that takes it TO
    WGS84. Kept with the drawing so its conversion is reproducible."""

    zone: int
    northern: bool = False
    datum: str = "WGS84"
    shift: tuple[float, float, float] = (0.0, 0.0, 0.0)

    def __post_init__(self) -> None:
        if not 1 <= int(self.zone) <= 60:
            raise ValueError(f"UTM zone must be 1 to 60, not {self.zone}")
        if self.datum not in DATUMS:
            raise ValueError(f"unknown datum {self.datum!r}")
        object.__setattr__(self, "zone", int(self.zone))
        object.__setattr__(self, "shift", tuple(float(v) for v in self.shift))

    @property
    def hemisphere(self) -> str:
        return "N" if self.northern else "S"

    def zone_label(self) -> str:
        """``19 S`` -- how a chart or a report names the zone."""
        return f"{self.zone} {self.hemisphere}"

    def label(self) -> str:
        """``WGS84 UTM 19 S`` -- short, language-free."""
        return f"{self.datum} UTM {self.zone_label()}"

    def to_tags(self) -> list[tuple[int, str]]:
        dx, dy, dz = self.shift
        return [(1, f"zone={self.zone}"), (1, f"hemisphere={self.hemisphere}"),
                (1, f"datum={self.datum}"), (1, f"shift={dx:g},{dy:g},{dz:g}")]

    @classmethod
    def from_tags(cls, tags) -> Optional["Georef"]:
        """The record read back; None when it does not name a valid zone.
        Unknown keys are ignored, so a newer IngeCAD may add some."""
        values: dict[str, str] = {}
        for code, value in tags:
            if code == 1 and "=" in str(value):
                key, _, val = str(value).partition("=")
                values[key.strip().lower()] = val.strip()
        try:
            zone = int(values.get("zone", ""))
            datum = values.get("datum", "WGS84").upper()
            shift = tuple(float(v) for v in values.get("shift", "0,0,0").split(","))
            if len(shift) != 3:
                shift = (0.0, 0.0, 0.0)
            return cls(zone, values.get("hemisphere", "S").upper() != "S", datum, shift)
        except (TypeError, ValueError):
            return None


def read_georef(doc) -> Optional[Georef]:
    """The georeference an ezdxf drawing declares, or None."""
    folder = doc.rootdict.get(DICT_NAME, None)
    if folder is None:
        return None
    record = folder.get(RECORD_NAME, None)
    if record is None or record.dxftype() != "XRECORD":
        return None
    return Georef.from_tags(record.tags)


def write_georef(doc, georef: Optional[Georef]) -> None:
    """Declare ``georef`` in the drawing; None removes the declaration and
    leaves no empty dictionary behind."""
    folder = doc.rootdict.get(DICT_NAME, None)
    if georef is None:
        if folder is None:
            return
        record = folder.get(RECORD_NAME, None)
        if record is not None:
            folder.discard(RECORD_NAME)
            doc.objects.delete_entity(record)
        if len(folder) == 0:
            doc.rootdict.discard(DICT_NAME)
            doc.objects.delete_entity(folder)
        return
    if folder is None:
        folder = doc.rootdict.add_new_dict(DICT_NAME)
    record = folder.get(RECORD_NAME, None)
    if record is None or record.dxftype() != "XRECORD":
        record = folder.add_xrecord(RECORD_NAME)
    record.reset(georef.to_tags())


class SetGeorefCommand(Command):
    """Declare (or remove, with None) the drawing's georeference; undo
    puts back exactly what was declared before."""

    name = "georeference"

    def __init__(self, georef: Optional[Georef]) -> None:
        self.georef = georef
        self._old: Optional[Georef] = None

    def do(self, document) -> None:
        self._old = read_georef(document.doc)
        write_georef(document.doc, self.georef)
        document.dirty = True

    def undo(self, document) -> None:
        write_georef(document.doc, self._old)
        document.dirty = True
