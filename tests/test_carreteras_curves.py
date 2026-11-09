# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Roads plugin, C2: simple horizontal curves at the PIs of a chain of
tangents -- the elements exactly, the PC and PT stations, the curve table,
the refusal when two curves do not fit -- run as the user runs them."""
from __future__ import annotations

import math

import pytest

from core import actions as core_actions
from plugins.carreteras import actions, geometry

C40, S40 = math.cos(math.radians(40.0)), math.sin(math.radians(40.0))
#: PI-1 at (100, 0), turning 40° left; 100 m of tangent each side
TANGENTS = [(0.0, 0.0), (100.0, 0.0), (100.0 + 100.0 * C40, 100.0 * S40)]


def test_the_elements_of_a_known_curve():
    c = geometry.CurveElements(40.0, 100.0)
    assert round(c.tangent, 3) == 36.397
    assert round(c.length, 3) == 69.813
    assert round(c.external, 3) == 6.418
    assert round(c.middle_ordinate, 3) == 6.031
    assert round(c.chord, 3) == 68.404
    # the textbook identities, to the last digit
    assert c.tangent == pytest.approx(100.0 * math.tan(math.radians(20.0)), abs=1e-12)
    assert c.length == pytest.approx(100.0 * math.radians(40.0), abs=1e-12)


def test_fitting_puts_pc_and_pt_on_the_tangents_with_the_right_bulge():
    verts = geometry.fit_curves(TANGENTS, [100.0])
    t = 100.0 * math.tan(math.radians(20.0))
    assert len(verts) == 4
    assert verts[1][:2] == pytest.approx((100.0 - t, 0.0), abs=1e-12)
    assert verts[1][2] == pytest.approx(math.tan(math.radians(10.0)), abs=1e-12)    # left: +
    assert verts[2][:2] == pytest.approx((100.0 + t * C40, t * S40), abs=1e-12)
    alignment = geometry.Alignment(verts)
    (pi,) = geometry.points_of_intersection(alignment)
    assert pi.point == pytest.approx((100.0, 0.0), abs=1e-9)
    assert pi.curve.delta == pytest.approx(40.0, abs=1e-12)
    assert pi.curve.radius == pytest.approx(100.0, abs=1e-9)
    assert pi.left
    assert pi.pc_station == pytest.approx(100.0 - t, abs=1e-12)
    assert pi.pt_station == pytest.approx(100.0 - t + 100.0 * math.radians(40.0), abs=1e-12)
    assert pi.station == pytest.approx(100.0, abs=1e-12)                  # PC + T
    # the middle of the curve is M below the chord... and E from the PI
    (mx, my), _ = alignment.at((pi.pc_station + pi.pt_station) / 2.0)
    assert math.hypot(mx - 100.0, my) == pytest.approx(pi.curve.external, abs=1e-9)


def test_tangents_that_cannot_hold_both_curves_are_refused():
    zigzag = [(0.0, 0.0), (50.0, 0.0), (50.0, 30.0), (100.0, 30.0)]
    with pytest.raises(geometry.TangentOverlap) as err:
        geometry.fit_curves(zigzag, [50.0, 50.0])
    assert (err.value.first, err.value.second) == (1, 2)
    assert err.value.needed == pytest.approx(100.0) and err.value.available == pytest.approx(30.0)
    # a first tangent shorter than the curve's T is refused too
    with pytest.raises(geometry.TangentOverlap):
        geometry.fit_curves([(0, 0), (10, 0), (10, 100)], [50.0])
    # exactly touching (T1 + T2 == the tangent) is a reverse curve, allowed
    verts = geometry.fit_curves(zigzag, [15.0, 15.0])
    assert len(verts) == 5                 # PT of the first is the PC of the second


# -- through the window --------------------------------------------------------------

@pytest.fixture
def win(qapp):
    from views.main_window import MainWindow

    window = MainWindow()
    window.new_document()
    yield window
    window.document.dirty = False
    window.close()


def _draw(win, points):
    win.tools._execute(core_actions.add_polyline(points))
    return [e for e in win.document.modelspace() if e.dxftype() == "LWPOLYLINE"][-1]


def _pick(win, point):
    t = win.tools
    t.on_hover(point[0], point[1], threshold_world=0.5)
    t.on_click(point[0], point[1])
    t.on_text("")


def _type(win, *answers):
    for text in answers:
        win.tools.on_text(text)


def _texts(win, layer):
    return [e.dxf.text for e in win.document.modelspace()
            if e.dxftype() == "TEXT" and e.dxf.layer == layer]


def _axes(win):
    return [e for e in win.document.modelspace() if actions.is_axis(e)]


def _fingerprint(win):
    out = []
    for e in win.document.modelspace():
        try:
            tags = tuple(e.get_xdata(actions.APPID))
        except Exception:
            tags = ()
        extra = tuple(e.get_points("xyb")) if e.dxftype() == "LWPOLYLINE" else \
            (e.dxf.text,) if e.dxftype() == "TEXT" else ()
        out.append((e.dxftype(), e.dxf.handle, e.dxf.layer, tags, extra))
    return sorted(out)


def _history(win) -> str:
    return win.command_line.history.toPlainText()


def _fit(win, tangents, *answers, pick=(50.0, 0.0)):
    win.dispatcher.submit("HCURVES")
    _pick(win, pick)
    _type(win, *answers)


ARC_MIDDLE = (100.0 - 6.4177772 * math.cos(math.radians(70.0)),
              6.4177772 * math.sin(math.radians(70.0)))       # E from the PI, inward


def test_hcurves_draws_the_axis_and_marks_pi_pc_pt(win):
    tangents = _draw(win, TANGENTS)
    before = list(tangents.get_points("xyb"))
    _fit(win, tangents, "100")
    (axis,) = _axes(win)
    assert axis is not tangents and axis.dxf.layer == "CAR-EJE"
    assert list(tangents.get_points("xyb")) == before            # the tangents stay
    bulges = [b for _x, _y, b in axis.get_points("xyb")]
    assert bulges[1] == pytest.approx(math.tan(math.radians(10.0)))
    marks = _texts(win, "CAR-CURVAS")
    assert sorted(marks) == ["PC 0+063.60", "PI-1", "PT 0+133.42"]
    assert "1 curves fitted; axis from 0+000.00 to 0+197.02." in _history(win)


def test_the_curve_table_has_every_element(win):
    tangents = _draw(win, TANGENTS)
    _fit(win, tangents, "100")
    win.dispatcher.submit("CURVETABLE")
    _pick(win, ARC_MIDDLE)
    win.tools.on_click(300.0, 200.0)
    texts = [e.dxf.text for e in win.document.modelspace()
             if e.dxftype() == "TEXT" and e.dxf.layer == "CAR-CUADROS"]
    assert texts[0] == "HORIZONTAL CURVE ELEMENTS"
    assert texts[1:13] == ["CURVE", "PI", "Δ", "DIRECTION", "R", "T", "Lc", "E", "M", "C",
                           "PC", "PT"]
    assert texts[13:] == ["C-1", "PI-1", "40°00'00\"", "Left", "100.00", "36.397", "69.813",
                          "6.418", "6.031", "68.404", "0+063.60", "0+133.42"]


def test_a_right_turn_reads_right_and_each_pi_takes_its_own_radius(win):
    # PI-1 turns 30° right, PI-2 60° left
    p1 = (200.0, 0.0)
    a = math.radians(-30.0)
    p2 = (p1[0] + 200.0 * math.cos(a), p1[1] + 200.0 * math.sin(a))
    b = math.radians(30.0)
    p3 = (p2[0] + 200.0 * math.cos(b), p2[1] + 200.0 * math.sin(b))
    tangents = _draw(win, [(0.0, 0.0), p1, p2, p3])
    _fit(win, tangents, "E", "80", "120", pick=(100.0, 0.0))
    (axis,) = _axes(win)
    rows = actions.curve_table_rows(actions.alignment_of(axis))
    assert [r[0] for r in rows] == ["C-1", "C-2"]
    assert [r[2] for r in rows] == ["30°00'00\"", "60°00'00\""]
    assert [r[3] for r in rows] == ["Right", "Left"]
    assert [r[4] for r in rows] == ["80.00", "120.00"]
    t1 = 80.0 * math.tan(math.radians(15.0))
    assert rows[0][5] == f"{t1:.3f}"
    assert rows[0][10] == f"0+{200.0 - t1:06.2f}"


def test_overlapping_tangents_are_refused_and_nothing_is_drawn(win):
    tangents = _draw(win, [(0.0, 0.0), (50.0, 0.0), (50.0, 30.0), (100.0, 30.0)])
    before = _fingerprint(win)
    _fit(win, tangents, "50", pick=(25.0, 0.0))
    assert _fingerprint(win) == before
    assert "the tangents overlap at PI-1 / PI-2 (T1 + T2 = 100.000 m > 30.000 m)" in _history(win)
    assert win.tools.tool is None                                  # the command ended


def test_a_polyline_with_arcs_is_not_a_chain_of_tangents(win):
    win.tools._execute(core_actions.add_polyline([(0, 0, 0, 0, 0.3), (50, 0, 0, 0, 0), (50, 50, 0, 0, 0)]))
    before = _fingerprint(win)
    _fit(win, None, "100", pick=(50.0, 25.0))
    assert _fingerprint(win) == before
    assert "draw the tangents only" in _history(win)


def test_the_curved_axis_is_stationed_exactly_and_reverses_with_its_marks(win):
    long_out = [(0.0, 0.0), (100.0, 0.0), (100.0 + 150.0 * C40, 150.0 * S40)]
    tangents = _draw(win, long_out)
    _fit(win, tangents, "100")
    (axis,) = _axes(win)
    t = 100.0 * math.tan(math.radians(20.0))
    win.dispatcher.submit("STATIONING")
    _pick(win, ARC_MIDDLE)
    _type(win, "20", "", "")
    labels = _texts(win, "CAR-PROGRESIVAS")
    length = 100.0 - t + 100.0 * math.radians(40.0) + 150.0 - t
    assert labels[-1] == f"0+{length:06.2f}" == "0+247.02"
    assert len(labels) == 14                       # 0..240 every 20, and the end
    # the 0+080 tick crosses the arc where the arc truly is at 80 m
    phi = (80.0 - (100.0 - t)) / 100.0
    on_arc = (100.0 - t + 100.0 * math.sin(phi), 100.0 - 100.0 * math.cos(phi))
    ticks = [e for e in win.document.modelspace()
             if e.dxftype() == "LINE" and e.dxf.layer == "CAR-ESTACAS"]
    mids = [((l.dxf.start.x + l.dxf.end.x) / 2, (l.dxf.start.y + l.dxf.end.y) / 2) for l in ticks]
    assert min(math.dist(m, on_arc) for m in mids) < 1e-9
    # reversed: the stations run back, PC and PT trade places, the turn is right
    win.dispatcher.submit("AXISREVERSE")
    _pick(win, ARC_MIDDLE)
    marks = sorted(_texts(win, "CAR-CURVAS"))
    assert marks == ["PC 0+113.60", "PI-1", "PT 0+183.42"]
    assert len(_texts(win, "CAR-PROGRESIVAS")) == 14
    assert actions.curve_table_rows(actions.alignment_of(axis))[0][3] == "Right"
    # RESTATION redraws both kinds, once
    win.dispatcher.submit("RESTATION")
    _pick(win, ARC_MIDDLE)
    assert sorted(_texts(win, "CAR-CURVAS")) == marks
    assert len(_texts(win, "CAR-PROGRESIVAS")) == 14


def test_hcurves_and_the_curve_table_undo_exactly(win):
    tangents = _draw(win, TANGENTS)
    clean = _fingerprint(win)
    _fit(win, tangents, "100")
    fitted = _fingerprint(win)
    win.dispatcher.submit("CURVETABLE")
    _pick(win, ARC_MIDDLE)
    win.tools.on_click(300.0, 200.0)
    assert _fingerprint(win) != fitted
    win.dispatcher.submit("U")
    assert _fingerprint(win) == fitted
    win.dispatcher.submit("U")
    assert _fingerprint(win) == clean
    win.dispatcher.submit("REDO")
    assert _fingerprint(win) == fitted


def _text_box(entity):
    """A rough world box of a TEXT: its alignment point, as long as its
    characters and as tall as its height, turned by its rotation."""
    from ezdxf.math import Vec2

    h = entity.dxf.height
    length = 0.8 * h * len(entity.dxf.text)
    p = Vec2(entity.dxf.align_point if entity.dxf.halign or entity.dxf.valign
             else entity.dxf.insert)
    u = Vec2.from_deg_angle(entity.dxf.rotation)
    v = u.orthogonal()
    align = entity.get_align_enum().name
    start = p - u * length if align.endswith("RIGHT") else p
    corners = [start + v * (-h / 2), start + v * (h / 2),
               start + u * length + v * (-h / 2), start + u * length + v * (h / 2)]
    xs, ys = [c.x for c in corners], [c.y for c in corners]
    return min(xs), min(ys), max(xs), max(ys)


def _overlap(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def test_pc_and_pt_labels_stay_clear_of_the_stations_on_a_right_turn(win):
    # the mirror of TANGENTS: 40° right, the outside of the curve is the
    # left of travel, where the station labels are
    right = [(x, -y) for x, y in TANGENTS]
    tangents = _draw(win, right)
    _fit(win, tangents, "100")
    win.dispatcher.submit("STATIONING")
    _pick(win, (ARC_MIDDLE[0], -ARC_MIDDLE[1]))
    _type(win, "10", "", "")
    msp = win.document.modelspace()
    marks = [e for e in msp if e.dxftype() == "TEXT"
             and e.dxf.layer == "CAR-CURVAS" and e.dxf.text[:2] in ("PC", "PT")]
    stations = [e for e in msp if e.dxftype() == "TEXT"
                and e.dxf.layer == "CAR-PROGRESIVAS"]
    assert len(marks) == 2 and stations
    for mark in marks:
        for station in stations:
            assert not _overlap(_text_box(mark), _text_box(station)), \
                (mark.dxf.text, station.dxf.text)
