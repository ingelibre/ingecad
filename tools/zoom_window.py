# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""ZOOM Window as AutoCAD asks for it (ZOOM, p. 2140): "Specify first
corner:", then "Specify opposite corner:" with a rectangle following the
cursor -- two clicks or two typed points, with object snaps like any
other point prompt (#80: the drag on the canvas had none).

In the Model tab and on a sheet; inside an active viewport ZOOM W stays
a drag, since a viewport has no model snaps on purpose (it is for
navigating, and building them cost 2 s on entry).
"""
from __future__ import annotations

from typing import Optional

from tools.base import Point, Tool


class ZoomWindowTool(Tool):
    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        self.name = "ZOOMWINDOW"
        self._first: Optional[Point] = None

    def start(self) -> None:
        self.prompt("Specify first corner:")

    def on_point(self, point: Point) -> None:
        if self._first is None:
            self._first = point
            self.last_point = point
            self.prompt("Specify opposite corner:")
            return
        (x0, y0), (x1, y1) = self._first, point
        if abs(x1 - x0) < 1e-12 or abs(y1 - y0) < 1e-12:
            self.prompt("Specify opposite corner:")   # a line is not a window
            return
        services = self.ctx.services
        self.ctx.finish()
        if services is not None:
            services.zoom_to_window((min(x0, x1), min(y0, y1),
                                     max(x0, x1), max(y0, y1)))

    def preview_segments(self, cursor: Point) -> list[tuple[Point, Point]]:
        if self._first is None:
            return []
        (x0, y0), (x1, y1) = self._first, cursor
        a, b, c, d = (x0, y0), (x1, y0), (x1, y1), (x0, y1)
        return [(a, b), (b, c), (c, d), (d, a)]

    def on_enter(self) -> None:
        self.ctx.finish()


ZOOM_TOOL_CLASSES = {"ZOOMWINDOW": ZoomWindowTool}
