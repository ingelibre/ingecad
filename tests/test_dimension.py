# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Dimension creation: DIMLINEAR, DIMALIGNED, DIMRADIUS, DIMDIAMETER."""
from __future__ import annotations

import math

import ezdxf
import pytest

from core import actions
from core.commands import History
from core.document import Document
from tools.base import ToolContext
from tools.dimension import (
    DimAlignedTool,
    DimDiameterTool,
    DimLinearTool,
    DimRadiusTool,
)


class Services:
    def __init__(self, document):
        self.document = document

    def pick_entity(self, point):
        import math
        best = None
        for e in self.document.modelspace():
            t = e.dxftype()
            if t in ("CIRCLE", "ARC"):
                c = e.dxf.center
                if math.dist((c.x, c.y), point) <= e.dxf.radius + 1:
                    best = e
            elif t == "LINE":
                s, w = e.dxf.start, e.dxf.end
                # distance from point to the segment
                dx, dy = w.x - s.x, w.y - s.y
                L2 = dx * dx + dy * dy or 1.0
                u = max(0.0, min(1.0, ((point[0]-s.x)*dx + (point[1]-s.y)*dy)/L2))
                px, py = s.x + u*dx, s.y + u*dy
                if math.dist((px, py), point) <= 0.5:
                    best = e
        return best


class Harness:
    def __init__(self):
        self.document = Document.new()
        self.history = History(self.document)
        self.finished = False
        self.ctx = ToolContext(
            execute=self.history.execute,
            prompt=lambda *_a: None,
            echo=lambda *_a: None,
            finish=lambda: setattr(self, "finished", True),
            undo_last=self.history.undo,
            services=Services(self.document),
        )

    @property
    def msp(self):
        return self.document.modelspace()


def test_linear_dim_horizontal():
    h = Harness()
    tool = DimLinearTool(h.ctx)
    tool.start()
    tool.on_point((0, 0))
    tool.on_point((10, 0))
    tool.on_point((5, 4))          # dim line above -> horizontal
    dims = h.msp.query("DIMENSION")
    assert len(dims) == 1
    assert dims[0].get_measurement() == pytest.approx(10.0)
    assert h.finished


def test_linear_dim_vertical():
    h = Harness()
    tool = DimLinearTool(h.ctx)
    tool.start()
    tool.on_point((0, 0))
    tool.on_point((0, 8))
    tool.on_point((4, 4))          # dim line to the side -> vertical
    assert h.msp.query("DIMENSION")[0].get_measurement() == pytest.approx(8.0)


def test_linear_dim_undo_removes_dim_and_block():
    h = Harness()
    tool = DimLinearTool(h.ctx)
    tool.start()
    for p in ((0, 0), (10, 0), (5, 4)):
        tool.on_point(p)
    block = h.msp.query("DIMENSION")[0].dxf.geometry
    assert block in h.document.doc.blocks
    h.history.undo()
    assert len(h.msp.query("DIMENSION")) == 0
    assert block not in h.document.doc.blocks


def test_aligned_dim_measures_true_length():
    h = Harness()
    tool = DimAlignedTool(h.ctx)
    tool.start()
    tool.on_point((0, 0))
    tool.on_point((3, 4))          # length 5
    tool.on_point((0, 4))          # offset to a side
    assert h.msp.query("DIMENSION")[0].get_measurement() == pytest.approx(5.0)


def test_radius_dim_on_circle():
    h = Harness()
    h.msp.add_circle((0, 0), 6)
    tool = DimRadiusTool(h.ctx)
    tool.start()
    tool.on_point((0, 0))          # picks the circle
    tool.on_point((6, 0))          # dimension line location
    assert len(h.msp.query("DIMENSION")) == 1
    assert h.finished


def test_diameter_dim_on_circle():
    h = Harness()
    h.msp.add_circle((0, 0), 6)
    tool = DimDiameterTool(h.ctx)
    tool.start()
    tool.on_point((0, 0))
    tool.on_point((6, 0))
    assert len(h.msp.query("DIMENSION")) == 1


