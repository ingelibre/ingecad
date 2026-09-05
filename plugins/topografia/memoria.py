# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The descriptive report of a lot (memoria descriptiva): boundaries by
front, right, back and left as one enters, their lengths and neighbours,
the area, the perimeter and the technical chart. Pure text; the wording
comes through ``tr()`` so the Spanish pack gives the Peruvian phrasing.

The structure follows what a Peruvian filing (municipal licence, COFOPRI,
SUNARP) expects; the exact wording of a given office is to be confirmed
against a real file, which is why every line is a translatable string.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from core.i18n import tr

ROLES_FOUR = ("front", "right", "back", "left")
ROLE_LABELS = {
    "front": "Front",
    "right": "Right (entering)",
    "back": "Back",
    "left": "Left (entering)",
}


def side_roles(n_sides: int, front: int) -> list[str]:
    """The role of each side, walking clockwise from the front: a
    four-sided lot gets front / right / back / left; any other count
    gets the front and then numbered sides."""
    roles = ["" for _ in range(n_sides)]
    if n_sides == 4:
        for k, role in enumerate(ROLES_FOUR):
            roles[(front + k) % 4] = role
        return roles
    for k in range(n_sides):
        roles[(front + k) % n_sides] = "front" if k == 0 else f"side {k + 1}"
    return roles


def role_label(role: str) -> str:
    if role in ROLE_LABELS:
        return tr(ROLE_LABELS[role])
    if role.startswith("side "):
        return tr("Side {n}", n=role.split(" ", 1)[1])
    return role


@dataclass
class Boundary:
    role: str
    side: str                 # "V1-V2"
    length: float
    bearing: str
    neighbour: str = ""


@dataclass
class Memoria:
    name: str
    location: str
    boundaries: list = field(default_factory=list)
    rows: list = field(default_factory=list)      # the technical chart rows
    area: float = 0.0
    perimeter: float = 0.0
    datum: str = "WGS84"
    zone: str = "19 S"

    def text(self) -> str:
        lines = [tr("DESCRIPTIVE REPORT"), self.name.upper(), ""]
        if self.location:
            lines += [tr("Location: {place}", place=self.location), ""]
        lines.append(tr("BOUNDARIES AND PERIMETER MEASUREMENTS"))
        for b in self.boundaries:
            neighbour = b.neighbour or tr("(neighbour not stated)")
            lines.append(tr("{role}: adjoins {neighbour}, in a straight line of {length:.2f} m "
                            "(side {side}, bearing {bearing}).",
                            role=role_label(b.role), neighbour=neighbour,
                            length=b.length, side=b.side, bearing=b.bearing))
        lines += ["", tr("AREA: {area:.2f} m²", area=self.area),
                  tr("PERIMETER: {per:.2f} m", per=self.perimeter), ""]
        lines.append(tr("TECHNICAL DATA (datum {datum}, UTM zone {zone})",
                        datum=self.datum, zone=self.zone))
        header = [tr("VERTEX"), tr("SIDE"), tr("DISTANCE"), tr("BEARING"),
                  tr("INTERIOR ANGLE"), tr("EAST"), tr("NORTH")]
        widths = [8, 9, 11, 18, 16, 12, 13]
        lines.append("  ".join(h.ljust(w) for h, w in zip(header, widths)))
        for row in self.rows:
            lines.append("  ".join(str(c).ljust(w) for c, w in zip(row, widths)))
        return "\n".join(lines) + "\n"

    def csv(self) -> str:
        out = ["vertex,side,distance,bearing,interior_angle,east,north"]
        for row in self.rows:
            out.append(",".join(str(c) for c in row))
        out.append(f"area,{self.area:.2f}")
        out.append(f"perimeter,{self.perimeter:.2f}")
        return "\n".join(out) + "\n"


def build_memoria(name: str, location: str, rows: list, area: float, perimeter: float,
                  front: int = 0, neighbours: dict | None = None,
                  datum: str = "WGS84", zone: str = "19 S") -> Memoria:
    """``rows`` are the technical chart rows (vertex, side, distance,
    bearing, angle, east, north) in clockwise order; ``front`` is the
    index of the front side; ``neighbours`` maps a side index to who
    adjoins it."""
    neighbours = neighbours or {}
    roles = side_roles(len(rows), front)
    boundaries = []
    for k in range(len(rows)):
        i = (front + k) % len(rows)
        row = rows[i]
        boundaries.append(Boundary(roles[i], str(row[1]), float(row[2]), str(row[3]),
                                   neighbours.get(i, "")))
    return Memoria(name, location, boundaries, rows, area, perimeter, datum, zone)


# -- lots --------------------------------------------------------------------------------

@dataclass
class Lot:
    name: str
    area: float
    perimeter: float


def lots_rows(lots: list, decimals: int = 2) -> list[list[str]]:
    """One row per lot plus the total, for a table or a CSV."""
    rows = [[lot.name, f"{lot.area:.{decimals}f}", f"{lot.perimeter:.{decimals}f}"] for lot in lots]
    rows.append([tr("TOTAL"), f"{sum(l.area for l in lots):.{decimals}f}", ""])
    return rows


def lots_csv(lots: list) -> str:
    out = ["lot,area,perimeter"]
    for lot in lots:
        out.append(f"{lot.name},{lot.area:.2f},{lot.perimeter:.2f}")
    out.append(f"TOTAL,{sum(l.area for l in lots):.2f},")
    return "\n".join(out) + "\n"
