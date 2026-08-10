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


# -- floating viewports (MVIEW) -------------------------------------------------

class AddViewportCommand(Command):
    """MVIEW — create one floating viewport in a paperspace layout.

    ``needs_regen`` tells the display layer that only a full regen can show
    the result (the viewport's content is the whole model re-projected —
    there is no cheap overlay for that, same as dimension blocks).
    """

    needs_regen = True

    def __init__(self, layout_name: str, center, size,
                 view_center, view_height: float) -> None:
        self.name = "MVIEW"
        self.layout_name = layout_name
        self.center = center
        self.size = size
        self.view_center = view_center
        self.view_height = view_height
        self.entity = None

    def do(self, document) -> None:
        psp = document.doc.layouts.get(self.layout_name)
        self.entity = psp.add_viewport(
            center=self.center, size=self.size,
            view_center_point=self.view_center, view_height=self.view_height)
        # AutoCAD puts the viewport on the current layer (ezdxf's default is
        # its own "VIEWPORTS" convention layer, which real files don't have).
        current = document.doc.header.get("$CLAYER", "0")
        if current in document.doc.layers:
            self.entity.dxf.layer = current
        document.dirty = True

    def undo(self, document) -> None:
        if self.entity is not None:
            self.removed_handles = [self.entity.dxf.handle]
            psp = document.doc.layouts.get(self.layout_name)
            psp.delete_entity(self.entity)
            self.entity = None
        document.dirty = True


def model_fit_view(document, width: float, height: float):
    """(view_center, view_height) that fits the whole model in a viewport
    of the given paper aspect — MVIEW's default view, like AutoCAD's Fit.

    Falls back to the origin at 1:1 when the model is empty.
    """
    ext = _model_extents(document)
    if ext is None:
        return (0.0, 0.0), max(height, 1.0)
    x0, y0, x1, y1 = ext
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    mw, mh = max(x1 - x0, 1e-9), max(y1 - y0, 1e-9)
    aspect = width / height if height > 0 else 1.0
    # both model dimensions must fit: height-limited or width-limited
    view_height = max(mh, mw / aspect) * 1.02      # small breathing margin
    return (cx, cy), view_height


def _model_extents(document):
    """Model extents from the header, or measured; None when empty."""
    try:
        lo = document.doc.header["$EXTMIN"]
        hi = document.doc.header["$EXTMAX"]
        box = (float(lo[0]), float(lo[1]), float(hi[0]), float(hi[1]))
        if all(math.isfinite(v) for v in box) and abs(box[0]) < 1e19 \
                and box[2] > box[0] and box[3] > box[1]:
            return box
    except Exception:
        pass
    try:
        from ezdxf import bbox

        ext = bbox.extents(document.modelspace(), fast=True)
        if ext.has_data:
            return (ext.extmin.x, ext.extmin.y, ext.extmax.x, ext.extmax.y)
    except Exception:
        pass
    return None


def viewport_from_corners(document, layout_name: str,
                          c1, c2) -> Optional[AddViewportCommand]:
    """MVIEW's corner-point default: a viewport spanning the picked rect,
    showing the whole model fitted (AutoCAD then lets the user zoom it)."""
    x0, x1 = sorted((c1[0], c2[0]))
    y0, y1 = sorted((c1[1], c2[1]))
    w, h = x1 - x0, y1 - y0
    if w <= 0.0 or h <= 0.0:
        return None
    center = ((x0 + x1) / 2.0, (y0 + y1) / 2.0)
    view_center, view_height = model_fit_view(document, w, h)
    return AddViewportCommand(layout_name, center, (w, h),
                              view_center, view_height)


def viewport_fit_printable(document, layout_name: str) -> AddViewportCommand:
    """MVIEW Fit: one viewport filling the printable area of the sheet."""
    layout = document.doc.layouts.get(layout_name)
    frame = paper_frame(layout)
    rect = frame["printable"] or frame["sheet"]
    return viewport_from_corners(document, layout_name,
                                 (rect[0], rect[1]), (rect[2], rect[3]))


# -- viewport as a selectable paper-space entity --------------------------------

def viewport_border_hit(layout, x: float, y: float, tol: float):
    """The topmost visible viewport whose BORDER passes within ``tol`` of
    (x, y) — AutoCAD selects viewports by their frame, not their interior."""
    hit = None
    for vp in visible_viewports(layout):        # stacking order: last on top
        x0, y0, x1, y1 = viewport_rect(vp)
        inside_outer = (x0 - tol <= x <= x1 + tol
                        and y0 - tol <= y <= y1 + tol)
        inside_inner = (x0 + tol < x < x1 - tol
                        and y0 + tol < y < y1 - tol)
        if inside_outer and not inside_inner:
            hit = vp
    return hit