def test_linear_dim_select_object():
    # Enter on the first prompt -> pick a line -> it dimensions the whole line.
    h = Harness()
    h.msp.add_line((2, 2), (12, 2))
    tool = DimLinearTool(h.ctx)
    tool.start()
    tool.on_enter()                # switch to select-object mode
    assert tool.entity_picker is True
    tool.on_point((7, 2))          # click on the line
    assert tool._p1 is not None and tool._p2 is not None
    assert tool.entity_picker is False   # snapping returns for the location
    tool.on_point((7, 6))          # place the dimension line
    dims = h.msp.query("DIMENSION")
    assert len(dims) == 1
    assert dims[0].get_measurement() == pytest.approx(10.0)


def test_linear_preview_dimension():
    # While placing, a rich dimension preview (frame + measurement) is offered.
    h = Harness()
    tool = DimLinearTool(h.ctx)
    tool.start()
    tool.on_point((0, 0))
    assert tool.preview_dimension((0, 2)) is None    # only one point yet
    tool.on_point((10, 0))
    dim = tool.preview_dimension((5, 4))             # cursor above -> horizontal
    assert dim["d1"] == (0, 4) and dim["d2"] == (10, 4)
    assert dim["text"] == "10.00"
    # cursor to the side: origins share Y, so the dimension STAYS
    # horizontal — the old rule flipped to a collapsed 0.00 vertical here.
    side = tool.preview_dimension((14, 0))
    assert side["text"] == "10.00"


def test_aligned_preview_measures_true_length():
    h = Harness()
    tool = DimAlignedTool(h.ctx)
    tool.start()
    tool.on_point((0, 0))
    tool.on_point((3, 4))
    dim = tool.preview_dimension((0, 4))
    assert dim["text"] == "5.00"


class FixedPick:
    """pick_entity always returns one preset entity (option-flow tests)."""

    def __init__(self, entity):
        self._entity = entity

    def pick_entity(self, point):
        return self._entity


# -- wave B: Mtext/Text/Angle + Horizontal/Vertical/Rotated --------------------

def test_linear_text_override_with_placeholder():
    h = Harness()
    tool = DimLinearTool(h.ctx)
    tool.start()
    tool.on_point((0, 0))
    tool.on_point((10, 0))
    assert tool.on_option("T")            # Text option at the location prompt
    assert tool.on_option("<> m")         # <> stands for the measurement
    tool.on_point((5, 4))
    dim = h.msp.query("DIMENSION")[0]
    assert dim.dxf.text == "<> m"
    assert h.finished


def test_linear_text_enter_keeps_measurement():
    h = Harness()
    tool = DimLinearTool(h.ctx)
    tool.start()
    tool.on_point((0, 0))
    tool.on_point((10, 0))
    assert tool.on_option("T")
    tool.on_enter()                       # empty Enter -> keep <measured>
    tool.on_point((5, 4))
    assert h.msp.query("DIMENSION")[0].dxf.text == "<>"


def test_linear_angle_rotates_text_only():
    h = Harness()
    tool = DimLinearTool(h.ctx)
    tool.start()
    tool.on_point((0, 0))
    tool.on_point((10, 0))
    assert tool.on_option("A")
    assert tool.on_option("30")
    tool.on_point((5, 4))
    dim = h.msp.query("DIMENSION")[0]
    assert dim.dxf.text_rotation == pytest.approx(30.0)
    assert dim.get_measurement() == pytest.approx(10.0)   # measurement intact


def test_linear_forced_vertical():
    h = Harness()
    tool = DimLinearTool(h.ctx)
    tool.start()
    tool.on_point((0, 0))
    tool.on_point((3, 4))
    assert tool.on_option("V")
    tool.on_point((2, 10))                # auto rule would say horizontal here
    assert h.msp.query("DIMENSION")[0].get_measurement() == pytest.approx(4.0)


def test_linear_rotated_projects_measurement():
    h = Harness()
    tool = DimLinearTool(h.ctx)
    tool.start()
    tool.on_point((0, 0))
    tool.on_point((10, 0))
    assert tool.on_option("R")
    assert tool.on_option("45")
    tool.on_point((5, 6))
    m = h.msp.query("DIMENSION")[0].get_measurement()
    assert m == pytest.approx(10 * math.cos(math.radians(45)))


def test_linear_select_circle_quadrant_rule():
    # Official: a pick near the N/S quadrant -> horizontal (W-E endpoints).
    h = Harness()
    circle = h.msp.add_circle((5, 5), 3)
    h.ctx.services = FixedPick(circle)
    tool = DimLinearTool(h.ctx)
    tool.start()
    tool.on_enter()                       # select-object mode
    tool.on_point((5, 7.9))               # near north
    assert tool._p1 == (2, 5) and tool._p2 == (8, 5)
    tool.on_point((5, 12))
    assert h.msp.query("DIMENSION")[0].get_measurement() == pytest.approx(6.0)


