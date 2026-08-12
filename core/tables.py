# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""TABLE: a grid of lines and centered texts, built as plain geometry.

AutoCAD's TABLE creates an ACAD_TABLE compound object (Command Reference
p. 1895: title row, header row, data rows, column width, row height in
lines). IngeCAD builds the same table out of LINEs and TEXTs instead — the
construction every coordinate-chart LISP uses — because plain geometry
round-trips everywhere, edits with the normal commands, and needs no
proprietary object. One undo step removes the whole grid.

The layout mirrors the Insert Table dialog: an optional title row spanning
the full width, an optional header row, then the data grid. ``data`` fills
cells with centered text; the topography plugin's coordinate chart calls
this directly.
"""
from __future__ import annotations

from core.commands import CompositeCommand
from core.i18n import tr


def _cell_text_factory(text: str, cx: float, cy: float, height: float):
    def factory(msp):
        from ezdxf.enums import TextEntityAlignment

        entity = msp.add_text(text, dxfattribs={"height": height})
        entity.set_placement((cx, cy),
                             align=TextEntityAlignment.MIDDLE_CENTER)
        return entity
    return factory


def _line_factory(a, b):
    def factory(msp):
        return msp.add_line(a, b)
    return factory


def insert_table(insert, cols: int, col_width: float, data_rows: int,
                 row_height: float, text_height: float,
                 title: str = "", headers: list[str] | None = None,
                 data: list[list[str]] | None = None) -> CompositeCommand:
    """The whole grid as ONE undoable command.

    ``insert`` is the TOP-LEFT corner, like AutoCAD places tables.
    """
    from core import actions

    x0, y0 = float(insert[0]), float(insert[1])
    width = cols * col_width
    n_header = 1 if headers is not None else 0
    n_title = 1 if title != "" else 0
    n_rows = n_title + n_header + data_rows
    height = n_rows * row_height

    commands = []

    def add(factory):
        commands.append(actions.AddEntityCommand("TABLE", factory))

    # Horizontal lines: the title row has no internal verticals, so the
    # frame is drawn row band by row band.
    for r in range(n_rows + 1):
        y = y0 - r * row_height
        add(_line_factory((x0, y), (x0 + width, y)))
    # Verticals: full height at the borders; internal ones skip the title.
    y_top_internal = y0 - n_title * row_height
    add(_line_factory((x0, y0), (x0, y0 - height)))
    add(_line_factory((x0 + width, y0), (x0 + width, y0 - height)))
    for c in range(1, cols):
        x = x0 + c * col_width
        add(_line_factory((x, y_top_internal), (x, y0 - height)))

    if n_title:
        add(_cell_text_factory(title, x0 + width / 2.0,
                               y0 - row_height / 2.0, text_height))
    if n_header:
        y = y0 - n_title * row_height - row_height / 2.0
        for c, head in enumerate(headers or []):
            if c >= cols or not str(head):
                continue
            add(_cell_text_factory(str(head), x0 + (c + 0.5) * col_width, y,
                                   text_height))
    for r, row in enumerate(data or []):
        if r >= data_rows:
            break
        y = y0 - (n_title + n_header + r) * row_height - row_height / 2.0
        for c, value in enumerate(row):
            if c >= cols or not str(value):
                continue
            add(_cell_text_factory(str(value), x0 + (c + 0.5) * col_width, y,
                                   text_height))

    return CompositeCommand(tr("table"), commands)
