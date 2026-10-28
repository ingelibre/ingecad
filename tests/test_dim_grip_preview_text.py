# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A dimension grip's drag preview writes the number as the dimension does.

Rafael's seventh review (29:08): dragging a 0-decimal dimension's grip
previewed "48.23" and landed "48" -- the preview used a fixed two decimals
and a point, whatever the style's DIMDEC and separator said.
"""
from __future__ import annotations

import pytest

from core import actions
from core.dim_commands import measurement_text
from core.document import Document


def _dim(style: str, **overrides):
    document = Document.new()
    document.doc.header["$DIMSTYLE"] = style
    actions.dim_linear((0, 0), (48.234, 0), (0, -8)).do(document)
    dim = [e for e in document.doc.modelspace() if e.dxftype() == "DIMENSION"][-1]
    if overrides:
        override = dim.override()
        for key, value in overrides.items():
            override[key] = value
        override.commit()
        dim.render()
    return dim


def _drawn(dim) -> str:
    return next(t.dxf.text for t in dim.virtual_entities()
                if t.dxftype() in ("MTEXT", "TEXT"))


@pytest.mark.parametrize("style,overrides", [
    ("ISO-25", {}),
    ("Standard", {}),
    ("ISO-25", {"dimdec": 0}),
    ("ISO-25", {"dimdec": 3, "dimdsep": ord(".")}),
    ("ISO-25", {"dimlfac": 2.0}),
])
def test_the_preview_text_is_the_drawn_text(style, overrides):
    dim = _dim(style, **overrides)
    assert measurement_text(dim, dim.get_measurement()) == _drawn(dim)


def test_the_grip_drag_preview_uses_it():
    from views.tool_controller import _dim_grip_preview

    dim = _dim("ISO-25", dimdec=0)
    preview = _dim_grip_preview(dim, "dim_defpoint3", 48.234, 0.0)
    assert preview["text"] == "48"
    text = _dim_grip_preview(dim, "dim_text", 10.0, 10.0)
    assert text["text"] == "48"