def test_aligned_select_circle_uses_pick_diameter():
    h = Harness()
    circle = h.msp.add_circle((0, 0), 5)
    h.ctx.services = FixedPick(circle)
    tool = DimAlignedTool(h.ctx)
    tool.start()
    tool.on_enter()
    tool.on_point((3, 3))                 # diameter through the pick (45 deg)
    assert tool._p1[0] == pytest.approx(-tool._p2[0])
    assert math.dist(tool._p1, tool._p2) == pytest.approx(10.0)


def test_linear_select_polyline_segment():
    h = Harness()
    pl = h.msp.add_lwpolyline([(0, 0), (10, 0), (10, 8)])
    h.ctx.services = FixedPick(pl)
    tool = DimLinearTool(h.ctx)
    tool.start()
    tool.on_enter()
    tool.on_point((5, 0.1))               # nearest the bottom segment
    assert tool._p1 == (0, 0) and tool._p2 == (10, 0)


def test_radius_text_and_angle_options():
    h = Harness()
    h.msp.add_circle((0, 0), 6)
    tool = DimRadiusTool(h.ctx)
    tool.start()
    tool.on_point((0, 0))                 # picks the circle
    assert tool.on_option("T")
    assert tool.on_option("<> TYP")
    assert tool.on_option("A")
    assert tool.on_option("15")
    tool.on_point((6, 0))
    dim = h.msp.query("DIMENSION")[0]
    assert dim.dxf.text == "<> TYP"
    assert dim.dxf.text_rotation == pytest.approx(15.0)


def test_preview_text_substitutes_placeholder():
    h = Harness()
    tool = DimLinearTool(h.ctx)
    tool.start()
    tool.on_point((0, 0))
    tool.on_point((10, 0))
    assert tool.on_option("T")
    assert tool.on_option("<> m")
    assert tool.preview_dimension((5, 4))["text"] == "10.00 m"


# -- wave C: DIMANGULAR / DIMARC / DIMORDINATE / DIMCENTER ---------------------

from tools.dimension import (   # noqa: E402
    DimAngularTool,
    DimArcTool,
    DimCenterTool,
    DimOrdinateTool,
)


def test_angular_vertex_flow():
    h = Harness()
    tool = DimAngularTool(h.ctx)
    tool.start()
    tool.on_enter()                       # <specify vertex>
    tool.on_point((0, 0))                 # vertex
    tool.on_point((10, 0))                # first endpoint
    tool.on_point((0, 10))                # second endpoint
    tool.on_point((3, 3))                 # location inside the 90-deg region
    dims = h.msp.query("DIMENSION")
    assert len(dims) == 1
    assert dims[0].get_measurement() == pytest.approx(90.0)   # degrees
    assert h.finished


def test_angular_location_picks_the_other_angle():
    # Same three points, location in the OUTER region -> 270 degrees.
    h = Harness()
    tool = DimAngularTool(h.ctx)
    tool.start()
    tool.on_enter()
    tool.on_point((0, 0))
    tool.on_point((10, 0))
    tool.on_point((0, 10))
    tool.on_point((-4, -4))               # explement side
    m = h.msp.query("DIMENSION")[0].get_measurement()
    assert m == pytest.approx(270.0)


def test_angular_two_lines():
    h = Harness()
    l1 = h.msp.add_line((0, 0), (10, 0))
    l2 = h.msp.add_line((0, 0), (10, 10))
    picks = iter([l1, l2])

    class TwoPicks:
        def pick_entity(self, point):
            return next(picks)

    h.ctx.services = TwoPicks()
    tool = DimAngularTool(h.ctx)
    tool.start()
    tool.on_point((5, 0))                 # first line
    tool.on_point((5, 5))                 # second line
    tool.on_point((6, 2))                 # inside the 45-deg wedge
    m = h.msp.query("DIMENSION")[0].get_measurement()
    assert m == pytest.approx(45.0)


def test_angular_arc_uses_included_angle():
    h = Harness()
    arc = h.msp.add_arc((0, 0), 5, start_angle=0, end_angle=120)
    h.ctx.services = FixedPick(arc)
    tool = DimAngularTool(h.ctx)
    tool.start()
    tool.on_point((5, 1))                 # select the arc
    tool.on_point((-6, -6))               # location outside the included angle
    m = h.msp.query("DIMENSION")[0].get_measurement()
    assert m == pytest.approx(120.0)   # NOT flipped by location


