# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""DIMANGULAR as AutoCAD draws it: the whole dimension follows the cursor,
straight polyline segments are lines, and an extension line runs from the
tip of a line that stops short of the dimension arc.

GeoCad Yaguarete (Fernando Bellocchio's plugin) had to add all three.
"""
from __future__ import annotations

import math

import pytest

from core import actions


@pytest.fixture
def win(qapp):
    from views.main_window import MainWindow

    window = MainWindow()
    window.show()
    window.new_document()
    qapp.processEvents()
    yield window
    window.document.dirty = False
    window.close()


def _click(t, x, y):
    t.on_hover(x, y, threshold_world=0.3)
    t.on_click(x, y)


def test_two_polyline_segments_and_the_live_dimension(win):
    t = win.tools
    t.osnap_on = False
    t._execute(actions.AddEntityCommand(
        "LWPOLYLINE", lambda msp: msp.add_lwpolyline([(10, 0), (0, 0), (0, 10)])))
    win.dispatcher.submit("DIMANGULAR")
    _click(t, 5, 0)                      # first segment of the lot
    _click(t, 0, 5)                      # second segment
    assert t.tool._mode == "locate", "polyline segments were refused"
    t.on_hover(4, 4, threshold_world=0.3)
    assert win.viewport._preview_scene is not None, "no live dimension"
    _click(t, 4, 4)
    [dim] = win.document.modelspace().query("DIMENSION")
    assert dim.get_measurement() == pytest.approx(90)     # degrees


def test_a_line_short_of_the_arc_gets_its_extension_from_its_tip():
    # two lines 3 long from the vertex; the arc placed at radius 8
    vertex, p1, p2 = actions.angular_from_lines(
        ((0, 0), (3, 0)), ((0, 0), (0, 3)), (8 / math.sqrt(2), 8 / math.sqrt(2)))
    assert vertex == pytest.approx((0, 0))
    assert sorted([tuple(round(v, 6) for v in p1), tuple(round(v, 6) for v in p2)]) \
        == [(0, 3), (3, 0)], "the defpoints are not the tips"
    # lines longer than the arc: the defpoints sit on the arc (no extension)
    _v, q1, q2 = actions.angular_from_lines(
        ((0, 0), (20, 0)), ((0, 0), (0, 20)), (8 / math.sqrt(2), 8 / math.sqrt(2)))
    assert math.dist(q1, (0, 0)) == pytest.approx(8)
    assert math.dist(q2, (0, 0)) == pytest.approx(8)


@pytest.mark.parametrize("dimadec,expected", [
    (0, "46°"), (1, "45°30'"), (2, "45°30'"), (3, "45°30'30\""),
    (4, "45°30'30\""), (5, "45°30'30.0\""), (7, "45°30'29.999\""),
    (8, "45°30'29.9988\""),
])
def test_degrees_minutes_seconds_as_autocad_writes_them(dimadec, expected):
    """ezdxf printed 7.00000" for 7.5 seconds at DIMADEC 5 (GeoCad
    Yaguarete had to patch it). No padding: AutoCAD's own text in a
    colleague's plan reads 60°0'0" at DIMADEC 3."""
    from core.ezdxf_patches import dms_text

    assert dms_text(45.508333, dimadec) == expected


def test_seconds_never_round_up_to_sixty():
    from core.ezdxf_patches import dms_text

    assert dms_text(12.99999, 4) == "13°0'0\""
    assert dms_text(12.99999, 6) == "12°59'59.96\""
    assert dms_text(60.0, 3) == "60°0'0\"", "AutoCAD's own text"


def test_a_dms_angular_dimension_draws_that_text():
    import ezdxf

    from core import ezdxf_patches

    ezdxf_patches.apply()
    doc = ezdxf.new("R2018", setup=True)
    style = doc.dimstyles.get("Standard")
    style.dxf.dimaunit = 1
    style.dxf.dimadec = 4
    msp = doc.modelspace()
    # the arc inside the 30.5 degree sweep: on the other side it is 329.5
    dim = msp.add_angular_dim_3p(base=(5 * math.cos(math.radians(15)),
                                       5 * math.sin(math.radians(15))),
                                 center=(0, 0), p1=(10, 0),
                                 p2=(10 * math.cos(math.radians(30.5)),
                                     10 * math.sin(math.radians(30.5))),
                                 dimstyle="Standard")
    dim.render()
    texts = [e.text if e.dxftype() == "MTEXT" else e.dxf.text
             for e in dim.dimension.get_geometry_block()
             if e.dxftype() in ("MTEXT", "TEXT")]
    assert any("30°30'" in t for t in texts), texts


def test_the_style_editor_offers_autocad_s_precision_list(qapp):
    from core.document import Document
    from core import styles as style_ops
    from views.dimstyle_dialog import DimStyleEditorDialog

    doc = Document.new()
    style_ops.install_default_styles(doc)
    attribs = style_ops.dim_style_attribs(doc, "ISO-25")
    attribs.update(dimaunit=1, dimadec=3)
    dlg = DimStyleEditorDialog(None, "t", attribs, ["Standard"])
    try:
        rows = [dlg.dimadec.itemText(i) for i in range(dlg.dimadec.count())]
        assert rows[:3] == ["0°", "0°00'", "0°00'00\""]
        assert dlg.result_props()["dimadec"] == 3, "an unshown value changed"
        dlg.dimadec.setCurrentIndex(rows.index("0°00'00.0\""))
        assert dlg.result_props()["dimadec"] == 5
        dlg.dimaunit.setCurrentIndex(dlg.dimaunit.findData(0))
        assert dlg.dimadec.itemText(2) == "0.00°"
        assert [dlg.dimdec.itemText(i) for i in range(3)] == ["0", "0.0", "0.00"]
    finally:
        dlg.deleteLater()
