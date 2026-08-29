# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Every grip-editable type must survive its own undo.

Marco asked why a LEADER showed no grips ("no aparecen esos cuadraditos").
Giving it grips exposed something worse: undoing a leader grip left the
leader moved. ``_restore_entity`` copies DXF *attributes*, and a leader's
vertices are not one -- the same reason LWPOLYLINE and MTEXT already had
their own lines there.

So instead of fixing the one type, this sweeps ALL of them: move the first
grip, fingerprint the geometry that grip can change, undo, and demand the
fingerprint comes back. It found two more silent data losses -- SPLINE and
HATCH, where a moved hatch stayed moved through Ctrl+Z.

Add a type to ``entity_grips`` and add it here; the sweep is the point.
"""
from __future__ import annotations

import pytest

from core.actions import SnapshotCommand
from core.document import Document
from core.select import apply_grip_edit, entity_grips


def _fingerprint(e):
    """The geometry a grip can move, as comparable values.

    Deliberately per-type and explicit: an ``str()`` of the object would
    hash memory addresses and report "nothing changed" for a hatch that had
    in fact moved -- which is exactly what happened while writing this.
    """
    t = e.dxftype()
    if t == "LINE":
        return tuple(e.dxf.start), tuple(e.dxf.end)
    if t == "LWPOLYLINE":
        return [tuple(p) for p in e.get_points("xy")]
    if t == "CIRCLE":
        return tuple(e.dxf.center), e.dxf.radius
    if t == "ARC":
        return (tuple(e.dxf.center), e.dxf.radius,
                e.dxf.start_angle, e.dxf.end_angle)
    if t == "ELLIPSE":
        return tuple(e.dxf.center), tuple(e.dxf.major_axis), e.dxf.ratio
    if t == "SPLINE":
        return ([tuple(p) for p in e.fit_points],
                [tuple(p) for p in e.control_points])
    if t == "LEADER":
        return [(v.x, v.y, v.z) for v in e.vertices]
    if t == "SOLID":
        return [tuple(getattr(e.dxf, f"vtx{i}")) for i in range(4)]
    if t == "TEXT":
        return (tuple(e.dxf.insert),
                tuple(e.dxf.align_point) if e.dxf.hasattr("align_point") else None)
    if t == "HATCH":
        # Both boundary kinds: a title block's frame is an EdgePath, and a
        # fingerprint that only knew PolylinePath reported "nothing moved"
        # for it -- blind in exactly the shape the real drawings use.
        def _path(path):
            vertices = getattr(path, "vertices", None)
            if vertices is not None:
                return [tuple(v)[:2] for v in vertices]
            return [(tuple(edge.start)[:2], tuple(edge.end)[:2])
                    for edge in getattr(path, "edges", [])
                    if hasattr(edge, "start")]
        return [_path(path) for path in e.paths]
    if t in ("MULTILEADER", "MLEADER"):
        return [[[tuple(v) for v in line.vertices] for line in leader.lines]
                for leader in e.context.leaders]
    raise AssertionError(f"no fingerprint for {t} — add one")


def _mleader(msp):
    from ezdxf.math import Vec2
    from ezdxf.render import mleader

    builder = msp.add_multileader_mtext("Standard")
    builder.set_content("PEDESTAL")
    builder.add_leader_line(mleader.ConnectionSide.left, [Vec2(-8, -4)])
    builder.build(insert=Vec2(0, 0))
    return msp[-1]


def _hatch(msp):
    h = msp.add_hatch(color=2)
    h.paths.add_polyline_path([(0, 0), (5, 0), (5, 5), (0, 5)], is_closed=True)
    return h


BUILDERS = {
    "LINE": lambda m: m.add_line((0, 0), (10, 0)),
    "LWPOLYLINE": lambda m: m.add_lwpolyline([(0, 0), (5, 5), (10, 0)]),
    "CIRCLE": lambda m: m.add_circle((0, 0), 5),
    "ARC": lambda m: m.add_arc((0, 0), 5, 0, 90),
    "ELLIPSE": lambda m: m.add_ellipse((0, 0), (5, 0), 0.5),
    "SPLINE": lambda m: m.add_spline([(0, 0), (5, 5), (10, 0)]),
    "LEADER": lambda m: m.add_leader([(0, 0), (5, 5), (8, 5)]),
    "TEXT": lambda m: m.add_text("hola"),
    "SOLID": lambda m: m.add_solid([(0, 0), (1, 0), (1, 1), (0, 1)]),
    "HATCH": _hatch,
    "MULTILEADER": _mleader,
}


@pytest.mark.parametrize("kind", sorted(BUILDERS))
def test_a_grip_edit_is_undone_exactly(kind):
    doc = Document.new()
    if kind == "MULTILEADER":
        import ezdxf

        doc = Document(ezdxf.new("R2010", setup=True))
    entity = BUILDERS[kind](doc.modelspace())
    grips = entity_grips(entity)
    assert grips, f"{kind} shows no grips at all"

    before = _fingerprint(entity)
    snap = SnapshotCommand([entity])
    x, y, role = grips[0][0], grips[0][1], grips[0][2]
    assert apply_grip_edit(entity, 0, role, (x + 3.0, y + 3.0)) is not False
    snap.commit(doc)

    # the control: an undo that "restores" something the edit never changed
    # proves nothing, and a fingerprint blind to the change would say so
    assert _fingerprint(entity) != before, \
        f"the {kind} grip changed nothing — the test would pass vacuously"

    snap.undo(doc)
    assert _fingerprint(entity) == before, \
        f"undoing a {kind} grip edit left the entity changed"
    # Identity survives too: the snapshot is an ezdxf copy, which carries
    # no owner, and discarding it left the entity parentless. Nothing in the
    # file broke -- the layout still holds it and ezdxf re-stamps the owner
    # on export -- but the surgical post-undo redraw skips owner-less
    # entities, so the object went on hiding until a full regen caught up.
    assert entity.dxf.owner is not None, \
        f"undoing a {kind} edit left the entity without an owner"
    assert entity.dxf.handle is not None


def test_a_leader_shows_a_grip_on_every_vertex():
    """What Marco actually asked for: AutoCAD puts a square on each vertex
    of the leader line, and dragging one re-aims that segment."""
    doc = Document.new()
    leader = doc.modelspace().add_leader([(0, 0), (5, 5), (8, 5)])
    grips = entity_grips(leader)
    assert [g[2] for g in grips] == ["vertex", "vertex", "vertex"]
    assert [(g[0], g[1]) for g in grips] == [(0, 0), (5, 5), (8, 5)]

    apply_grip_edit(leader, 0, "vertex", (-2.0, -3.0))
    assert [(v.x, v.y) for v in leader.vertices] == [(-2, -3), (5, 5), (8, 5)], \
        "moving one vertex must leave the others alone"


# -- a hatch's boundary corners (p. 873) --------------------------------------

def _closed(hatch) -> bool:
    """Every edge's end meets the next edge's start: the loop is intact."""
    for path in hatch.paths:
        if getattr(path, "vertices", None) is not None:
            continue
        edges = list(path.edges)
        for a, b in zip(edges, edges[1:] + edges[:1]):
            if abs(a.end[0] - b.start[0]) > 1e-6 \
                    or abs(a.end[1] - b.start[1]) > 1e-6:
                return False
    return True


def _rect_edge_hatch(msp):
    """A frame drawn the way a title block is: an EdgePath of four lines."""
    hatch = msp.add_hatch(color=2)
    path = hatch.paths.add_edge_path()
    corners = [(0, 0), (10, 0), (10, 6), (0, 6)]
    for a, b in zip(corners, corners[1:] + corners[:1]):
        path.add_line(a, b)
    return hatch


def test_a_nonassociative_hatch_shows_a_grip_on_every_boundary_corner():
    """Reference p. 873: "when you select a nonassociative hatch, both the
    control grip and the boundary grips are displayed".

    Marco selected the sheet's thick border -- a solid hatch -- and got no
    squares to drag. It had exactly one grip, at its centroid, which on a
    frame that big is nowhere near the corner you are pointing at.
    """
    doc = Document.new()
    edge = _rect_edge_hatch(doc.modelspace())
    poly = doc.modelspace().add_hatch(color=3)
    poly.paths.add_polyline_path([(0, 0), (4, 0), (4, 4)], is_closed=True)

    for hatch, corners in ((edge, 4), (poly, 3)):
        grips = entity_grips(hatch)
        roles = [g[2] for g in grips]
        assert roles[0] == "center", "the control grip must stay first"
        assert roles.count("vertex") == corners, roles
        # squares, not the round control grip -- that is what gets dragged
        assert set(roles[1:]) == {"vertex"}


def test_an_associative_hatch_keeps_only_its_control_grip():
    """Same page: an associative hatch's shape follows the objects it was
    built from, so AutoCAD offers no corner of its own to drag."""
    doc = Document.new()
    hatch = _rect_edge_hatch(doc.modelspace())
    hatch.dxf.associative = 1
    grips = entity_grips(hatch)
    assert [g[2] for g in grips] == ["center"]


def test_dragging_a_hatch_corner_keeps_the_boundary_closed():
    """A corner belongs to TWO edges. Moving one of them tears the loop
    open and the fill leaks; both have to travel together."""
    doc = Document.new()
    hatch = _rect_edge_hatch(doc.modelspace())
    assert _closed(hatch)
    before = _fingerprint(hatch)

    grips = entity_grips(hatch)
    x, y, role = grips[1]
    assert role == "vertex"
    snap = SnapshotCommand([hatch])
    assert apply_grip_edit(hatch, 1, role, (x + 3.0, y - 2.0)) is not False
    snap.commit(doc)

    assert _fingerprint(hatch) != before, "the drag changed nothing"
    assert _closed(hatch), "the corner moved one edge and tore the boundary"
    edges = list(hatch.paths[0].edges)
    touched = [e for e in edges
               if (e.start[0], e.start[1]) == (x + 3.0, y - 2.0)
               or (e.end[0], e.end[1]) == (x + 3.0, y - 2.0)]
    assert len(touched) == 2, "a corner moves exactly its own two edges"

    snap.undo(doc)
    assert _fingerprint(hatch) == before
    assert _closed(hatch)


def test_a_hatch_corner_grip_edits_the_corner_it_points_at():
    """The grip index IS the position in ``_hatch_vertices``' walk; if the
    two disagree, dragging one corner silently moves a different one."""
    doc = Document.new()
    hatch = _rect_edge_hatch(doc.modelspace())
    grips = entity_grips(hatch)
    assert len(grips) == 5, "no corners to walk — the test would prove nothing"
    for i in range(1, len(grips)):
        gx, gy, role = grips[i]
        apply_grip_edit(hatch, i, role, (gx + 100.0, gy + 100.0))
        moved = entity_grips(hatch)[i]
        assert (round(moved[0], 6), round(moved[1], 6)) \
            == (round(gx + 100.0, 6), round(gy + 100.0, 6)), \
            f"grip {i} moved some other corner"