def test_angular_quadrant_locks_region():
    h = Harness()
    tool = DimAngularTool(h.ctx)
    tool.start()
    tool.on_enter()
    tool.on_point((0, 0))
    tool.on_point((10, 0))
    tool.on_point((0, 10))
    assert tool.on_option("Q")
    tool.on_point((3, 3))                 # quadrant: the 90-deg wedge
    tool.on_point((-4, -4))               # location elsewhere — angle stays 90
    m = h.msp.query("DIMENSION")[0].get_measurement()
    assert m == pytest.approx(90.0)



def _arc_dim_value(h):
    """ezdxf's ARC_DIMENSION has no get_measurement — read the rendered
    text (ISO-25 writes a comma decimal separator)."""
    dim = h.msp.query("ARC_DIMENSION")[0]
    blk = h.document.doc.blocks[dim.dxf.geometry]
    texts = [e.text for e in blk if e.dxftype() == "MTEXT"]
    texts += [e.dxf.text for e in blk if e.dxftype() == "TEXT"]
    return float(texts[0].replace(",", "."))

def test_arc_length_dimension():
    h = Harness()
    arc = h.msp.add_arc((0, 0), 10, start_angle=0, end_angle=90)
    h.ctx.services = FixedPick(arc)
    tool = DimArcTool(h.ctx)
    tool.start()
    tool.on_point((7, 7))                 # select the arc
    tool.on_point((11, 11))               # location
    assert len(h.msp.query("ARC_DIMENSION")) == 1
    # arc length = r * sweep = 10 * pi/2 = 15.71
    assert _arc_dim_value(h) == pytest.approx(10 * math.pi / 2, abs=0.01)


def test_arc_partial():
    h = Harness()
    arc = h.msp.add_arc((0, 0), 10, start_angle=0, end_angle=180)
    h.ctx.services = FixedPick(arc)
    tool = DimArcTool(h.ctx)
    tool.start()
    tool.on_point((7, 7))
    assert tool.on_option("P")
    tool.on_point((10, 0))                # first partial point (0 deg)
    tool.on_point((0, 10))                # second partial point (90 deg)
    tool.on_point((8, 8))
    assert _arc_dim_value(h) == pytest.approx(10 * math.pi / 2, abs=0.01)


def test_arc_on_polyline_bulge_segment():
    h = Harness()
    # semicircle bulge segment from (0,0) to (10,0), radius 5
    pl = h.msp.add_lwpolyline([(0, 0, 1.0), (10, 0, 0.0)], format="xyb")
    h.ctx.services = FixedPick(pl)
    tool = DimArcTool(h.ctx)
    tool.start()
    tool.on_point((5, 5))
    tool.on_point((5, 7))
    assert _arc_dim_value(h) == pytest.approx(5 * math.pi, abs=0.01)


def test_ordinate_auto_and_forced_datum():
    h = Harness()
    tool = DimOrdinateTool(h.ctx)
    tool.start()
    tool.on_point((7, 3))                 # feature
    tool.on_point((7.5, 9))               # mostly-vertical leader -> X datum
    dim = h.msp.query("DIMENSION")[0]
    assert dim.dxf.dimtype & 64            # the X-datum flag
    assert dim.get_measurement().x == pytest.approx(7.0)

    h2 = Harness()
    tool2 = DimOrdinateTool(h2.ctx)
    tool2.start()
    tool2.on_point((7, 3))
    assert tool2.on_option("Y")           # force the Y datum
    tool2.on_point((7.5, 9))
    dim2 = h2.msp.query("DIMENSION")[0]
    assert not dim2.dxf.dimtype & 64       # Y datum
    assert dim2.get_measurement().y == pytest.approx(3.0)


