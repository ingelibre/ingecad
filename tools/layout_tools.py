# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Paper-space tools: MVIEW (floating viewports).

Only usable on a layout tab — the controller gates them the same way it
gates model-space drawing tools out of paper space (AutoCAD's
"** Command not allowed in Model Tab **").
"""
from __future__ import annotations

from dataclasses import dataclass

from core import layouts as layout_ops
from core.i18n import tr
from tools.base import Point, Tool


@dataclass
class MviewTool(Tool):
    """MVIEW: corner-point rectangle, or Fit for the whole printable area."""

    name: str = "MVIEW"

    def start(self) -> None:
        self._first: Point | None = None
        self.prompt("Specify corner of viewport or [Fit] <Fit>:")

    def _paper(self):
        """(document, layout_name) from the controller (fake in tests)."""
        return self.ctx.services.paper_context()

    def on_option(self, text: str) -> bool:
        if self.option(text) == "F":
            document, layout_name = self._paper()
            command = layout_ops.viewport_fit_printable(document, layout_name)
            if command is not None:
                self.ctx.execute(command)
                self.ctx.echo(tr("Viewport created (Fit)."))
            self.ctx.finish()
            return True
        return False

    def on_enter(self) -> None:
        # Enter on the first prompt takes the <Fit> default.
        if self._first is None:
            self.on_option("F")
        else:
            self.ctx.finish()

    def on_point(self, point: Point) -> None:
        if self._first is None:
            self._first = point
            self.preview_points = [point]     # rubber rectangle anchor
            self.prompt("Specify opposite corner:")
            return
        document, layout_name = self._paper()
        command = layout_ops.viewport_from_corners(
            document, layout_name, self._first, point)
        if command is None:
            self.ctx.echo(tr("Zero-size viewport — nothing created."))
        else:
            self.ctx.execute(command)
            self.ctx.echo(tr("Viewport created."))
        self.ctx.finish()

    def preview_segments(self, cursor: Point):
        if self._first is None:
            return []
        (x0, y0), (x1, y1) = self._first, cursor
        return [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)),
                ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))]


LAYOUT_TOOL_CLASSES = {"MVIEW": MviewTool}
