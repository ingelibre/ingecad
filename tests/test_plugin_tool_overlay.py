# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A plugin's tool paints its own overlay and preview (level 2).

A third-party plugin replaced the viewport's tool preview painting to show
what its tools chose, which piece goes and which stays, and a sample text,
and replaced the selection highlight to hide what it had matched. A tool
now answers overlay(cursor), preview_entities(cursor) and
suppress_selection_highlight.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from ezdxf.entities import factory

from core.plugins import LoadedPlugin, PluginSpec
from tools.base import Tool


class Marking(Tool):
    """Waits for a point; shows a chosen segment and a sample line."""

    suppress_selection_highlight = True

    def start(self) -> None:
        self.name = "MARKING"
        self.prompt("Specify a point:")

    def on_point(self, point) -> None:
        self.ctx.finish()

    def overlay(self, cursor):
        return {"chosen": [((0, 0), (10, 0))], "points": [cursor]}

    def preview_entities(self, cursor):
        doc = self.ctx.services.window.document.doc
        return [factory.new("LINE", dxfattribs={
            "start": (0, 0), "end": cursor}, doc=doc)]


@pytest.fixture
def win(qapp, clean_settings):
    from views.main_window import MainWindow

    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    w.new_document()
    w.tools.osnap_on = False
    spec = PluginSpec(id="ejemplo_overlay", name="Overlay",
                      tools={"MARKING": Marking})
    w.plugins.loaded[spec.id] = LoadedPlugin(spec.id, Path("."), False,
                                             spec=spec)
    assert w.plugins.activate(spec.id)
    yield w
    w.plugins.deactivate(spec.id)
    w.plugins.loaded.pop(spec.id, None)
    w.document.dirty = False
    w.close()


def _pixels(win, color) -> int:
    from PySide6.QtGui import QColor, QImage, QPainter

    vp = win.viewport
    image = QImage(vp.width(), vp.height(), QImage.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    vp._draw_tool_feedback(painter)
    painter.end()
    rgb = color.rgb()
    return sum(1 for y in range(image.height()) for x in range(image.width())
               if image.pixel(x, y) == rgb)


def _start(win):
    for text in ("LINE", "-20,-20", "20,20", "", "ZOOM", "E"):
        win._on_command_submitted(text)
    win._on_command_submitted("MARKING")
    assert type(win.tools.tool).__name__ == "Marking"
    win.tools.on_hover(5, 5)


def test_the_overlay_is_painted(win):
    _start(win)
    assert _pixels(win, win.viewport.HIGHLIGHT_COLOR) > 20


def test_the_preview_entities_are_rendered(win):
    _start(win)
    assert win.viewport._preview_scene is not None


def test_the_selection_highlight_can_be_hidden(win):
    for text in ("LINE", "0,0", "10,0", "", "ZOOM", "E"):
        win._on_command_submitted(text)
    (line,) = win.document.modelspace().query("LINE")
    win.tools.select_entities([line])
    segments, _c, _b = win.tools.highlight_geometry()
    assert len(segments)
    win._on_command_submitted("MARKING")
    segments, _c, _b = win.tools.highlight_geometry()
    assert len(segments) == 0
