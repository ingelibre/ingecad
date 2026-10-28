# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The view a drawing opens in, as AutoCAD keeps it.

AutoCAD opens a drawing where its author left it: the Model tab's view is
the ``*Active`` VPORT table entry (center 12/22, height 40, aspect 41,
relative to its target 17), a layout's is the paper view held by its main
viewport (id 1: view center 12/22, view height 45). IngeCAD zoomed to the
extents on every open instead, and a plan with two blocks at their true UTM
coordinates -- far from the drawing itself -- opened as an empty screen
(found by the release tour on a colleague's plan, 2026-10-10).

``saved_view`` reads that view and ``store_view`` writes the current one
back on save. A view that is missing, degenerate, or nowhere near what is
drawn (a DXF written by a program that never set one) is not used.
"""
from __future__ import annotations

import math
from typing import Optional

View = tuple[float, float, float]        # center x, center y, height (units)


def _finite(*values) -> bool:
    return all(isinstance(v, (int, float)) and math.isfinite(v) for v in values)


def _main_viewport(doc, layout_name: str):
    try:
        layout = doc.layouts.get(layout_name)
    except Exception:  # noqa: BLE001
        return None
    for vp in layout.query("VIEWPORT"):
        if int(vp.dxf.get("id", 0) or 0) == 1:
            return vp
    return None


def saved_view(doc, layout_name: str = "Model") -> Optional[View]:
    """The view the drawing was saved with on this tab, or None."""
    if layout_name == "Model":
        try:
            entries = doc.viewports.get("*Active")
        except Exception:  # noqa: BLE001
            return None
        if not entries:
            return None
        vport = entries[0]
        center = vport.dxf.get("center", None)
        height = vport.dxf.get("height", None)
        if center is None or height is None:
            return None
        target = vport.dxf.get("target", None)
        tx, ty = (target[0], target[1]) if target is not None else (0.0, 0.0)
        cx, cy = center[0] + tx, center[1] + ty
    else:
        vp = _main_viewport(doc, layout_name)
        if vp is None:
            return None
        center = vp.dxf.get("view_center_point", None)
        height = vp.dxf.get("view_height", None)
        if center is None or height is None:
            return None
        cx, cy = center[0], center[1]
    height = float(height)
    if not _finite(cx, cy, height) or not 0 < height < 1e15:
        return None
    return float(cx), float(cy), height


def near(view: View, bounds, aspect: float) -> bool:
    """Does the view show any of ``bounds`` (x0, y0, x1, y1)?"""
    if bounds is None:
        return True
    cx, cy, h = view
    w = h * max(aspect, 1e-6)
    x0, y0, x1, y1 = bounds
    return not (cx + w / 2 < x0 or cx - w / 2 > x1 or cy + h / 2 < y0 or cy - h / 2 > y1)


def store_view(doc, layout_name: str, view: View, aspect: float) -> None:
    """Write the current view where AutoCAD reads it on opening."""
    cx, cy, height = view
    if not _finite(cx, cy, height) or height <= 0:
        return
    if layout_name == "Model":
        entries = doc.viewports.get("*Active")
        vport = entries[0] if entries else doc.viewports.new("*Active")
        target = vport.dxf.get("target", None)
        tx, ty = (target[0], target[1]) if target is not None else (0.0, 0.0)
        vport.dxf.center = (cx - tx, cy - ty)
        vport.dxf.height = float(height)
        vport.dxf.aspect_ratio = float(aspect)
        return
    vp = _main_viewport(doc, layout_name)
    if vp is None:
        return
    vp.dxf.view_center_point = (cx, cy, 0.0)
    vp.dxf.view_height = float(height)