def viewport_grips(vp) -> list:
    """Grip points of a viewport: 4 corners (resize) + center (move).

    AutoCAD shows the 4 corner grips; the center grip is our concession so
    a viewport can be moved without a MOVE-through-paper-space tool yet.
    """
    x0, y0, x1, y1 = viewport_rect(vp)
    return [(x0, y0, "end"), (x1, y0, "end"), (x1, y1, "end"), (x0, y1, "end"),
            ((x0 + x1) / 2.0, (y0 + y1) / 2.0, "center")]


def viewport_drag_rect(vp, index: int, role: str, point) -> tuple:
    """The rubber rectangle while a viewport grip follows the cursor."""
    x0, y0, x1, y1 = viewport_rect(vp)
    if role == "center":
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        dx, dy = point[0] - cx, point[1] - cy
        return (x0 + dx, y0 + dy, x1 + dx, y1 + dy)
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    ox, oy = corners[(index + 2) % 4]           # opposite corner stays put
    return (min(ox, point[0]), min(oy, point[1]),
            max(ox, point[0]), max(oy, point[1]))


class SetViewportGeometryCommand(Command):
    """Move/resize a floating viewport (grip edit). Undoable.

    A resize keeps the SCALE and keeps the model pinned to the paper
    (AutoCAD: the window reveals more model, nothing slides): the view
    height scales with the paper height, and the view center shifts by the
    paper-center displacement converted to model units.
    """

    needs_regen = True

    def __init__(self, vp, center, size, view_center, view_height,
                 name: str = "Viewport edit") -> None:
        self.name = name
        self.entity = vp
        self._new = (center, size, view_center, view_height)
        self._old = ((vp.dxf.center.x, vp.dxf.center.y),
                     (float(vp.dxf.width), float(vp.dxf.height)),
                     (vp.dxf.view_center_point.x, vp.dxf.view_center_point.y),
                     float(vp.dxf.view_height))

    def _apply(self, state, document) -> None:
        center, size, view_center, view_height = state
        self.entity.dxf.center = center
        self.entity.dxf.width, self.entity.dxf.height = size
        self.entity.dxf.view_center_point = view_center
        self.entity.dxf.view_height = view_height
        document.dirty = True

    def do(self, document) -> None:
        self._apply(self._new, document)

    def undo(self, document) -> None:
        self._apply(self._old, document)


def viewport_grip_command(vp, index: int, role: str, point):
    """The Command a finished grip drag executes, or None for a no-op."""
    x0, y0, x1, y1 = viewport_drag_rect(vp, index, role, point)
    w, h = x1 - x0, y1 - y0
    if w <= 1e-6 or h <= 1e-6:
        return None
    old_cx, old_cy = vp.dxf.center.x, vp.dxf.center.y
    new_center = ((x0 + x1) / 2.0, (y0 + y1) / 2.0)
    if role == "center":
        # move: the model travels with its window (view unchanged)
        if abs(new_center[0] - old_cx) < 1e-9 \
                and abs(new_center[1] - old_cy) < 1e-9:
            return None
        return SetViewportGeometryCommand(
            vp, new_center, (float(vp.dxf.width), float(vp.dxf.height)),
            (vp.dxf.view_center_point.x, vp.dxf.view_center_point.y),
            float(vp.dxf.view_height), name="MOVE viewport")
    # resize: keep scale, keep model pinned to paper
    scale = viewport_scale(vp)
    view_center = (vp.dxf.view_center_point.x + (new_center[0] - old_cx) / scale,
                   vp.dxf.view_center_point.y + (new_center[1] - old_cy) / scale)
    return SetViewportGeometryCommand(
        vp, new_center, (w, h), view_center, h / scale,
        name="Resize viewport")


class RemoveViewportCommand(Command):
    """ERASE of a floating viewport; undo recreates it (same view, layer)."""

    needs_regen = True

    def __init__(self, vp, layout_name: str) -> None:
        self.name = "ERASE viewport"
        self.entity = vp
        self.layout_name = layout_name

    def do(self, document) -> None:
        vp = self.entity
        self._params = dict(
            center=(vp.dxf.center.x, vp.dxf.center.y),
            size=(float(vp.dxf.width), float(vp.dxf.height)),
            view_center_point=(vp.dxf.view_center_point.x,
                               vp.dxf.view_center_point.y),
            view_height=float(vp.dxf.view_height),
            layer=vp.dxf.layer,
        )
        self.removed_handles = [vp.dxf.handle]
        psp = document.doc.layouts.get(self.layout_name)
        psp.delete_entity(vp)
        self.entity = None
        document.dirty = True

    def undo(self, document) -> None:
        psp = document.doc.layouts.get(self.layout_name)
        p = self._params
        self.entity = psp.add_viewport(
            center=p["center"], size=p["size"],
            view_center_point=p["view_center_point"],
            view_height=p["view_height"])
        self.entity.dxf.layer = p["layer"]
        document.dirty = True


