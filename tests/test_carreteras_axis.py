# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Roads plugin, C1: the axis and its stationing, the way the user runs it
-- typed commands, the polyline picked with the mouse, the prompts answered
at the command line -- and the axis table."""
from __future__ import annotations

import math

import pytest

from core import actions as core_actions
from core.surveying import format_station
from plugins.carreteras import actions, geometry

APPID = "INGECAD_CARRETERAS"


# -- pure geometry ---------------------------------------------------------------------

def test_station_format_is_km_plus_metres():
    assert format_station(20.0, 0) == "0+020"
    assert format_station(1000.0, 0) == "1+000"
    assert format_station(1250.5) == "1+250.50"
    assert format_station(999.996) == "1+000.00"
    assert geometry.parse_station("1+250.50") == 1250.5
    assert geometry.parse_station("1+250,5") == 1250.5
    assert geometry.parse_station("250") == 250.0
    with pytest.raises(ValueError):
        geometry.parse_station("1+x")


def test_an_arc_is_stationed_by_its_true_length():
    # a half circle of radius 10 (bulge 1), then 20 m straight on
    alignment = geometry.Alignment([(0, 0, 1.0), (20, 0, 0.0), (20, 20, 0.0)])
    assert alignment.length == pytest.approx(10 * math.pi + 20.0, abs=1e-12)
    # a quarter of the way round the arc: (10 - 10 cos 45°... ) exactly
    (x, y), angle = alignment.at(10 * math.pi / 4)
    assert (x, y) == pytest.approx((10 - 10 * math.cos(math.pi / 4), -10 * math.sin(math.pi / 4)),
                                   abs=1e-12)
    assert angle == pytest.approx(-45.0)
    # the end of the arc heads north, as the straight after it does
    assert alignment.at(10 * math.pi)[1] == pytest.approx(90.0)
    # reversed: same length, the arc turns the other way
    back = alignment.reversed()
    assert back.length == pytest.approx(alignment.length, abs=1e-12)
    assert back.at(20.0)[0] == pytest.approx((20.0, 0.0), abs=1e-12)
    assert back.segments[-1].bulge == -1.0


def test_ticks_every_interval_plus_the_odd_start_and_end():
    alignment = geometry.Alignment([(0, 0), (145, 0)], start_station=13.0)
    ticks = geometry.station_ticks(alignment, 20.0)
    assert [t.station for t in ticks] == [13.0, 20, 40, 60, 80, 100, 120, 140, 158.0]
    assert [t.regular for t in ticks] == [False] + [True] * 7 + [False]
    assert ticks[1].point == pytest.approx((7.0, 0.0))


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
    """A polyline drawn as the user draws it: through a Command."""
    win.tools._execute(core_actions.add_polyline(points))
    return [e for e in win.document.modelspace() if e.dxftype() == "LWPOLYLINE"][-1]


def _pick(win, point):
    """Hover and click on the polyline, then Enter to end the selection."""
    t = win.tools
    t.on_hover(point[0], point[1], threshold_world=0.5)
    t.on_click(point[0], point[1])
    t.on_text("")


def _type(win, *answers):
    for text in answers:
        win.tools.on_text(text)


def _texts(win, layer):
    return [e for e in win.document.modelspace()
            if e.dxftype() == "TEXT" and e.dxf.layer == layer]


def _lines(win, layer):
    return [e for e in win.document.modelspace()
            if e.dxftype() == "LINE" and e.dxf.layer == layer]


def _fingerprint(win):
    out = []
    for e in win.document.modelspace():
        tags = []
        for app in (APPID, "INGECAD"):
            try:
                tags.append((app, tuple(e.get_xdata(app))))
            except Exception:
                pass
        extra = tuple(e.get_points("xyb")) if e.dxftype() == "LWPOLYLINE" else \
            (e.dxf.text,) if e.dxftype() == "TEXT" else ()
        out.append((e.dxftype(), e.dxf.handle, e.dxf.layer, tuple(tags), extra))
    return sorted(out)


L_AXIS = [(1000.0, 2000.0), (1100.0, 2000.0), (1100.0, 2045.0)]      # 145 m


def _station(win, entity, *answers, pick=(1050.0, 2000.0)):
    win.dispatcher.submit("STATIONING")
    _pick(win, pick)
    _type(win, *answers)


def test_the_plugin_is_bundled_on_with_its_menu_and_no_toolbar(win):
    assert win.plugins.is_active("carreteras")
    assert "Roads" in [a.text() for a in win._menu_bar.actions()]
    for name in ("ROADAXIS", "STATIONING", "RESTATION", "AXISREVERSE", "AXISTABLE",
                 "HCURVES", "CURVETABLE"):
        assert name in win.dispatcher._commands
    assert win.plugins.has_toolbar("carreteras")
    assert "plugin_carreteras_toolbar" not in [
        t.objectName() for t in win.findChildren(type(win._draw_toolbar))]


def test_turning_roads_off_leaves_no_trace(win):
    before = set(win.dispatcher._commands)
    win.plugins.deactivate("carreteras")
    try:
        assert "Roads" not in [a.text() for a in win._menu_bar.actions()]
        gone = before - set(win.dispatcher._commands)
        assert {"ROADAXIS", "STATIONING", "RESTATION", "AXISREVERSE", "AXISTABLE",
                "HCURVES", "CURVETABLE"} <= gone
        assert all(name.startswith(("ROAD", "STATION", "RESTATION", "AXIS", "HCURVE", "CURVE",
                                    "VCURVE", "SUPERELEV", "MASSHAUL"))
                   for name in gone), gone
    finally:
        assert win.plugins.activate("carreteras")
    assert set(win.dispatcher._commands) == before


def test_stationing_a_known_length_draws_every_tick_and_label(win):
    axis = _draw(win, L_AXIS)
    _station(win, axis, "20", "", "")
    labels = [t.dxf.text for t in _texts(win, "CAR-PROGRESIVAS")]
    assert labels == ["0+000", "0+020", "0+040", "0+060", "0+080", "0+100",
                      "0+120", "0+140", "0+145.00"]
    ticks = _lines(win, "CAR-ESTACAS")
    assert len(ticks) == 9
    # a tick across the axis, 4 m long, centred on it; the label on the left
    tick20 = next(l for l in ticks if l.dxf.start.x == pytest.approx(1020.0))
    assert {round(tick20.dxf.start.y, 9), round(tick20.dxf.end.y, 9)} == {1998.0, 2002.0}
    assert tick20.dxf.end.x == pytest.approx(1020.0)
    t20 = _texts(win, "CAR-PROGRESIVAS")[1]
    assert t20.dxf.align_point.x == pytest.approx(1020.0)
    assert t20.dxf.align_point.y > 2002.0                  # left of travel: north
    assert t20.dxf.rotation == pytest.approx(90.0)
    # on the second leg, heading north, the left is west
    t140 = _texts(win, "CAR-PROGRESIVAS")[7]
    assert t140.dxf.align_point.x < 1098.0
    assert t140.dxf.align_point.y == pytest.approx(2040.0)
    # the axis remembers it all, under its own APPID
    params = actions.axis_params(axis)
    assert params == actions.AxisParams(0.0, False, 20.0, 4.0, 2.0)
    assert axis.dxf.layer == "CAR-EJE"
    assert not axis.has_xdata("INGECAD")
    assert APPID in win.document.doc.appids


def test_full_kilometres_stand_out(win):
    axis = _draw(win, [(0.0, 0.0), (2100.0, 0.0)])
    _station(win, axis, "100", "", "", pick=(500.0, 0.0))
    texts = {t.dxf.text: t for t in _texts(win, "CAR-PROGRESIVAS")}
    assert texts["1+000"].dxf.height == pytest.approx(3.0)
    assert texts["2+000"].dxf.height == pytest.approx(3.0)
    assert texts["1+100"].dxf.height == pytest.approx(2.0)
    km_tick = next(l for l in _lines(win, "CAR-ESTACAS") if l.dxf.start.x == pytest.approx(1000.0))
    assert abs(km_tick.dxf.end.y - km_tick.dxf.start.y) == pytest.approx(6.0)


def test_a_typed_start_station_is_a_station_not_a_sum(win):
    axis = _draw(win, L_AXIS)
    win.dispatcher.submit("ROADAXIS")
    _pick(win, (1050.0, 2000.0))
    _type(win, "1+250.50")
    assert actions.axis_params(axis).start == 1250.5
    _station(win, axis, "", "", "")
    labels = [t.dxf.text for t in _texts(win, "CAR-PROGRESIVAS")]
    assert labels[:3] == ["1+250.50", "1+260", "1+280"]
    assert labels[-1] == "1+395.50"


def test_reversing_runs_the_stations_from_the_other_end(win):
    axis = _draw(win, L_AXIS)
    _station(win, axis, "20", "", "")
    old = _texts(win, "CAR-PROGRESIVAS")
    win.dispatcher.submit("AXISREVERSE")
    _pick(win, (1050.0, 2000.0))
    alive = {e.dxf.handle for e in win.document.modelspace()}
    assert not any(t.dxf.handle in alive for t in old), "the old labels stayed"
    texts = _texts(win, "CAR-PROGRESIVAS")
    assert len(texts) == 9 and len(_lines(win, "CAR-ESTACAS")) == 9
    by_text = {t.dxf.text: t for t in texts}
    zero, end = by_text["0+000"], by_text["0+145.00"]
    # 0+000 is now at the far end of the polyline, heading south
    assert zero.dxf.align_point.y == pytest.approx(2045.0)
    assert end.dxf.align_point.x == pytest.approx(1000.0, abs=3.0)
    assert by_text["0+020"].dxf.align_point.y == pytest.approx(2025.0)
    assert actions.axis_params(axis).reverse is True


def test_stationing_again_replaces_and_restation_follows_an_edit(win):
    axis = _draw(win, L_AXIS)
    _station(win, axis, "20", "", "")
    _station(win, axis, "", "", "")                     # same settings: same count
    assert len(_texts(win, "CAR-PROGRESIVAS")) == 9
    _station(win, axis, "50", "", "")
    assert [t.dxf.text for t in _texts(win, "CAR-PROGRESIVAS")] == \
        ["0+000", "0+050", "0+100", "0+145.00"]
    assert len(_lines(win, "CAR-ESTACAS")) == 4
    # a grip edit stretches the last leg to 100 m; RESTATION catches up
    pts = list(axis.get_points("xyseb"))
    pts[-1] = (1100.0, 2100.0, 0, 0, 0)
    axis.set_points(pts, format="xyseb")
    win.dispatcher.submit("RESTATION")
    _pick(win, (1050.0, 2000.0))
    assert [t.dxf.text for t in _texts(win, "CAR-PROGRESIVAS")] == \
        ["0+000", "0+050", "0+100", "0+150", "0+200"]


def test_every_command_undoes_exactly(win):
    axis = _draw(win, L_AXIS)
    clean = _fingerprint(win)
    win.dispatcher.submit("ROADAXIS")
    _pick(win, (1050.0, 2000.0))
    _type(win, "R", "0+100")
    assert actions.axis_params(axis) == actions.AxisParams(100.0, True)
    defined = _fingerprint(win)
    assert defined != clean
    _station(win, axis, "20", "", "")
    stationed = _fingerprint(win)
    _station(win, axis, "25", "3", "1.5")
    assert _fingerprint(win) != stationed
    win.dispatcher.submit("AXISREVERSE")
    _pick(win, (1050.0, 2000.0))
    win.dispatcher.submit("AXISTABLE")
    _pick(win, (1050.0, 2000.0))
    win.tools.on_click(1200.0, 2100.0)
    assert _texts(win, "CAR-CUADROS")
    undo = lambda: win.dispatcher.submit("U")            # noqa: E731
    undo()                                               # the table
    undo()                                               # the reversal
    undo()                                               # the second stationing
    assert _fingerprint(win) == stationed
    undo()
    assert _fingerprint(win) == defined
    undo()
    assert _fingerprint(win) == clean
    assert not axis.has_xdata(APPID) and axis.dxf.layer == "0"


def test_the_axis_table_lists_pis_stations_bearings_and_distances(win):
    axis = _draw(win, L_AXIS)
    win.dispatcher.submit("AXISTABLE")
    _pick(win, (1050.0, 2000.0))
    win.tools.on_click(1200.0, 2100.0)
    texts = [t.dxf.text for t in _texts(win, "CAR-CUADROS")]
    assert texts[0] == "AXIS TABLE"
    rows = actions.axis_table_rows(actions.alignment_of(axis))
    assert rows == [
        ["START", "0+000.00", "1000.000", "2000.000", "N 90°00'00\" E", "90°00'00\"", "100.000"],
        ["PI-1", "0+100.00", "1100.000", "2000.000", "N 0°00'00\" E", "0°00'00\"", "45.000"],
        ["END", "0+145.00", "1100.000", "2045.000", "", "", ""],
    ]
    for cell in ("PI-1", "0+100.00", "1100.000", "N 0°00'00\" E", "45.000"):
        assert cell in texts


def test_the_axis_survives_a_save_and_a_reload(win, tmp_path):
    from core.document import Document

    axis = _draw(win, L_AXIS)
    _station(win, axis, "20", "", "")
    path = tmp_path / "eje.dxf"
    win.document.save_as(path)
    again = Document.load(path)
    axes = [e for e in again.doc.modelspace() if actions.is_axis(e)]
    assert len(axes) == 1
    assert actions.axis_params(axes[0]) == actions.AxisParams()
    assert len(actions.annotations_of(again, axes[0])) == 18
