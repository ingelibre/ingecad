# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Roads, the French practice: clothoids (A² = R·L) between the straights
and the circle, kept exactly by the axis; the design standards as data
(ARP, ICTAAL, ICTAVRU) and ROADCHECK against them; the table of elements;
angles in grads (gisements)."""
from __future__ import annotations

import math

import pytest

from core.commands import History
from core.document import Document
from plugins.carreteras import actions, geometry, norms
from tools.base import ToolContext

C40, S40 = math.cos(math.radians(40.0)), math.sin(math.radians(40.0))
#: PI-1 at (400, 0), turning 40° left; 400 m of tangent each side
TANGENTS = [(0.0, 0.0), (400.0, 0.0), (400.0 + 400.0 * C40, 400.0 * S40)]


# -- the clothoid ------------------------------------------------------------------------

def test_a_clothoid_matches_its_series_and_a_squared_is_r_l():
    e = geometry.Element((0.0, 0.0), 0.0, 50.0, 0.0, 1.0 / 200.0)
    (x, y), angle = e.at(50.0)
    th = 50.0 / 400.0
    xs = 50.0 * (1 - th ** 2 / 10 + th ** 4 / 216 - th ** 6 / 9360)
    ys = 50.0 * (th / 3 - th ** 3 / 42 + th ** 5 / 1320)
    assert (x, y) == pytest.approx((xs, ys), abs=1e-7)
    assert angle == pytest.approx(math.degrees(th), abs=1e-12)
    assert e.parameter == pytest.approx(100.0, abs=1e-12)          # A² = 200 x 50
    assert e.kind == "clothoid" and e.radius == pytest.approx(200.0)


def test_an_element_survives_its_xdata_string_and_walks_back():
    e = geometry.Element((12.5, -3.0), 33.0, 80.0, 1.0 / 300.0, 1.0 / 150.0)
    again = geometry.Element.decode(e.encode())
    assert again.end == pytest.approx(e.end, abs=1e-6)
    back = e.reversed()
    assert back.end == pytest.approx(e.start, abs=1e-9)
    assert back.at(30.0)[0] == pytest.approx(e.at(50.0)[0], abs=1e-9)


def test_the_spiral_curve_elements_and_the_axis_land_on_both_tangents():
    sc = geometry.SpiralCurve(40.0, 300.0, 80.0)
    assert sc.parameter == pytest.approx(math.sqrt(300.0 * 80.0))
    assert sc.theta_s == pytest.approx(80.0 / 600.0)
    assert sc.shift == pytest.approx(80.0 ** 2 / (24 * 300.0), rel=2e-3)    # p ≈ L²/24R
    assert sc.k == pytest.approx(40.0, rel=1e-3)                            # k ≈ L/2
    elements = geometry.fit_spiral_curves(TANGENTS, [300.0], [80.0])
    assert [e.kind for e in elements] == ["line", "clothoid", "arc", "clothoid", "line"]
    ts, st = elements[1].start, elements[3].end
    t = sc.tangent
    assert ts == pytest.approx((400.0 - t, 0.0), abs=1e-9)
    assert st == pytest.approx((400.0 + t * C40, t * S40), abs=1e-7)
    assert elements[3].end_angle == pytest.approx(40.0, abs=1e-9)
    for a, b in zip(elements, elements[1:]):                      # continuous, tangent
        assert a.end == pytest.approx(b.start, abs=1e-7)
        assert a.end_angle == pytest.approx(b.start_angle, abs=1e-9)
    # no clothoid: the simple circle of fit_curves
    assert geometry.SpiralCurve(40.0, 300.0, 0.0).tangent == pytest.approx(
        geometry.CurveElements(40.0, 300.0).tangent)


def test_clothoids_that_turn_more_than_the_pi_are_refused():
    with pytest.raises(geometry.SpiralTooLong):
        geometry.fit_spiral_curves(TANGENTS, [100.0], [80.0])        # 2 x 80/200 rad > 40°


def test_the_pis_of_a_spiral_axis_name_ts_sc_cs_st():
    alignment = geometry.ElementAlignment(geometry.fit_spiral_curves(TANGENTS, [300.0], [80.0]))
    (pi,) = geometry.points_of_intersection(alignment)
    assert pi.spiral and pi.point == pytest.approx((400.0, 0.0), abs=1e-6)
    assert pi.curve.delta == pytest.approx(40.0) and pi.curve.radius == pytest.approx(300.0)
    assert pi.sc_station - pi.pc_station == pytest.approx(80.0)
    assert pi.pt_station - pi.cs_station == pytest.approx(80.0)
    assert pi.station - pi.pc_station == pytest.approx(pi.curve.tangent, abs=1e-6)


# -- in the drawing -----------------------------------------------------------------------

def _document():
    document = Document.new()
    return document, History(document)


def _fit(radius=300.0, ls=80.0):
    document, history = _document()
    tangents = document.doc.modelspace().add_lwpolyline(TANGENTS)
    command = actions.fit_axis(document, tangents, [radius], spirals=[ls])
    history.execute(command)
    return document, history, command.axis_command.entity


def test_the_axis_keeps_its_clothoids_exactly_and_draws_them_by_chords():
    document, history, axis = _fit()
    alignment = actions.alignment_of(axis)
    assert isinstance(alignment, geometry.ElementAlignment)
    assert [e.kind for e in alignment.elements] == ["line", "clothoid", "arc", "clothoid", "line"]
    verts = actions.polyline_vertices(axis)
    assert len(verts) > 10                                  # the clothoids, as chords
    # every chord vertex lies on the exact clothoid
    spiral = alignment.elements[1]
    for x, y, _b in verts[2:6]:
        d = min(math.dist((x, y), spiral.at(spiral.length * k / 400)[0]) for k in range(401))
        assert d < 0.15
    # the marks: TS, SC, CS, ST and the PI
    marks = sorted(e.dxf.text.split(" ")[0] for e in document.doc.modelspace().query("TEXT")
                   if e.dxf.layer == "CAR-CURVAS")
    assert marks == ["CS", "PI-1", "SC", "ST", "TS"]
    history.undo()
    assert not [e for e in document.doc.modelspace() if actions.is_axis(e)]


def test_reversing_keeps_the_elements_and_a_grip_edit_falls_back_to_the_polyline():
    document, history, axis = _fit()
    history.execute(actions.reverse_axis(document, axis))
    reverse = actions.alignment_of(axis)
    assert isinstance(reverse, geometry.ElementAlignment)
    assert [e.kind for e in reverse.elements] == ["line", "clothoid", "arc", "clothoid", "line"]
    assert reverse.elements[0].start == pytest.approx(TANGENTS[-1], abs=1e-6)
    # an edit after the fact: the elements no longer describe the polyline
    points = list(axis.get_points("xyb"))
    points[-1] = (points[-1][0] + 5.0, points[-1][1], points[-1][2])
    axis.set_points(points, format="xyb")
    assert actions.stored_elements(axis) is None
    assert not isinstance(actions.alignment_of(axis), geometry.ElementAlignment)


def test_curve_and_element_tables_with_clothoids_and_in_grads():
    _document_, _history, axis = _fit()
    alignment = actions.alignment_of(axis)
    (row,) = actions.curve_table_rows(alignment, "grad")
    assert row[2] == "44.4444 gr" and row[4] == "300.00" and row[5] == "80.00"
    assert row[6] == f"{math.sqrt(300 * 80):.2f}"
    rows = actions.element_table_rows(alignment, "grad")
    assert [r[1] for r in rows] == ["Straight", "Clothoid", "Arc", "Clothoid", "Straight"]
    assert rows[1][6] == "∞ → 300.00" and rows[3][6] == "300.00 → ∞"
    assert rows[0][8] == "100.0000"                       # due east: gisement 100 gr
    assert rows[4][8] == f"{(90 - 40) * 400 / 360:.4f}"
    assert actions.axis_table_rows(alignment, "grad")[0][4] == "100.0000"
    assert len(actions.axis_table_rows(alignment, "deg")[0]) == 7


def test_gisement_is_from_north_clockwise_in_grads():
    assert actions.gisement(90.0) == pytest.approx(0.0)        # north
    assert actions.gisement(0.0) == pytest.approx(100.0)       # east
    assert actions.gisement(-90.0) == pytest.approx(200.0)     # south
    assert actions.gisement(180.0) == pytest.approx(300.0)     # west
    assert actions.format_angle(90.0, "grad") == "100.0000 gr"


# -- the standards ----------------------------------------------------------------------------

def test_the_bundled_standards_load_and_name_their_sources():
    found = norms.available()
    assert {"ARP1994", "ARP2022", "ICTAAL2015", "ICTAVRU2009"} <= set(found)
    for norm in found.values():
        assert norm.source and norm.categories
    assert found["ARP2022"].verified is False             # read from a secondary source
    arp = found["ARP1994"]
    assert arp.category("r80") == {"rm": 240, "rdm": 650, "rnd": 900, "crest_min": 3000,
                                   "sag_min": 2200, "grade_max": 6}
    assert found["ICTAAL2015"].category("L1")["rm"] == 600
    assert found["ICTAVRU2009"].category("A100")["rnd"] == 800


def test_arp_superelevation_is_linear_in_one_over_r():
    arp = norms.find("ARP1994")
    cat = arp.category("R80")
    assert norms.superelevation(arp, cat, 240.0) == pytest.approx(7.0)
    assert norms.superelevation(arp, cat, 650.0) == pytest.approx(2.5)
    assert norms.superelevation(arp, cat, 800.0) == pytest.approx(2.5)
    assert norms.superelevation(arp, cat, 900.0) == pytest.approx(-2.5)       # crown kept
    # ARP annex 1, R80/T80: d = -0.13 + 1712.2 / R between 240 and 650 m
    for r in (300.0, 400.0, 500.0):
        assert norms.superelevation(arp, cat, r) == pytest.approx(-0.13 + 1712.2 / r, abs=0.01)


def test_recommended_clothoid_lengths():
    arp = norms.find("ARP1994")
    cat = arp.category("R80")
    assert norms.clothoid_length(arp, cat, 240.0, 2) == pytest.approx(6 * 240 ** 0.4)
    assert norms.clothoid_length(arp, cat, 2000.0, 2) == pytest.approx(67.0)      # capped
    assert norms.clothoid_length(arp, cat, 240.0, 4) == pytest.approx(12 * 240 ** 0.4)
    ictaal = norms.find("ICTAAL2015")
    assert norms.clothoid_needed_below(ictaal, ictaal.category("L2")) == pytest.approx(975.0)
    vru = norms.find("ICTAVRU2009")
    a80 = vru.category("A80")
    # 5 % at Rm: from the -2.5 % crown, 14 x 7.5 = 105 m > 240 / 9
    assert norms.clothoid_length(vru, a80, 240.0) == pytest.approx(105.0)


def test_roadcheck_finds_a_tight_curve_without_clothoids():
    document, history = _document()
    tangents = document.doc.modelspace().add_lwpolyline(TANGENTS)
    history.execute(actions.fit_axis(document, tangents, [200.0]))
    axis = [e for e in document.doc.modelspace() if actions.is_axis(e)][0]
    report = norms.check(actions.alignment_of(axis), norms.find("ARP1994"), "R80", 2)
    texts = [f.text for f in report.findings]
    assert report.errors == 1 and "below the minimum radius Rm = 240 m" in texts[0]
    assert any("needs clothoids (R < 900 m)" in t for t in texts)
    ok = norms.check(actions.alignment_of(_fit(300.0, 60.0)[2]), norms.find("ARP1994"), "R80", 2)
    assert ok.errors == 0 and ok.warnings == 0
    assert any("superelevation" in f.text for f in ok.findings)


def test_chaining_rules():
    pts = [(0.0, 0.0), (800.0, 0.0), (1400.0, 600.0), (2400.0, 600.0)]
    alignment = geometry.ElementAlignment(geometry.fit_spiral_curves(pts, [600.0, 250.0], [60.0, 50.0]))
    arp = norms.check(alignment, norms.find("ARP1994"), "R80")
    assert any("ratio outside 0.67 to 1.50" in f.text for f in arp.findings)
    ictaal = norms.check(alignment, norms.find("ICTAAL2015"), "L2-relief-difficile")
    assert any("R1 = 600 m > 1.5 x R2 = 250 m" in f.text for f in ictaal.findings)


class _Services:
    def __init__(self, document):
        self.document = document


def test_roadcheck_tool_asks_standard_category_and_lanes():
    from plugins.carreteras.tools import RoadCheckTool

    document, history, axis = _fit(300.0, 60.0)
    echoed, prompts, done = [], [], []
    ctx = ToolContext(execute=history.execute, prompt=prompts.append, echo=echoed.append,
                      finish=lambda: done.append(True), undo_last=history.undo,
                      services=_Services(document))
    tool = RoadCheckTool(ctx)
    tool.start()
    tool.on_selection([axis])
    assert prompts[-1].startswith("Design standard (") and "ARP1994" in prompts[-1]
    tool.on_option("arp1994")
    assert prompts[-1].startswith("Category (R60, R80, T80, T100)")
    tool.on_option("t100")
    assert prompts[-1] == "Lanes in the cross-section (2, 3 or 4) <2>:"
    tool.on_enter()
    assert done
    assert echoed[0] == "ARP - Aménagement des routes principales (Sétra, 1994), category T100."
    assert any(line.startswith("ERROR C-1: R = 300.00 m: below the minimum radius Rm = 425 m")
               for line in echoed)
    assert echoed[-1].startswith("1 error(s)")


def test_the_unverified_standard_says_so():
    from plugins.carreteras.tools import RoadCheckTool

    document, history, axis = _fit(300.0, 60.0)
    echoed = []
    ctx = ToolContext(execute=history.execute, prompt=lambda *_: None, echo=echoed.append,
                      finish=lambda: None, undo_last=history.undo, services=_Services(document))
    tool = RoadCheckTool(ctx)
    tool.start()
    tool.on_selection([axis])
    tool.on_option("ARP2022")
    tool.on_option("R1")
    tool.on_option("2")
    assert echoed[1].startswith("Values to check against the guide:")
