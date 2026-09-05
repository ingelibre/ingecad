# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Topography plugin, T4: contour lines held to surfaces whose contours
are known in closed form (a plane, a cone), never crossing, linked into
the right chains, labelled and masked; and slope zones."""
from __future__ import annotations

import math
import random

import pytest

from core.commands import History
from core.document import Document
from plugins.topografia import actions, contours
from plugins.topografia.tin import _segments_cross, build_tin
from tools.base import ToolContext


def _plane(nx: int = 21, ny: int = 11, step: float = 5.0, gx: float = 0.1):
    """z = gx * x on a grid: contours are vertical lines at x = k / gx."""
    return build_tin([(i * step, j * step, gx * i * step) for i in range(nx) for j in range(ny)])


def _cone(radius: float = 50.0, step: float = 2.0):
    """z = 10 - r / 5: contours are circles; the rim is at z = 0."""
    pts = []
    n = int(radius / step)
    for i in range(-n, n + 1):
        for j in range(-n, n + 1):
            x, y = i * step, j * step
            r = math.hypot(x, y)
            if r <= radius + 1e-9:
                pts.append((x, y, 10.0 - r / 5.0))
    return build_tin(pts)


def test_a_plane_gives_straight_parallel_contours_that_never_cross():
    tin = _plane()
    lines = contours.contours(tin, 1.0)
    assert len(lines) == 9                                   # z 1..9 (0 and 10 are the rims)
    for c in lines:
        xs = {round(p[0], 6) for p in c.points}
        assert len(xs) == 1 and abs(c.level / 0.1 - next(iter(xs))) < 1e-6
        assert not c.closed and len(c.points) >= 2
        ys = [p[1] for p in c.points]
        assert abs(min(ys)) < 1e-9 and abs(max(ys) - 50.0) < 1e-9   # one chain, edge to edge
    assert [c.major for c in lines] == [False, False, False, False, True,
                                        False, False, False, False]
    # different levels never cross
    for a in lines:
        for b in lines:
            if a is b:
                continue
            for p, q in zip(a.points, a.points[1:]):
                for r, s in zip(b.points, b.points[1:]):
                    assert not _segments_cross(p, q, r, s)


def test_a_cone_gives_closed_rings_of_the_right_length():
    tin = _cone()
    rings = contours.contours(tin, 2.0)
    assert [c.level for c in rings] == [2.0, 4.0, 6.0, 8.0]
    for c in rings:
        assert c.closed
        radius = (10.0 - c.level) * 5.0
        assert c.length() == pytest.approx(2 * math.pi * radius, rel=0.03)
        assert all(abs(math.hypot(*p) - radius) < 1.5 for p in c.points)


def test_shuffled_segments_link_into_one_loop_and_open_chains_keep_their_ends():
    rng = random.Random(4)
    square = [(0, 0), (10, 0), (10, 10), (0, 10)]
    segs = [(square[i], square[(i + 1) % 4]) for i in range(4)]
    rng.shuffle(segs)
    chains = contours.link_segments(segs)
    assert len(chains) == 1 and chains[0][1] is True and len(chains[0][0]) == 4
    open_segs = [((0, 0), (1, 0)), ((2, 0), (3, 0)), ((1, 0), (2, 0))]
    rng.shuffle(open_segs)
    chains = contours.link_segments(open_segs)
    assert len(chains) == 1 and chains[0][1] is False
    assert {chains[0][0][0], chains[0][0][-1]} == {(0, 0), (3, 0)}


def test_smoothing_positions_and_slopes():
    pts = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]
    smoothed = contours.smooth(pts, closed=False, passes=1)
    assert smoothed[0] == pts[0] and smoothed[-1] == pts[-1] and len(smoothed) > len(pts)
    ring = contours.smooth([(0, 0), (10, 0), (10, 10), (0, 10)], closed=True, passes=2)
    assert len(ring) == 16
    spots = contours.positions_along([(0.0, 0.0), (35.0, 0.0)], False, 10.0)
    assert [round(s[0], 6) for s in spots] == [5.0, 15.0, 25.0] and spots[0][2] == 0.0
    assert contours.positions_along([(0.0, 0.0), (4.0, 0.0)], False, 10.0)[0][0] == 2.0
    near = contours.nearest_on_chain([(0, 0), (10, 0)], False, (4.0, 3.0))
    assert near[:2] == pytest.approx((4.0, 0.0))
    plane = _plane(gx=0.1)
    assert contours.triangle_slope(plane, plane.triangles[0]) == pytest.approx(10.0)
    assert contours.slope_class(10.0, (5, 10, 20, 30)) == 2
    assert contours.slope_label(0, (5, 10)) == "< 5 %" and contours.slope_label(2, (5, 10)) == "> 10 %"
    assert contours.slope_label(1, (5, 10)) == "5 - 10 %"


# -- in the drawing ---------------------------------------------------------------------

def _document():
    document = Document.new()
    return document, History(document)


def test_contours_land_at_their_elevation_on_two_layers_and_undo():
    document, history = _document()
    tin = _cone()
    history.execute(actions.draw_contours(document, tin, 1.0, major_every=5))
    lines = actions.contour_entities(document)
    assert len(lines) == 9
    levels = sorted(actions.contour_level(e) for e in lines)
    assert levels == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0]
    for e in lines:
        assert e.dxf.elevation == actions.contour_level(e) and e.closed
        assert e.dxf.layer == ("TOPO-CN-GRUESA" if actions.contour_level(e) == 5.0 else "TOPO-CN-FINA")
    assert document.doc.layers.get("TOPO-CN-GRUESA").color == 30
    history.execute(actions.label_contours(document, lines, 0.8, spacing=60.0))
    labels = [e for e in document.doc.modelspace() if e.dxftype() == "MTEXT"]
    assert labels and all(e.dxf.layer == "TOPO-CN-TEXTO" for e in labels)
    assert labels[0].dxf.hasattr("bg_fill") and labels[0].dxf.bg_fill == 3     # canvas mask
    assert {e.text for e in labels} <= {f"{k}" for k in range(1, 10)}
    ring_9 = next(e for e in lines if actions.contour_level(e) == 9.0)
    assert sum(1 for e in labels if e.get_xdata("INGECAD")[1].value == ring_9.dxf.handle) == 1
    history.undo()
    assert not [e for e in document.doc.modelspace() if e.dxftype() == "MTEXT"]
    history.undo()
    assert not actions.contour_entities(document)


def test_slope_zones_are_one_solid_hatch_per_class_plus_a_legend():
    document, history = _document()
    tin = _plane(gx=0.1)                                # 10 % everywhere
    report = actions.slope_report(tin, (5, 10, 20, 30))
    assert [r[2] for r in report] == [0, 0, len(tin.triangles), 0, 0]
    assert report[2][1] == pytest.approx(100.0 * 50.0)
    cone = actions.slope_report(_cone(), (5, 10, 20, 30))
    assert sum(r[2] for r in cone) == len(_cone().triangles)   # every facet in one class
    history.execute(actions.slope_zones(document, tin, (5, 10, 20, 30), legend_at=(60.0, 60.0)))
    hatches = [e for e in document.doc.modelspace() if e.dxftype() == "HATCH"]
    assert len(hatches) == 1 and hatches[0].dxf.solid_fill == 1
    assert len(hatches[0].paths) == len(tin.triangles)
    assert hatches[0].dxf.color == actions.SLOPE_COLORS[2]
    texts = [e.dxf.text for e in document.doc.modelspace() if e.dxftype() == "TEXT"]
    assert any(t.startswith("10 - 20 %") for t in texts)
    assert [e for e in document.doc.modelspace() if e.dxftype() == "SOLID"]
    history.undo()
    assert not [e for e in document.doc.modelspace() if e.dxftype() in ("HATCH", "TEXT", "SOLID")]


# -- tools, headless ---------------------------------------------------------------------------

class _Services:
    def __init__(self, document):
        self.document = document
        self.picked = None

    def pick_entity(self, point):
        return self.picked


class _Harness:
    def __init__(self):
        self.document = Document.new()
        self.history = History(self.document)
        self.finished = False
        self.echoed: list[str] = []
        self.services = _Services(self.document)
        self.ctx = ToolContext(
            execute=self.history.execute, prompt=self.echoed.append,
            echo=self.echoed.append, finish=lambda: setattr(self, "finished", True),
            undo_last=self.history.undo, services=self.services)


def test_the_three_tools_headless():
    from plugins.topografia.tools import ContourLabelTool, ContourTool, SlopeZonesTool

    h = _Harness()
    h.history.execute(actions.build_surface(h.document, _cone()))
    tool = ContourTool(h.ctx)
    tool.start()
    assert tool.on_option("2")                            # interval
    tool.on_enter()                                       # major every 5
    tool.on_enter()                                       # no smoothing
    assert h.finished and len(actions.contour_entities(h.document)) == 4
    assert any("4 contours drawn" in line for line in h.echoed)

    h.finished = False
    label = ContourLabelTool(h.ctx)
    label.start()
    tool_ok = label.on_option("A")
    assert tool_ok and label.on_option("40") and label.on_option("0.8")
    assert label.on_option("A")                           # all contours
    assert h.finished
    labels = [e for e in h.document.doc.modelspace() if e.dxftype() == "MTEXT"]
    assert len(labels) >= 4

    h.finished = False
    pick = ContourLabelTool(h.ctx)
    pick.start()
    assert pick.on_option("P")
    h.services.picked = actions.contour_entities(h.document)[0]
    pick.on_point((30.0, 0.0))
    assert len([e for e in h.document.doc.modelspace() if e.dxftype() == "MTEXT"]) == len(labels) + 1
    pick.on_enter()
    assert h.finished

    h.finished = False
    zones = SlopeZonesTool(h.ctx)
    zones.start()
    assert zones.on_option("10, 25")
    zones.on_enter()                                      # no legend
    assert h.finished
    assert any("10 - 25 %" in line for line in h.echoed)
    assert len([e for e in h.document.doc.modelspace() if e.dxftype() == "HATCH"]) >= 1

    empty = _Harness()
    ContourTool(empty.ctx).start()
    assert empty.finished and "no surface" in empty.echoed[-1]
