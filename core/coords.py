# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""AutoCAD coordinate input parsing.

The prompt grammar every AutoCAD user has in muscle memory:

- ``10,5``       absolute point
- ``@10,5``      relative to the last point
- ``10<45``      absolute polar (distance < angle in degrees)
- ``@10<45``     relative polar
- ``25``         direct distance: 25 units from the last point toward the
                 cursor (requires a direction)

Angles follow AutoCAD's default: degrees, counterclockwise, 0 = east.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Optional

_NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
# ``@`` makes a point relative, ``#`` makes it absolute: with dynamic input
# on, AutoCAD reads a bare second point as relative (DYNPICOORDS 0) and
# ``#`` is how you insist on absolute there.
_CARTESIAN = re.compile(rf"^(?P<rel>[@#])?(?P<x>{_NUM})\s*,\s*(?P<y>{_NUM})$")
_POLAR = re.compile(rf"^(?P<rel>[@#])?(?P<d>{_NUM})\s*<\s*(?P<a>{_NUM})$")
_DISTANCE = re.compile(rf"^(?P<d>{_NUM})$")


@dataclass(frozen=True)
class ParsedPoint:
    x: float
    y: float


class CoordinateError(ValueError):
    """Input that looks like a coordinate but cannot be resolved."""


def parse_point(
    text: str,
    last_point: Optional[tuple[float, float]] = None,
    cursor_direction: Optional[float] = None,
    relative_default: bool = False,
) -> Optional[ParsedPoint]:
    """Parse prompt input into a world point.

    ``last_point`` anchors relative (``@``) input and direct distances;
    ``cursor_direction`` (radians) gives direct distance its direction.
    ``relative_default`` is dynamic input's rule: a bare ``x,y`` or ``d<a``
    after a first point is relative to it (``#`` forces absolute).
    Returns None when the text is not coordinate-shaped at all (so callers
    can treat it as a keyword/option instead).
    """
    text = text.strip()

    def relative(prefix) -> bool:
        if prefix == "@":
            return True
        if prefix == "#":
            return False
        return relative_default and last_point is not None

    m = _CARTESIAN.match(text)
    if m:
        x, y = float(m.group("x")), float(m.group("y"))
        if relative(m.group("rel")):
            if last_point is None:
                raise CoordinateError("relative input needs a previous point")
            return ParsedPoint(last_point[0] + x, last_point[1] + y)
        return ParsedPoint(x, y)

    m = _POLAR.match(text)
    if m:
        d, ang = float(m.group("d")), math.radians(float(m.group("a")))
        dx, dy = d * math.cos(ang), d * math.sin(ang)
        if relative(m.group("rel")):
            if last_point is None:
                raise CoordinateError("relative input needs a previous point")
            return ParsedPoint(last_point[0] + dx, last_point[1] + dy)
        return ParsedPoint(dx, dy)

    m = _DISTANCE.match(text)
    if m:
        if last_point is None or cursor_direction is None:
            raise CoordinateError("direct distance needs a previous point "
                                  "and a cursor direction")
        d = float(m.group("d"))
        return ParsedPoint(
            last_point[0] + d * math.cos(cursor_direction),
            last_point[1] + d * math.sin(cursor_direction),
        )

    return None
