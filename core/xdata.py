# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""IngeCAD's APPID for XDATA, and the check that an APPID is registered
before an entity refers to it.

``INGECAD`` belongs to IngeCAD and its bundled plugins (a survey point's
number, a contour's level, a geographic point's latitude): plain DXF that
any CAD preserves and none misreads. A third-party plugin registers an
APPID of its own (``ensure_appid(doc, "GEOCAD")``) and never writes under
``INGECAD``: ``set_xdata`` replaces everything under an APPID, so a plugin
sharing it would wipe the survey and terrain tags of the same entity, and
``discard_xdata`` would take them all."""
from __future__ import annotations

APPID = "INGECAD"


def ensure_appid(doc, name: str = APPID) -> None:
    """Register ``name`` in the drawing's APPID table if it is not there
    yet; ezdxf refuses XDATA under an unknown application name."""
    if name not in doc.appids:
        doc.appids.add(name)
