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
        return [[tuple(v)[:2] for v in getattr(p, "vertices", [])]
                for p in e.paths]
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
