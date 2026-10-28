# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Associative dimensions: a dimension follows the object it measures.

Rafael's seventh review (28:40): he stretched a part and its dimension
kept the old number. AutoCAD ties a dimension placed on object snaps to
the object (DIMASSOC = 2) and re-measures it whenever the object changes.
The dimensions here are placed the user's way -- DIMLINEAR typed, the
origins clicked on END snaps -- and the objects edited by real commands.
"""
from __future__ import annotations

import io

import ezdxf
import pytest

from core import actions
from core import dimassoc as da
from core.modify import stretch_entities


def _window(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    win.new_document()
    qapp.processEvents()
    return win


def _click(t, x, y, kinds=("END",)):
    t.osnap_on = True
    t.osnap_modes = set(kinds)
    t.on_hover(x, y, threshold_world=0.5)
    t.on_click(x, y)


def _dimlinear_on_ends(win, line_start, line_end, location):
    t = win.tools
    win.dispatcher.submit("DIMLINEAR")
    _click(t, line_start[0] + 0.1, line_start[1] + 0.1)
    _click(t, line_end[0] - 0.1, line_end[1] + 0.1)
    t.osnap_on = False
    t.on_hover(*location, threshold_world=0.5)
    t.on_click(*location)
    dims = win.document.modelspace().query("DIMENSION")
    return dims[-1]


@pytest.fixture
def win(qapp):
    window = _window(qapp)
    yield window
    window.document.dirty = False
    window.close()


def test_a_dimension_on_two_ends_follows_its_line_through_stretch_and_undo(win):
    t = win.tools
    t._execute(actions.add_line((0, 0), (40, 0)))
    line = win.document.modelspace().query("LINE")[0]
    dim = _dimlinear_on_ends(win, (0, 0), (40, 0), (20, -8))
    assoc = da.of_dimension(dim)
    assert assoc is not None, "clicked on END snaps, the dimension is not tied"
    assert [(bit, ref.osnap) for bit, ref in assoc.references()] == [
        (1, da.START), (2, da.OSNAP["END"])]
    assert assoc.dxf.handle in line.get_reactors()
    # STRETCH the line alone: the dimension re-measures with it
    t._execute(stretch_entities([line], [(35, -1, 45, 1)], 10, 0))
    assert dim.get_measurement() == pytest.approx(50)
    assert dim in t._pending_render, "the new number is not on screen"
    win._cmd_undo()
    assert dim.get_measurement() == pytest.approx(40)
    win._cmd_redo()
    assert dim.get_measurement() == pytest.approx(50)


def test_select_object_ties_both_ends(win):
    t = win.tools
    t._execute(actions.add_line((0, 0), (30, 0)))
    line = win.document.modelspace().query("LINE")[0]
    win.dispatcher.submit("DIMLINEAR")
    t.tool.on_enter()                          # <select object>
    t.on_hover(15, 0.05, threshold_world=0.5)
    t.on_click(15, 0.05)
    t.on_hover(15, 6, threshold_world=0.5)
    t.on_click(15, 6)
    dim = win.document.modelspace().query("DIMENSION")[0]
    assert da.of_dimension(dim) is not None
    t._execute(actions.move_entities([line], 0, 5))
    assert dim.dxf.defpoint2.y == pytest.approx(5)
    assert dim.get_measurement() == pytest.approx(30)


def test_typed_points_tie_nothing(win):
    t = win.tools
    t._execute(actions.add_line((0, 0), (30, 0)))
    win.dispatcher.submit("DIMLINEAR")
    for text in ("0,0", "30,0", "15,6"):
        t.on_text(text)
    dim = win.document.modelspace().query("DIMENSION")[0]
    assert da.of_dimension(dim) is None


def test_a_radius_follows_its_circle(win):
    t = win.tools
    t._execute(actions.add_circle((0, 0), 5))
    circle = win.document.modelspace().query("CIRCLE")[0]
    win.dispatcher.submit("DIMRADIUS")
    t.on_hover(5, 0, threshold_world=0.5)
    t.on_click(5, 0)
    t.on_hover(8, 3, threshold_world=0.5)
    t.on_click(8, 3)
    dim = win.document.modelspace().query("DIMENSION")[0]
    assert da.of_dimension(dim) is not None
    t._execute(actions.scale_entities([circle], (0, 0), 2.0))
    assert dim.get_measurement() == pytest.approx(10)
    t._execute(actions.move_entities([circle], 7, 0))
    assert (dim.dxf.defpoint.x, dim.dxf.defpoint.y) == pytest.approx((7, 0))


def test_moving_the_dimension_alone_unties_it_and_undo_ties_it_again(win):
    t = win.tools
    t._execute(actions.add_line((0, 0), (40, 0)))
    line = win.document.modelspace().query("LINE")[0]
    dim = _dimlinear_on_ends(win, (0, 0), (40, 0), (20, -8))
    t._execute(actions.move_entities([dim], 3, 0))
    assert da.of_dimension(dim) is None
    assert not line.get_reactors()
    win._cmd_undo()
    assert da.of_dimension(dim) is not None
    # moved together, it stays tied
    t._execute(actions.move_entities([dim, line], 0, 4))
    assert da.of_dimension(dim) is not None


def test_dimassoc_1_places_plain_dimensions(win):
    win.document.doc.header["$DIMASSOC"] = 1
    win.tools._execute(actions.add_line((0, 0), (40, 0)))
    dim = _dimlinear_on_ends(win, (0, 0), (40, 0), (20, -8))
    assert da.of_dimension(dim) is None


def test_the_tie_survives_save_and_reopen(win, tmp_path):
    from core.document import Document

    t = win.tools
    t._execute(actions.add_line((0, 0), (40, 0)))
    _dimlinear_on_ends(win, (0, 0), (40, 0), (20, -8))
    path = tmp_path / "assoc.dxf"
    win.document.save_as(path)
    again = Document.load(path)
    assert not again.doc.audit().has_errors
    dim = again.doc.modelspace().query("DIMENSION")[0]
    line = again.doc.modelspace().query("LINE")[0]
    assert isinstance(da.of_dimension(dim), da.DimAssoc)
    from core.commands import History

    history = History(again)
    history.execute(stretch_entities([line], [(-1, -1, 1, 1)], -5, 0))
    assert dim.get_measurement() == pytest.approx(45)


# A colleague's DIMASSOC, as AutoCAD writes it (read from ODA's DXF of a
# corpus plan): a polyline's segment ends (gsmarker), and a perpendicular
# dropped from a nearest point, its companion reference following it.
def _colleague_drawing():
    from core.document import Document

    document = Document(ezdxf.new("R2018", setup=True))
    msp = document.doc.modelspace()
    poly = msp.add_lwpolyline([(0, 0), (10, 0), (10, 4)])
    line = msp.add_line((0, 6), (20, 6))
    dim = msp.add_aligned_dim(p1=(10, 0), p2=(10, 4), distance=2)
    dim.render()
    dim = dim.dimension
    da.attach(document, dim, {
        1: da.Reference(da.START, [poly.dxf.handle], gsmarker=2),
        2: da.Reference(da.OSNAP["END"], [poly.dxf.handle], gsmarker=2, param=1.0)})
    perp = msp.add_aligned_dim(p1=(5, 0), p2=(5, 6), distance=-2)
    perp.render()
    perp = perp.dimension
    near = da.Reference(da.OSNAP["NEA"], [poly.dxf.handle], gsmarker=1, param=0.5)
    per = da.Reference(da.OSNAP["PER"], [line.dxf.handle], param=0.25, has_last=True)
    da.attach(document, perp, {1: near, 2: per})
    assoc = da.of_dimension(perp)
    probe = da.DimAssoc()
    probe.set_content(perp.dxf.handle, {1: near})
    companion = list(probe.tags)[4:]          # the near reference's tags
    assoc.tags = type(assoc.tags)(list(assoc.tags) + companion)
    return document, poly, line, dim, perp


def test_a_colleagues_polyline_segment_and_perpendicular_follow():
    from core.commands import History

    document, poly, line, dim, perp = _colleague_drawing()
    refs = da.of_dimension(perp).references()
    assert [(bit, r.osnap) for bit, r in refs] == [(1, 10), (2, 8), (0, 10)]
    history = History(document)

    class MoveVertex(actions.Command):
        name = "GRIP"

        def do(self, doc):
            pts = list(poly.get_points("xyb"))
            self.old = pts
            pts[2] = (10.0, 9.0, 0.0)
            poly.set_points(pts, format="xyb")

        def undo(self, doc):
            poly.set_points(self.old, format="xyb")

    history.execute(MoveVertex())
    assert dim.get_measurement() == pytest.approx(9)
    history.execute(actions.move_entities([line], 0, 3))
    # the perpendicular from the polyline's first segment to the moved line
    assert (perp.dxf.defpoint3.x, perp.dxf.defpoint3.y) == pytest.approx((5, 9))
    assert perp.get_measurement() == pytest.approx(9)


def _have_libredwg() -> bool:
    from formats.dwg_bridge import find_dxf2dwg

    return find_dxf2dwg() is not None


@pytest.mark.skipif(not _have_libredwg(), reason="LibreDWG not available")
def test_the_tie_survives_save_as_dwg_and_reopen(win, tmp_path):
    """LibreDWG kept DIMASSOC unstable: dwg2dxf never wrote one and dxf2dwg
    could not import one, so a colleague's ties were gone on opening and
    IngeCAD's on saving. The vendor patch of 2026-10-10 carries them."""
    from core.commands import History
    from formats.dwg_bridge import load_dwg

    t = win.tools
    t._execute(actions.add_line((0, 0), (40, 0)))
    _dimlinear_on_ends(win, (0, 0), (40, 0), (20, -8))
    path = tmp_path / "assoc.dwg"
    _engine, warnings = win.document.save_as(path)
    again = load_dwg(path)
    pairs = da.associations(again)
    assert len(pairs) == 1, "the tie did not survive the DWG"
    dim, assoc = pairs[0]
    assert [(bit, ref.osnap) for bit, ref in assoc.references()] == [
        (1, da.START), (2, da.OSNAP["END"])]
    line = again.doc.modelspace().query("LINE")[0]
    History(again).execute(stretch_entities([line], [(35, -1, 45, 1)], 10, 0))
    assert dim.get_measurement() == pytest.approx(50)


