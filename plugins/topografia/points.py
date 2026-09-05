# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Survey points as text: the files a total station or a GPS hands over,
and the bearings a surveyor types. Pure functions, no document, no Qt.

The classic layout is ``P,N,E,Z,D`` (point, northing, easting, elevation,
description) and Latin-American station software emits it with commas,
semicolons, tabs or spaces, sometimes with a decimal comma, sometimes with
a header row. :func:`parse_points` takes all of that; :func:`sniff_order`
guesses the column order from the numbers themselves (a UTM northing in
the southern hemisphere is a seven-digit number, an easting six) and the
import dialog lets the user overrule it.
"""
from __future__ import annotations

import csv
import io
import math
import re
from dataclasses import dataclass

#: Column orders offered by the import; ``N`` northing, ``E`` easting.
ORDERS = ("PNEZD", "PENZD", "NEZD", "ENZD", "PNEZ", "PENZ", "NEZ", "ENZ")


@dataclass
class SurveyPoint:
    name: str
    east: float
    north: float
    z: float = 0.0
    desc: str = ""


def _num(cell: str) -> float:
    """A coordinate cell, tolerating the decimal comma."""
    return float(cell.strip().replace(",", "."))


def _cells(line: str) -> list[str]:
    if ";" in line:
        cells = next(csv.reader(io.StringIO(line), delimiter=";"))
    elif "\t" in line:
        cells = line.split("\t")
    elif "," in line and not re.match(r"^[-\d.,\s]+$", line.replace(",", " ")):
        cells = next(csv.reader(io.StringIO(line)))
    elif "," in line and " " not in line.strip():
        cells = next(csv.reader(io.StringIO(line)))
    else:
        cells = line.split()
    return [c.strip() for c in cells]


def _rows(text: str) -> list[list[str]]:
    rows = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        rows.append(_cells(line))
    return rows


def _is_number(cell: str) -> bool:
    try:
        _num(cell)
    except ValueError:
        return False
    return True


def sniff_order(text: str) -> str:
    """The most plausible column order for this file, by the first data row.

    Three numeric columns and nothing before them: ``NEZ`` or ``ENZ``; a
    leading non-numeric or integer cell is the point name (``P...``). N
    against E is decided by size: in the southern hemisphere a northing is
    millions and an easting hundreds of thousands, and in the north a
    northing is still the larger of the two well away from the equator. A
    file that fools this is one the dialog exists for.
    """
    for cells in _rows(text):
        numeric = [_is_number(c) for c in cells]
        if len(cells) >= 3 and all(numeric[:3]) and \
                not (len(cells) >= 4 and all(numeric[:4]) and "." not in cells[0]):
            first, second = _num(cells[0]), _num(cells[1])
            base = "NEZ" if abs(first) >= abs(second) else "ENZ"
            return base + ("D" if len(cells) > 3 else "")
        if len(cells) >= 4 and all(numeric[1:4]):
            first, second = _num(cells[1]), _num(cells[2])
            base = "PNEZ" if abs(first) >= abs(second) else "PENZ"
            return base + ("D" if len(cells) > 4 else "")
    return "PNEZD"


def parse_points(text: str, order: str = "PNEZD") -> list[SurveyPoint]:
    """Rows of ``text`` as points, in the given column ``order``.

    Header rows and comments are skipped; a row with too few cells or a
    non-numeric coordinate is skipped too. Raises ``ValueError`` when no
    point parses: a wrong file fails loudly instead of importing nothing.
    """
    order = order.upper()
    if order not in ORDERS:
        raise ValueError(f"unknown column order {order!r}")
    idx = {letter: i for i, letter in enumerate(order)}
    needed = max(idx["N"], idx["E"]) + 1
    points: list[SurveyPoint] = []
    auto = 1
    for cells in _rows(text):
        if len(cells) < needed:
            continue
        try:
            north, east = _num(cells[idx["N"]]), _num(cells[idx["E"]])
            z = _num(cells[idx["Z"]]) if "Z" in idx and len(cells) > idx["Z"] \
                and cells[idx["Z"]] != "" else 0.0
        except ValueError:
            continue                        # header, or a stray text row
        if "P" in idx:
            name = cells[idx["P"]]
        else:
            name = str(auto)
            auto += 1
        desc = ""
        if "D" in idx and len(cells) > idx["D"]:
            desc = " ".join(c for c in cells[idx["D"]:] if c).strip()
        points.append(SurveyPoint(name, east, north, z, desc))
    if not points:
        raise ValueError("no survey points found (expected P,N,E,Z[,D] columns)")
    return points


def format_points(points, order: str = "PNEZD", delimiter: str = ",",
                  decimals: int = 3) -> str:
    """Points as text, one per line, in ``order`` -- what PEXPORT writes."""
    order = order.upper()
    lines = []
    for p in points:
        cells = []
        for letter in order:
            if letter == "P":
                cells.append(p.name)
            elif letter == "N":
                cells.append(f"{p.north:.{decimals}f}")
            elif letter == "E":
                cells.append(f"{p.east:.{decimals}f}")
            elif letter == "Z":
                cells.append(f"{p.z:.{decimals}f}")
            elif letter == "D":
                cells.append(p.desc)
        lines.append(delimiter.join(cells))
    return "\n".join(lines) + "\n"


# -- bearings ------------------------------------------------------------------

_DMS = re.compile(
    r"^\s*(?P<deg>\d+(?:[.,]\d+)?)\s*(?:[°d]\s*)?"
    r"(?:(?P<min>\d+(?:[.,]\d+)?)\s*(?:['m′]\s*)?)?"
    r"(?:(?P<sec>\d+(?:[.,]\d+)?)\s*(?:[\"s″]\s*)?)?\s*$")
_QUADRANT = re.compile(r"^\s*(?P<ns>[NS])\s*(?P<body>.+?)\s*(?P<ew>[EW])\s*$",
                       re.IGNORECASE)


def parse_dms(text: str) -> float:
    """``45°30'20"``, ``45d30m20s``, ``45 30 20``, ``45-30-20`` or ``45.5``
    as decimal degrees."""
    body = text.strip().replace("-", " ").replace(":", " ")
    m = _DMS.match(body)
    if not m:
        raise ValueError(f"not an angle: {text!r}")
    deg = float(m.group("deg").replace(",", "."))
    minutes = float((m.group("min") or "0").replace(",", "."))
    seconds = float((m.group("sec") or "0").replace(",", "."))
    if minutes >= 60 or seconds >= 60:
        raise ValueError(f"minutes and seconds run to 59: {text!r}")
    return deg + minutes / 60.0 + seconds / 3600.0


def parse_bearing(text: str) -> float:
    """A bearing as typed, as an azimuth in degrees from north, clockwise.

    Quadrant form ``N45°30'E`` / ``S12E`` / ``N 45 30 20 W``, or a plain
    azimuth ``123.45`` / ``123°27'24"``. Raises ``ValueError`` otherwise.
    """
    m = _QUADRANT.match(text)
    if m:
        angle = parse_dms(m.group("body"))
        if angle > 90.0:
            raise ValueError(f"a quadrant bearing runs to 90°: {text!r}")
        ns, ew = m.group("ns").upper(), m.group("ew").upper()
        if ns == "N":
            az = angle if ew == "E" else 360.0 - angle
        else:
            az = 180.0 - angle if ew == "E" else 180.0 + angle
        return az % 360.0
    return parse_dms(text) % 360.0


def format_bearing(azimuth: float, seconds: bool = True) -> str:
    """An azimuth as the quadrant bearing surveyors read: ``N 45°30'20" E``."""
    az = azimuth % 360.0
    if az <= 90.0:
        ns, ew, angle = "N", "E", az
    elif az <= 180.0:
        ns, ew, angle = "S", "E", 180.0 - az
    elif az <= 270.0:
        ns, ew, angle = "S", "W", az - 180.0
    else:
        ns, ew, angle = "N", "W", 360.0 - az
    return f"{ns} {format_dms(angle, seconds)} {ew}"


def format_dms(degrees: float, seconds: bool = True) -> str:
    total = round(degrees * 3600.0) if seconds else round(degrees * 60.0) * 60
    d, rest = divmod(int(total), 3600)
    m, s = divmod(rest, 60)
    return f"{d}°{m:02d}'{s:02d}\"" if seconds else f"{d}°{m:02d}'"


def azimuth_to_cad(azimuth: float) -> float:
    """Azimuth (from north, clockwise) -> CAD angle (from east, CCW)."""
    return (90.0 - azimuth) % 360.0


def cad_to_azimuth(angle: float) -> float:
    return (90.0 - angle) % 360.0


def point_from_bearing(base, azimuth: float, distance: float) -> tuple[float, float]:
    """The point ``distance`` away from ``base`` along ``azimuth``."""
    rad = math.radians(azimuth_to_cad(azimuth))
    return (base[0] + distance * math.cos(rad), base[1] + distance * math.sin(rad))


def bearing_between(a, b) -> tuple[float, float]:
    """(azimuth, distance) from ``a`` to ``b``."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    return cad_to_azimuth(math.degrees(math.atan2(dy, dx))), math.hypot(dx, dy)
