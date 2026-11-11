# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Roads, C3 and C4 and the cross-section: parabolic vertical curves on
Topography's grade line (and the volumes that follow them), ROADCHECK on
grades and vertical radii, the superelevation table, and the mass-haul
diagram (Brückner / Lalanne)."""
from __future__ import annotations

import math

import pytest

from core.commands import History
from core.document import Document
from plugins.carreteras import actions, norms, vertical
from plugins.topografia import actions as topo
from plugins.topografia import profile
from plugins.topografia.tin import build_tin
from tools.base import ToolContext


# -- the parabola --------------------------------------------------------------------------

def test_a_crest_and_a_sag_have_the_textbook_elements():
    v = vertical.VerticalAlignment([(0, 100), (300, 112), (700, 100), (1000, 106)], [4000, 6000])
    crest, sag = v.curves()
    assert crest.crest and not sag.crest
    assert crest.tangent == pytest.approx(4000 * 0.07 / 2)          # T = R |Δp| / 2
    assert crest.flech == pytest.approx(140 ** 2 / 8000)            # f = T² / 2R
    assert v.z_at(300) == pytest.approx(112 - crest.flech)
    assert sag.extremum == pytest.approx((700 - 150 + 0.03 * 6000, sag.z_at(730)))
    # tangent to both grades at its ends
    assert crest.slope_at(crest.start) == pytest.approx(0.04)
    assert crest.slope_at(crest.end) == pytest.approx(-0.03)
    assert v.z_at(crest.start) == pytest.approx(112 - 0.04 * 140)
    # the chords of the sample stay within s²/8R of the curve
    pts = v.sample(1.0)
    for (s0, z0), (s1, z1) in zip(pts, pts[1:]):
        mid = (s0 + s1) / 2
        assert abs((z0 + z1) / 2 - v.z_at(mid)) < 0.0002
    again = vertical.VerticalAlignment.decode(v.encode())
    assert again.sommets == v.sommets and again.radii == v.radii


def test_curves_that_do_not_fit_are_refused():
    with pytest.raises(vertical.CurveOverlap):
        vertical.VerticalAlignment([(0, 100), (100, 110), (200, 100)], [10000])


# -- on Topography's profile ------------------------------------------------------------------

def _site():
    """A plane rising 2 % to the east, an axis across it, its profile, and
    a grade line with one crest (+4 % then -2 %)."""
    tin = build_tin([(i * 10.0, j * 10.0, 100.0 + 0.2 * i) for i in range(41) for j in range(11)])
    document = Document.new()
    history = History(document)
    history.execute(topo.build_surface(document, tin))
    msp = document.doc.modelspace()
    axis = msp.add_lwpolyline([(0.0, 50.0), (400.0, 50.0)])
    history.execute(topo.draw_profile(document, tin, axis, (600.0, 0.0), 20.0, 1.0, 10.0, 1.0, "AXE"))
    anchor = topo.profile_entities(document)[0]
    frame = topo.ProfileFrame.from_entity(anchor)
    pts = [frame.to_drawing(0.0, 101.0), frame.to_drawing(200.0, 109.0), frame.to_drawing(400.0, 105.0)]
    grade = msp.add_lwpolyline(pts)
    history.execute(topo.register_grade(document, grade, anchor, frame))
    return tin, document, history, axis, grade, frame


def test_vcurves_draws_a_design_line_topography_reads():
    tin, document, history, axis, grade, frame = _site()
    command = actions.vertical_curves(document, grade, [3000.0])
    history.execute(command)
    line = command.line_command.entity
    assert topo.is_grade(line) and topo.grade_profile_anchor(document, line) is not None
    valign = actions.vertical_of(line)
    (c,) = valign.curves()
    assert c.crest and c.radius == 3000 and c.tangent == pytest.approx(90.0)
    # Topography reads it as a grade line: the parabola, within a tenth of a millimetre
    read = topo.grade_of(line, frame)
    assert profile.grade_at(read, 200.0) == pytest.approx(109.0 - c.flech, abs=1e-4)
    texts = [e.dxf.text for e in document.doc.modelspace().query("TEXT") if e.dxf.layer == "CAR-RASANTE-TEXTO"]
    assert "S1  0+200.00  109.00" in texts
    assert "crest R = 3000  T = 90.00  f = 1.350" in texts
    assert any(t.startswith("+4.00 % over 110.00 m") for t in texts)
    assert any(t.startswith("high point 0+230.00") for t in texts)
    rows = actions.vertical_table_rows(valign)
    assert rows[0][:6] == ["S1", "0+200.00", "109.000", "+4.000", "-2.000", "Crest"]
    # the volumes follow the curve
    template = profile.Template(width=7.0, cut_hv=1.0, fill_hv=1.5)
    on_curve = topo.earthworks_rows(tin, axis, valign.sample(1.0), frame.step, template)
    on_angle = topo.earthworks_rows(tin, axis, topo.grade_of(grade, frame), frame.step, template)
    assert on_curve[-1].fill_total < on_angle[-1].fill_total        # the crest is rounded down
    history.undo()
    assert line not in list(document.doc.modelspace())


def test_roadcheck_checks_grades_and_vertical_radii():
    tin, document, history, axis, grade, frame = _site()
    history.execute(actions.vertical_curves(document, grade, [2000.0]))
    (valign,) = actions.verticals_of_axis(document, axis)
    report = norms.check_vertical(valign, norms.find("ARP2022"), "R1")
    texts = [f.text for f in report.findings]
    assert report.errors == 1 and "S1 (crest): R = 2000 m, below the minimum 3100 m." in texts
    steep = norms.check_vertical(vertical.VerticalAlignment([(0, 100), (100, 108), (200, 100)], [1000]),
                                 norms.find("ARP2022"), "R1")
    assert any("Grade 1: +8.00 %, steeper than 6 %." == f.text for f in steep.findings)


# -- superelevation ------------------------------------------------------------------------------

C40, S40 = math.cos(math.radians(40.0)), math.sin(math.radians(40.0))
TANGENTS = [(0.0, 0.0), (400.0, 0.0), (400.0 + 400.0 * C40, 400.0 * S40)]


def test_the_superelevation_turns_along_the_clothoid():
    document = Document.new()
    history = History(document)
    tangents = document.doc.modelspace().add_lwpolyline(TANGENTS)
    command = actions.fit_axis(document, tangents, [300.0], spirals=[70.0])
    history.execute(command)
    axis = command.axis_command.entity
    arp = norms.find("ARP2022")
    rows = actions.superelevation_rows(actions.alignment_of(axis), arp, "R1")
    d = norms.superelevation(arp, arp.category("R1"), 300.0)
    assert d == pytest.approx(2.5 + 4.5 * (1 / 300 - 1 / 400) / (1 / 240 - 1 / 400))
    (pi,) = [p for p in actions.geometry.points_of_intersection(actions.alignment_of(axis))]
    assert len(rows) == 8
    # a left curve: the right lane is the outer one
    assert rows[0][1:] == [actions.format_station(pi.pc_station), "crown", "-2.50", "-2.50", "-"]
    assert rows[1][2:5] == ["outer lane flat", "-2.50", "0.00"]
    assert rows[2][2:5] == ["outer lane at the crown slope", "-2.50", "2.50"]
    assert rows[3][1:5] == [actions.format_station(pi.sc_station), "full superelevation",
                            f"{-d:.2f}", f"{d:.2f}"]
    assert rows[4][1] == actions.format_station(pi.cs_station)
    assert rows[7][1:3] == [actions.format_station(pi.pt_station), "crown"]
    # the outer lane is flat a fraction 2.5 / (d + 2.5) along the clothoid
    s_flat = pi.pc_station + 70.0 * 2.5 / (d + 2.5)
    assert rows[1][1] == actions.format_station(s_flat)


def test_widening_in_difficult_relief():
    arp = norms.find("ARP2022")
    cat = arp.category("Relief-difficile")
    assert norms.widening(cat, 100.0) == pytest.approx(0.25)        # 25 / R
    assert norms.widening(cat, 40.0) == pytest.approx(0.75)         # 30 / R
    assert norms.widening(cat, 300.0) is None
    assert norms.superelevation(arp, cat, 100.0) == pytest.approx(7.0)
    assert norms.superelevation(arp, cat, 400.0) == pytest.approx(-2.5)


# -- the mass-haul diagram -----------------------------------------------------------------------

class _Row:
    def __init__(self, s, cut, fill):
        self.s, self.cut_volume, self.fill_volume = s, cut, fill


def test_the_mass_diagram_balances_and_measures_the_haul():
    # 100 m³ of cut over the first 100 m, 100 m³ of fill over the next 100 m
    rows = [_Row(0, 0, 0)] + [_Row(s, 10, 0) for s in range(10, 101, 10)] + \
        [_Row(s, 0, 10) for s in range(110, 201, 10)]
    haul = actions.mass_haul(rows)
    assert haul.ordinates[10] == pytest.approx(100.0) and haul.surplus == pytest.approx(0.0)
    (seg,) = haul.segments
    assert seg.forward and seg.volume == pytest.approx(100.0)
    # a triangle 200 m long, 100 m³ high: moment 10 000 m³·m, mean distance 100 m
    assert seg.moment == pytest.approx(10000.0) and seg.distance == pytest.approx(100.0)
    # with a swell coefficient the same cut leaves a surplus
    assert actions.mass_haul(rows, 1.2).surplus == pytest.approx(20.0)


def test_the_mass_diagram_splits_at_each_balance_point():
    rows = [_Row(0, 0, 0), _Row(50, 50, 0), _Row(100, 0, 50), _Row(150, 0, 50), _Row(200, 50, 0)]
    haul = actions.mass_haul(rows)
    assert [(round(s.start), round(s.end)) for s in haul.segments] == [(0, 100), (100, 200)]
    assert haul.segments[0].forward and not haul.segments[1].forward
    assert haul.segments[0].volume == pytest.approx(50.0) and haul.segments[1].volume == pytest.approx(50.0)
    assert haul.segments[0].distance == pytest.approx(50.0)


def test_the_diagram_is_drawn_as_one_undo_step():
    rows = [_Row(0, 0, 0)] + [_Row(s, 10, 0) for s in range(10, 101, 10)] + \
        [_Row(s, 0, 12) for s in range(110, 201, 10)]
    document = Document.new()
    history = History(document)
    history.execute(actions.mass_haul_diagram(document, actions.mass_haul(rows), (0.0, 0.0)))
    texts = [e.dxf.text for e in document.doc.modelspace().query("TEXT")]
    assert "MASS DIAGRAM EJE" in texts and "Deficit to borrow: 20 m³" in texts
    history.undo()
    assert not list(document.doc.modelspace())


# -- the tools, headless --------------------------------------------------------------------------

class _Services:
    def __init__(self, document):
        self.document = document


def _ctx(document, history, echoed, prompts, done):
    return ToolContext(execute=history.execute, prompt=prompts.append, echo=echoed.append,
                       finish=lambda: done.append(True), undo_last=history.undo,
                       services=_Services(document))


def test_vcurves_tool_takes_one_radius_per_sommet():
    from plugins.carreteras.tools import VerticalCurvesTool

    tin, document, history, axis, grade, frame = _site()
    echoed, prompts, done = [], [], []
    tool = VerticalCurvesTool(_ctx(document, history, echoed, prompts, done))
    tool.start()
    tool.on_selection([grade])
    assert echoed[-1] == "1 sommets."
    assert prompts[-1].startswith("Vertical radius for every sommet <")
    tool.on_option("E")
    assert prompts[-1].startswith("Vertical radius at S1 (crest, +4.00 % to -2.00 %)")
    tool.on_option("3500")
    assert done and echoed[-1] == "S1: crest R = 3500 m, T = 105.00 m, f = 1.575 m."


def test_masshaul_tool_runs_end_to_end():
    from plugins.carreteras.tools import MassHaulTool

    tin, document, history, axis, grade, frame = _site()
    history.execute(actions.vertical_curves(document, grade, [3000.0]))
    curved = [e for e in document.doc.modelspace() if actions.vertical_of(e) is not None][0]
    echoed, prompts, done = [], [], []
    tool = MassHaulTool(_ctx(document, history, echoed, prompts, done))
    tool.start()
    tool.on_selection([curved])
    assert prompts[-1] == "Platform width <6>:"
    tool.on_option("7")
    tool.on_enter()
    tool.on_enter()
    assert prompts[-1] == "Coefficient applied to the cut (swell, reuse) <1>:"
    tool.on_option("1.1")
    assert any(e.startswith("Cut ") for e in echoed)
    assert prompts[-1] == "Specify the bottom-left corner of the diagram:"
    tool.on_point((0.0, -300.0))
    assert done
    assert any(e.dxf.layer == "CAR-MOVIMIENTO-TIERRAS" for e in document.doc.modelspace())


def test_a_curved_axis_gets_stations_at_the_step_not_at_every_chord():
    from plugins.topografia import alignment as topo_alignment

    document = Document.new()
    history = History(document)
    tangents = document.doc.modelspace().add_lwpolyline(TANGENTS)
    command = actions.fit_axis(document, tangents, [300.0], spirals=[70.0])
    history.execute(command)
    points = topo.axis_points(command.axis_command.entity)
    assert len(points) > 50                                   # chords and a flattened arc
    sts = topo_alignment.stations(points, 20.0)
    assert all(not s.vertex for s in sts[1:-1])
    assert all(abs(b.s - a.s - 20.0) < 1e-6 for a, b in zip(sts[:-2], sts[1:-1]))
    # a real angle point is still a station
    corner = topo_alignment.stations([(0.0, 0.0), (55.0, 0.0), (55.0, 30.0)], 20.0)
    assert [round(s.s, 3) for s in corner if s.vertex] == [0.0, 55.0, 85.0]