def _screen(win, x, y):
    from PySide6.QtCore import QPoint

    sx, sy = win.viewport.view.world_to_screen(x, y)
    return QPoint(round(sx), round(sy))


def test_a_grip_on_the_line_drags_its_dimension_along(win, qapp):
    # #90, Rafael (2026-10-12): "que las cotas se ajusten automáticamente
    # cuando se modifica una línea mediante sus pinzamientos". Grips edit
    # first and record after, and the record skipped the reactor.
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtTest import QTest

    t = win.tools
    t._execute(actions.add_line((0, 0), (40, 0)))
    line = win.document.modelspace().query("LINE")[0]
    dim = _dimlinear_on_ends(win, (0, 0), (40, 0), (20, -8))
    win.resize(1000, 700)
    qapp.processEvents()
    win.viewport.view.zoom_extents(-10, -20, 70, 20)
    t.osnap_on = False
    t.ortho_on = False
    t.selection = {line.dxf.handle}
    vp = win.viewport
    QTest.mouseClick(vp, Qt.MouseButton.LeftButton, pos=_screen(win, 40, 0))
    qapp.processEvents()
    assert t._grip_drag is not None, "the grip did not get hot"
    pos = QPointF(_screen(win, 55, 0))
    vp.mouseMoveEvent(QMouseEvent(
        QEvent.Type.MouseMove, pos, vp.mapToGlobal(pos),
        Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier))
    QTest.mouseClick(vp, Qt.MouseButton.LeftButton, pos=_screen(win, 55, 0))
    qapp.processEvents()

    length = line.dxf.end.x - line.dxf.start.x
    assert length == pytest.approx(55, abs=0.3)
    assert dim.get_measurement() == pytest.approx(length)
    assert dim in t._pending_render, "the new number is not on screen"
    assert da.of_dimension(dim) is not None, "the grip untied it"
    # one undo step takes both back, redo both forward
    win._cmd_undo()
    assert (line.dxf.end.x, dim.get_measurement()) == pytest.approx((40, 40))
    win._cmd_redo()
    assert dim.get_measurement() == pytest.approx(length)