def test_center_mark_and_center_lines():
    h = Harness()
    circle = h.msp.add_circle((10, 10), 6)
    h.ctx.services = FixedPick(circle)
    tool = DimCenterTool(h.ctx)
    tool.start()
    tool.on_point((16, 10))
    lines = h.msp.query("LINE")
    assert len(lines) == 2                # ISO default DIMCEN=2.5: plain mark
    xs = sorted((ln.dxf.start.x, ln.dxf.end.x) for ln in lines)
    assert xs[0] == (7.5, 12.5)           # the horizontal mark, +-2.5
    h.history.undo()                      # ONE undo removes the whole mark
    assert len(h.msp.query("LINE")) == 0

    # negative DIMCEN -> mark + 4 center lines out to r + |DIMCEN|
    h2 = Harness()
    h2.document.doc.dimstyles.get("ISO-25").dxf.dimcen = -2.5
    circle2 = h2.msp.add_circle((0, 0), 6)
    h2.ctx.services = FixedPick(circle2)
    tool2 = DimCenterTool(h2.ctx)
    tool2.start()
    tool2.on_point((6, 0))
    lines2 = h2.msp.query("LINE")
    assert len(lines2) == 6
    reach = max(max(abs(ln.dxf.start.x), abs(ln.dxf.end.x)) for ln in lines2)
    assert reach == pytest.approx(8.5)    # r + |dimcen|


def test_angular_text_option():
    h = Harness()
    tool = DimAngularTool(h.ctx)
    tool.start()
    tool.on_enter()
    tool.on_point((0, 0))
    tool.on_point((10, 0))
    tool.on_point((0, 10))
    assert tool.on_option("T")
    assert tool.on_option("<> approx")
    tool.on_point((3, 3))
    assert h.msp.query("DIMENSION")[0].dxf.text == "<> approx"


# -- wave D: DIMCONTINUE / DIMBASELINE / DIMTEDIT ------------------------------

import tools.dimension as _dimmod  # noqa: E402
from tools.dimension import (   # noqa: E402
    DimBaselineTool,
    DimContinueTool,
    DimTextEditTool,
)


@pytest.fixture(autouse=True)
def _fresh_chain_state():
    _dimmod._LAST_DIM[0] = None
    yield
    _dimmod._LAST_DIM[0] = None


def _make_base(h, p1=(0, 0), p2=(10, 0), loc=(5, 4)):
    tool = DimLinearTool(h.ctx)
    tool.start()
    for p in (p1, p2, loc):
        tool.on_point(p)
    return h.msp.query("DIMENSION")[0]


def test_continue_chains_from_last_dimension():
    h = Harness()
    _make_base(h)                          # dim line at y=4
    tool = DimContinueTool(h.ctx)
    tool.start()
    assert not getattr(tool, "_selecting", False)   # auto base: the last dim
    tool.on_point((20, 0))
    tool.on_point((35, 0))                 # chains from the PREVIOUS new dim
    dims = h.msp.query("DIMENSION")
    assert len(dims) == 3
    assert dims[1].get_measurement() == pytest.approx(10.0)   # 10 -> 20
    assert dims[2].get_measurement() == pytest.approx(15.0)   # 20 -> 35
    # both stay aligned with the base dimension line
    assert dims[1].dxf.defpoint.y == pytest.approx(4.0)
    assert dims[2].dxf.defpoint.y == pytest.approx(4.0)
    tool.on_enter()                        # -> <Select>
    tool.on_enter()                        # second Enter ends
    assert h.finished


def test_baseline_stacks_by_dimdli():
    h = Harness()
    _make_base(h)
    tool = DimBaselineTool(h.ctx)
    tool.start()
    tool.on_point((20, 0))
    tool.on_point((30, 0))
    dims = h.msp.query("DIMENSION")
    assert len(dims) == 3
    # first origin reused: measurements from x=0
    assert dims[1].get_measurement() == pytest.approx(20.0)
    assert dims[2].get_measurement() == pytest.approx(30.0)
    # each line DIMDLI (3.75 default) above the previous
    assert dims[1].dxf.defpoint.y == pytest.approx(4.0 + 3.75)
    assert dims[2].dxf.defpoint.y == pytest.approx(4.0 + 7.5)


def test_continue_undo_option():
    h = Harness()
    _make_base(h)
    tool = DimContinueTool(h.ctx)
    tool.start()
    tool.on_point((20, 0))
    assert len(h.msp.query("DIMENSION")) == 2
    assert tool.on_option("U")
    assert len(h.msp.query("DIMENSION")) == 1
    tool.on_point((25, 0))                 # chains from the base again
    assert h.msp.query("DIMENSION")[1].get_measurement() == pytest.approx(15.0)


