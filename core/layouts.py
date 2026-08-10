# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Layout (paper space) operations: tabs, active layout, the paper sheet.

Everything here is headless (AI-native invariant): the tab bar, the LAYOUT
command and the tests all drive the same functions. The DXF conventions this
codes against are documented in docs/reference/layout/ (gitignored research
notes); the two that bite:

- ``doc.layouts.set_active_layout()`` does NOT touch ``$TILEMODE`` — without
  setting the header variable ourselves, AutoCAD reopens the file on the
  wrong tab. :func:`switch_active` does both together.
- Paper size, margins and plot offset are stored in **mm always**, whatever
  ``plot_paper_units`` says; and the paperspace coordinate origin sits at the
  lower-left corner of the *printable* area (+ plot offset), not the sheet
  corner. :func:`paper_frame` owns that math.
"""
from __future__ import annotations

import math
from typing import Callable, Optional

from ezdxf.lldxf.const import DXFValueError

from core.actions import Prompt
from core.commands import Command
from core.i18n import tr

# AcDbPlotSettings defaults (A3 paper, mm): used when a file carries no
# usable page setup — AutoCAD also shows *some* sheet in every layout tab.
_DEFAULT_PAPER = (420.0, 297.0)             # width, height
_DEFAULT_MARGINS = (20.0, 7.5, 20.0, 7.5)   # top, right, bottom, left
# Paper dimensions beyond this are corrupt, not a real sheet (20 m of paper).
_MAX_PAPER = 20000.0


# -- tab names ------------------------------------------------------------------

def layout_names(document) -> list[str]:
    """Tab names in taborder, with "Model" always first (AutoCAD behavior:
    the Model tab is fixed regardless of its stored taborder)."""
    try:
        names = document.doc.layouts.names_in_taborder()
    except Exception:
        names = list(document.doc.layouts.names())
    return ["Model"] + [n for n in names if n.lower() != "model"]


def default_new_name(document) -> str:
    """First free ``LayoutN`` name, AutoCAD-style (case-insensitive)."""
    taken = {n.lower() for n in layout_names(document)}
    i = 1
    while f"layout{i}" in taken:
        i += 1
    return f"Layout{i}"


def startup_tab(document) -> Optional[str]:
    """The tab the file says is current, or None for the Model tab.

    ``$TILEMODE`` = 0 means a paperspace tab was active when the file was
    saved; AutoCAD reopens there and so do we.
    """
    doc = document.doc
    try:
        if int(doc.header.get("$TILEMODE", 1)) != 0:
            return None
        return doc.layouts.active_layout().name
    except Exception:
        return None


# -- switching ------------------------------------------------------------------

def switch_active(document, name: str) -> None:
    """Make ``name`` the current tab in the document itself.

    Not a Command on purpose: AutoCAD does not put tab switches on the undo
    stack either. The document still changes (block-rename dance + header),
    so the file reopens on the same tab everywhere.
    """
    doc = document.doc
    if name.lower() == "model":
        doc.header["$TILEMODE"] = 1
    else:
        active = doc.layouts.active_layout()
        if active.name.lower() != name.lower():
            doc.layouts.set_active_layout(name)   # raises on unknown name
        doc.header["$TILEMODE"] = 0
    document.dirty = True


# -- create / rename / delete ---------------------------------------------------

class NewLayoutCommand(Command):
    """LAYOUT New — undo deletes the (still empty) layout again."""

    def __init__(self, layout_name: str) -> None:
        self.name = "LAYOUT New"
        self.layout_name = layout_name

    def do(self, document) -> None:
        document.doc.layouts.new(self.layout_name)
        document.dirty = True

    def undo(self, document) -> None:
        document.doc.layouts.delete(self.layout_name)
        document.dirty = True


class RenameLayoutCommand(Command):
    """LAYOUT Rename — fully reversible."""

    def __init__(self, old: str, new: str) -> None:
        self.name = "LAYOUT Rename"
        self.old = old
        self.new = new

    def do(self, document) -> None:
        document.doc.layouts.rename(self.old, self.new)
        document.dirty = True

    def undo(self, document) -> None:
        document.doc.layouts.rename(self.new, self.old)
        document.dirty = True


def delete_layout(document, name: str) -> None:
    """Delete a layout and everything on it. Permanent, like AutoCAD warns
    ("The selected layout will be permanently deleted") — deliberately NOT a
    Command: a faithful undo would need to snapshot every entity of the
    layout, and a half-faithful one would lie. Callers confirm first.

    Raises ``DXFValueError`` for "Model" and for the last paperspace layout
    (same rules as AutoCAD).
    """
    document.doc.layouts.delete(name)
    document.dirty = True


def validate_new_name(document, name: str) -> Optional[str]:
    """None if ``name`` can be used for a new/renamed layout, else why not."""
    name = name.strip()
    if not name:
        return tr("Layout name cannot be empty.")
    if len(name) > 255:
        return tr("Layout name is too long (255 characters maximum).")
    if any(ch in name for ch in '<>/\\":;?*|=`'):
        return tr("Layout name contains invalid characters.")
    if name.lower() in (n.lower() for n in layout_names(document)):
        return tr('Layout "{name}" already exists.', name=name)
    return None


# -- the paper sheet ------------------------------------------------------------

def paper_frame(layout) -> dict:
    """Sheet + printable rectangles of a paperspace layout, in paperspace
    drawing units, ready for the viewport to draw.

    Convention (verified against ezdxf's ``reset_paper_limits`` and the
    drawing add-on's ``Page.from_dxf_layout``): paperspace (0, 0) is the
    lower-left corner of the printable area plus the plot-origin offset;
    everything is stored in mm and divided by 25.4 when the layout plots in
    inches; ``plot_rotation`` 1/3 swaps the sheet dimensions and rotates the
    margins with them.

    Returns ``{"sheet": (x0, y0, x1, y1), "printable": (...) | None}``.
    """
    dxf = layout.dxf

    def num(field, default=0.0):
        # dxf.get(), not getattr(): an unset optional attribute raises
        # DXFValueError, which getattr's default would not catch.
        try:
            v = float(dxf.get(field, default))
        except (TypeError, ValueError):
            return default
        return v if math.isfinite(v) else default

    unit = 25.4 if int(num("plot_paper_units", 1)) == 0 else 1.0
    w = num("paper_width") / unit
    h = num("paper_height") / unit
    m_top = num("top_margin") / unit
    m_right = num("right_margin") / unit
    m_bottom = num("bottom_margin") / unit
    m_left = num("left_margin") / unit
    if not (0.0 < w < _MAX_PAPER and 0.0 < h < _MAX_PAPER):
        w, h = _DEFAULT_PAPER
        m_top, m_right, m_bottom, m_left = _DEFAULT_MARGINS
        unit = 1.0

    rotation = int(num("plot_rotation", 0)) % 4
    if rotation == 1:    # 90° CCW
        w, h = h, w
        m_top, m_right, m_bottom, m_left = m_right, m_bottom, m_left, m_top
    elif rotation == 2:  # 180°
        m_top, m_right, m_bottom, m_left = m_bottom, m_left, m_top, m_right
    elif rotation == 3:  # 90° CW
        w, h = h, w
        m_top, m_right, m_bottom, m_left = m_left, m_top, m_right, m_bottom

    ox = num("plot_origin_x_offset") / unit
    oy = num("plot_origin_y_offset") / unit

    sheet = (-(m_left + ox), -(m_bottom + oy),
             -(m_left + ox) + w, -(m_bottom + oy) + h)
    printable = None
    pw = w - m_left - m_right
    ph = h - m_top - m_bottom
    if pw > 0.0 and ph > 0.0:
        printable = (-ox, -oy, -ox + pw, -oy + ph)
    return {"sheet": sheet, "printable": printable}


# -- the LAYOUT command (headless prompt flow) ----------------------------------

LAYOUT_PROMPT = "Enter layout option [Copy/Delete/New/Template/Rename/SAveas/Set/?] <set>:"


def layout_command(
    document,
    history,
    *,
    switch: Callable[[str], None],
    echo: Callable[[str], None],
    refresh: Callable[[], None],
    current: Callable[[], str],
    args: tuple = (),
) -> Optional[Prompt]:
    """The AutoCAD LAYOUT command: same keywords, same prompt strings.

    ``switch``/``refresh`` are UI callbacks (tab switch, tab-bar rebuild);
    ``current`` returns the current tab name for the prompt defaults. Extra
    ``args`` typed on the command line ("LAYOUT N Sheet2") are consumed as
    the answers to the successive prompts.
    """
    def paper_default() -> str:
        # Default layout for Delete/Rename/Set: the current tab if it is a
        # paperspace layout, else the first one.
        name = current()
        if name.lower() != "model":
            return name
        names = [n for n in layout_names(document) if n.lower() != "model"]
        return names[0] if names else ""

    def find(name: str) -> Optional[str]:
        for n in layout_names(document):
            if n.lower() == name.lower():
                return n
        return None

    def on_new(text: str) -> None:
        name = text.strip() or default_new_name(document)
        problem = validate_new_name(document, name)
        if problem:
            echo(problem)
            return
        history.execute(NewLayoutCommand(name))
        refresh()
        echo(tr('Layout "{name}" created.', name=name))

    def on_delete(text: str) -> None:
        name = find(text.strip() or paper_default())
        if name is None:
            echo(tr('Layout "{name}" does not exist.', name=text.strip()))
            return
        if name.lower() == "model":
            echo(tr("The Model tab cannot be deleted."))
            return
        try:
            delete_layout(document, name)
        except DXFValueError:
            echo(tr("The last layout cannot be deleted."))
            return
        refresh()
        echo(tr('Layout "{name}" deleted.', name=name))

    def on_rename_old(text: str) -> Optional[Prompt]:
        old = find(text.strip() or paper_default())
        if old is None:
            echo(tr('Layout "{name}" does not exist.', name=text.strip()))
            return None
        if old.lower() == "model":
            echo(tr("The Model tab cannot be renamed."))
            return None

        def on_rename_new(text: str) -> None:
            new = text.strip()
            problem = validate_new_name(document, new)
            if problem:
                echo(problem)
                return
            history.execute(RenameLayoutCommand(old, new))
            refresh()
            echo(tr('Layout "{old}" renamed to "{new}".', old=old, new=new))

        return Prompt(tr("Enter new layout name:"), on_rename_new)

    def on_set(text: str) -> None:
        name = find(text.strip() or paper_default())
        if name is None:
            echo(tr('Layout "{name}" does not exist.', name=text.strip()))
            return
        switch(name)

    def on_option(text: str) -> Optional[Prompt]:
        opt = text.strip().upper()
        if opt in ("", "S", "SET"):
            return Prompt(
                tr("Enter layout to make current <{name}>:",
                   name=paper_default()), on_set)
        if opt in ("N", "NEW"):
            return Prompt(
                tr("Enter new layout name <{name}>:",
                   name=default_new_name(document)), on_new)
        if opt in ("D", "DELETE"):
            return Prompt(
                tr("Enter name of layout to delete <{name}>:",
                   name=paper_default()), on_delete)
        if opt in ("R", "RENAME"):
            return Prompt(
                tr("Enter layout to rename <{name}>:",
                   name=paper_default()), on_rename_old)
        if opt == "?":
            names = [n for n in layout_names(document) if n.lower() != "model"]
            echo(tr("Active layouts: {names}.",
                    names=", ".join(f'"{n}"' for n in names)))
            return None
        if opt in ("C", "COPY", "T", "TEMPLATE", "SA", "SAVEAS"):
            echo(tr("LAYOUT {option}: not available yet.", option=opt))
            return None
        echo(tr('Unknown LAYOUT option "{name}".', name=text.strip()))
        return None

    # Args typed inline answer the prompts in order (AutoCAD behavior).
    result: Optional[Prompt] = Prompt(tr(LAYOUT_PROMPT), on_option)
    for arg in args:
        if result is None:
            return None
        result = result.on_input(arg)
    return result