def test_an_end_typed_in_properties_drags_its_dimension_along(win):
    t = win.tools
    t._execute(actions.add_line((0, 0), (40, 0)))
    line = win.document.modelspace().query("LINE")[0]
    dim = _dimlinear_on_ends(win, (0, 0), (40, 0), (20, -8))
    t.selection = {line.dxf.handle}
    panel = win._properties_panel
    panel.refresh()
    panel._set_comp("end", 0, 25.0)
    assert dim.get_measurement() == pytest.approx(25)
    win._cmd_undo()
    assert dim.get_measurement() == pytest.approx(40)


def test_a_script_folded_into_one_step_undoes_its_dimensions_too(win, tmp_path):
    # APPLOAD folds a script's commands into one undo step; the dimensions
    # each command re-measured stayed re-measured through that undo
    t = win.tools
    t._execute(actions.add_line((0, 0), (40, 0)))
    dim = _dimlinear_on_ends(win, (0, 0), (40, 0), (20, -8))
    script = tmp_path / "stretch.py"
    script.write_text(
        "from core.modify import stretch_entities\n"
        "line = document.modelspace().query('LINE')[0]\n"
        "for _ in range(2):\n"
        "    execute(stretch_entities([line], [(35, -1, 65, 1)], 10, 0))\n")
    win._on_command_submitted(f"APPLOAD {script}")
    assert dim.get_measurement() == pytest.approx(60)
    win._cmd_undo()
    assert dim.get_measurement() == pytest.approx(40)
    win._cmd_redo()
    assert dim.get_measurement() == pytest.approx(60)