# -- viewport scale (MSPACE + ZOOM nXP, the AutoCAD way) ------------------------

def visible_viewports(layout) -> list:
    """The floating viewports a CAD app shows, in stacking order.

    Mirrors the ezdxf frontend's _draw_viewports heuristic exactly (id and
    status are unreliable in real files): sort by status, drop invisible
    ones, and pop the first iff it claims to be the "main" viewport — the
    one that represents the paper view itself, never a window.
    """
    viewports = [e for e in layout if e.dxftype() == "VIEWPORT"]
    viewports.sort(key=lambda e: e.dxf.status)
    viewports = [vp for vp in viewports if vp.dxf.status > 0]
    if viewports and viewports[0].dxf.get("status", 1) == 1:
        viewports.pop(0)
    return viewports


def viewport_hit(layout, x: float, y: float):
    """Topmost visible viewport whose paper rectangle contains (x, y)."""
    hit = None
    for vp in visible_viewports(layout):        # stacking order: last on top
        cx, cy = vp.dxf.center.x, vp.dxf.center.y
        if (abs(x - cx) <= vp.dxf.width / 2.0
                and abs(y - cy) <= vp.dxf.height / 2.0):
            hit = vp
    return hit


def viewport_rect(vp) -> tuple[float, float, float, float]:
    cx, cy = vp.dxf.center.x, vp.dxf.center.y
    hw, hh = vp.dxf.width / 2.0, vp.dxf.height / 2.0
    return (cx - hw, cy - hh, cx + hw, cy + hh)


def parse_xp_factor(token: str) -> Optional[float]:
    """AutoCAD's ZOOM nXP syntax: "1/100XP", "0.5XP", "2XP" → the paper/model
    scale factor, or None when the token is not an XP scale."""
    t = token.strip().upper()
    if not t.endswith("XP"):
        return None
    body = t[:-2]
    try:
        if "/" in body:
            num, den = body.split("/", 1)
            factor = float(num) / float(den)
        else:
            factor = float(body)
    except (ValueError, ZeroDivisionError):
        return None
    return factor if math.isfinite(factor) and factor > 0.0 else None


def viewport_scale(vp) -> float:
    """paper units per model unit = dxf.height / view_height."""
    view_height = float(vp.dxf.view_height) or 1.0
    return float(vp.dxf.height) / view_height


def scale_label(factor: float) -> str:
    """Human form of a viewport scale: 0.01 → "1:100", 2.0 → "2:1"."""
    if factor <= 0.0:
        return "?"
    if factor >= 1.0:
        n = factor
        return f"{n:g}:1"
    return f"1:{1.0 / factor:g}"


class SetViewportViewCommand(Command):
    """Change what a viewport looks at (ZOOM nXP / fit). Undoable — the
    view lives in the DXF entity, so it is a document mutation."""

    needs_regen = True

    def __init__(self, vp, view_center=None, view_height=None,
                 name: str = "ZOOM XP") -> None:
        self.name = name
        self.entity = vp
        self._new_center = view_center
        self._new_height = view_height
        self._old_center = (vp.dxf.view_center_point.x,
                            vp.dxf.view_center_point.y)
        self._old_height = float(vp.dxf.view_height)

    def do(self, document) -> None:
        if self._new_center is not None:
            self.entity.dxf.view_center_point = self._new_center
        if self._new_height is not None:
            self.entity.dxf.view_height = self._new_height
        document.dirty = True

    def undo(self, document) -> None:
        self.entity.dxf.view_center_point = self._old_center
        self.entity.dxf.view_height = self._old_height
        document.dirty = True


def xp_zoom_command(vp, factor: float) -> SetViewportViewCommand:
    """ZOOM nXP: model shown at ``factor`` paper units per model unit,
    keeping the view center (AutoCAD keeps it too)."""
    return SetViewportViewCommand(
        vp, view_height=float(vp.dxf.height) / factor)


def viewport_fit_command(document, vp) -> SetViewportViewCommand:
    """ZOOM Extents inside an active viewport: fit the whole model."""
    center, view_height = model_fit_view(
        document, float(vp.dxf.width), float(vp.dxf.height))
    return SetViewportViewCommand(vp, view_center=center,
                                  view_height=view_height, name="ZOOM Extents")


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