def test_continue_select_base():
    h = Harness()
    base = _make_base(h)
    _dimmod._LAST_DIM[0] = None            # a fresh session: no last dim
    h.ctx.services = FixedPick(base)
    tool = DimContinueTool(h.ctx)
    tool.start()
    assert tool._selecting                 # asks for the base
    tool.on_point((5, 4))                  # pick it
    tool.on_point((22, 0))
    assert h.msp.query("DIMENSION")[1].get_measurement() == pytest.approx(12.0)


def test_dimtedit_move_and_undo():
    h = Harness()
    base = _make_base(h)
    h.ctx.services = FixedPick(base)
    tool = DimTextEditTool(h.ctx)
    tool.start()
    tool.on_point((5, 4))                  # select the dimension
    tool.on_point((2, 9))                  # new text location
    assert base.dxf.dimtype & 128          # user text position
    assert base.dxf.text_midpoint.x == pytest.approx(2.0)
    blocks = [b.name for b in h.document.doc.blocks if b.name.startswith("*D")]
    assert len(blocks) == 1                # the old *D block was dropped
    h.history.undo()
    assert not base.dxf.dimtype & 128
    blocks = [b.name for b in h.document.doc.blocks if b.name.startswith("*D")]
    assert len(blocks) == 1                # still exactly one


def test_dimtedit_angle_and_home():
    h = Harness()
    base = _make_base(h)
    h.ctx.services = FixedPick(base)
    tool = DimTextEditTool(h.ctx)
    tool.start()
    tool.on_point((5, 4))
    assert tool.on_option("A")
    assert tool.on_option("30")
    assert base.dxf.text_rotation == pytest.approx(30.0)

    tool2 = DimTextEditTool(h.ctx)
    tool2.start()
    tool2.on_point((5, 4))
    tool2.on_point((1, 12))                # move it away...
    tool3 = DimTextEditTool(h.ctx)
    tool3.start()
    tool3.on_point((5, 4))
    assert tool3.on_option("H")            # ...and Home restores the default
    assert not base.dxf.dimtype & 128


def test_dimension_uses_current_style():
    h = Harness()
    h.document.doc.header["$DIMSTYLE"] = "Acot-100"
    tool = DimLinearTool(h.ctx)
    tool.start()
    for p in ((0, 0), (10, 0), (5, 4)):
        tool.on_point(p)
    assert h.msp.query("DIMENSION")[0].dxf.dimstyle == "Acot-100"


# -- the orientation rule (the collapsed-to-zero regression) -------------------

def test_vertical_origins_never_give_a_zero_horizontal_dim():
    """Dimensioning a rectangle's VERTICAL edge and dragging slightly
    diagonally used to pick 'horizontal' — a collapsed dimension reading
    0 with no visible text (the reported bug)."""
    h = Harness()
    tool = DimLinearTool(h.ctx)
    tool.start()
    tool.on_point((30.0, 0.0))
    tool.on_point((30.0, 20.0))
    for cursor in ((33.0, 25.0), (28.0, -9.0), (35.0, 10.0), (30.5, 40.0)):
        assert tool._angle_for(cursor) == 90.0, cursor
    tool.on_point((33.0, 25.0))
    assert h.msp.query("DIMENSION")[0].get_measurement() == pytest.approx(20.0)


def test_horizontal_origins_always_measure_horizontally():
    h = Harness()
    tool = DimLinearTool(h.ctx)
    tool.start()
    tool.on_point((0.0, 0.0))
    tool.on_point((30.0, 0.0))
    for cursor in ((15.0, -6.0), (32.0, 4.0), (-3.0, 8.0)):
        assert tool._angle_for(cursor) == 0.0, cursor


def test_diagonal_origins_follow_the_side_the_cursor_leaves():
    """Corners (0,0)-(30,20): beyond the x-range reads vertical, beyond
    the y-range horizontal; between the points the closer-axis rule."""
    h = Harness()
    tool = DimLinearTool(h.ctx)
    tool.start()
    tool.on_point((0.0, 0.0))
    tool.on_point((30.0, 20.0))
    assert tool._angle_for((38.0, 10.0)) == 90.0    # right of the box
    assert tool._angle_for((-5.0, 12.0)) == 90.0    # left of it
    assert tool._angle_for((15.0, 27.0)) == 0.0     # above it
    assert tool._angle_for((15.0, -6.0)) == 0.0     # below it
    assert tool._angle_for((36.0, 22.0)) == 90.0    # corner: x exceeded more
