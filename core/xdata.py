# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The one APPID IngeCAD writes XDATA under, and the check that it is
registered before an entity refers to it. Every plugin tags its entities
(a survey point's number, a contour's level, a geographic point's
latitude) as XDATA under ``INGECAD`` -- plain DXF that any CAD preserves
and none misreads -- so the name lives in one place."""
from __future__ import annotations

APPID = "INGECAD"


def ensure_appid(doc) -> None:
    """Register the APPID in the drawing's table if it is not there yet;
    ezdxf refuses XDATA under an unknown application name."""
    if APPID not in doc.appids:
        doc.appids.add(APPID)
