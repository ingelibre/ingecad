# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Associative dimensions (DIMASSOC = 2): a dimension that follows its object.

AutoCAD ties each definition point of an associative dimension to a point
of an object -- the end of a line, the centre of a circle, the second
vertex of a polyline -- and re-measures the dimension whenever the object
changes. The tie lives in a DIMASSOC object in the dimension's extension
dictionary (key ``ACAD_DIMASSOC``), and the object lists the DIMASSOC in
its persistent reactors. Read from real drawings (ODA's DXF of 40 corpus
plans, 2026-10-10):

- ``90`` which definition points are tied, one bit each (see ``SLOTS``);
- one ``AcDbOsnapPointRef`` per bit, in bit order: ``72`` the object snap
  (``OSNAP``), ``331`` the object, ``73`` subentity type (2 = an edge),
  ``91`` the polyline segment (1-based), ``40`` where on the object (a
  fraction of a line, an angle on an arc), ``10`` the last point
  (``30 = 2e50``: none) and ``75`` "a last-point reference follows" -- the
  perpendicular snap's extra reference, which takes no bit of its own.

The object is kept as the tags it was read with, so a colleague's DIMASSOC
goes back out exactly as it came in. This module reads it, resolves each
reference against the object as it is now, creates new ones when a
dimension is placed on object snaps, and holds the reactor: after any
command, the dimensions whose objects changed are re-measured in the same
undo step (``History.reactor``).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from ezdxf.entities import DXFObject, factory
from ezdxf.entities.dxfentity import SubclassProcessor, base_class
from ezdxf.entities.dxfns import DXFNamespace
from ezdxf.lldxf import const
from ezdxf.lldxf.attributes import DXFAttributes
from ezdxf.lldxf.tags import Tags
from ezdxf.lldxf.types import DXFTag, DXFVertex

XDICT_KEY = "ACAD_DIMASSOC"
REF_CLASS = "AcDbOsnapPointRef"

#: AutoCAD's object snap codes (72), and IngeCAD's snap kinds for them.
OSNAP = {"END": 1, "MID": 2, "CEN": 3, "NOD": 4, "QUA": 5, "INT": 6,
         "INS": 7, "PER": 8, "TAN": 9, "NEA": 10}
START = 13          # the start point of a curve (an END at its start)
APPINT = 11         # apparent intersection
NO_POINT = 2e50     # "no last point" in the 30 of a reference

#: Which definition point each bit of 90 ties, per dimension type.
SLOTS = {
    0: {1: "defpoint2", 2: "defpoint3"},                    # linear
    1: {1: "defpoint2", 2: "defpoint3"},                    # aligned
    2: {1: "defpoint2", 2: "defpoint3", 4: "defpoint4", 8: "defpoint"},
    5: {1: "defpoint2", 2: "defpoint3", 4: "defpoint4"},    # angular 3-point
    6: {2: "defpoint2"},                                    # ordinate
    8: {1: "defpoint2", 2: "defpoint3", 4: "defpoint4"},    # arc length
}
RADIAL = (3, 4)      # diameter, radius: bit 2 ties the whole circle


# -- the DIMASSOC object ---------------------------------------------------------

@dataclass
class Reference:
    """One AcDbOsnapPointRef."""

    osnap: int
    handles: list = field(default_factory=list)      # 331: the object (path)
    subent: int = 2
    gsmarker: int = 0
    param: float = 0.0
    last_point: Optional[tuple] = None
    has_last: bool = False
    others: list = field(default_factory=list)       # 332: intersection object
    #: the reference after one with has_last: where a perpendicular is
    #: dropped FROM (osnap 0 = the fixed point in its 10)
    companion: Optional["Reference"] = None

    @property
    def handle(self) -> Optional[str]:
        """The object itself: the last of the path (the rest are blocks)."""
        return self.handles[-1] if self.handles else None


class DimAssoc(DXFObject):
    """DXF DIMASSOC object, kept as its tags."""

    DXFTYPE = "DIMASSOC"
    DXFATTRIBS = DXFAttributes(base_class)
    MIN_DXF_VERSION_FOR_EXPORT = const.DXF2000

    def __init__(self) -> None:
        super().__init__()
        self.tags = Tags()       # the AcDbDimAssoc subclass, marker excluded

    def copy_data(self, entity, copy_strategy=None) -> None:
        # a copy of the dimension alone is not tied to anything (AutoCAD:
        # copying a dimension without its object leaves it non-associative)
        from ezdxf.entities.copy import CopyNotSupported

        raise CopyNotSupported("DIMASSOC is not copied")

    def load_dxf_attribs(self, processor: Optional[SubclassProcessor] = None
                         ) -> DXFNamespace:
        dxf = super().load_dxf_attribs(processor)
        if processor is not None and len(processor.subclasses) > 1:
            self.tags = Tags(processor.subclasses[1][1:])
        return dxf

    def export_entity(self, tagwriter) -> None:
        super().export_entity(tagwriter)
        tagwriter.write_tag2(const.SUBCLASS_MARKER, "AcDbDimAssoc")
        tagwriter.write_tags(self.tags)

    # -- reading -----------------------------------------------------------------
    def _first(self, code, default=None):
        for tag in self.tags:
            if tag.code == code:
                return tag.value
        return default

    @property
    def dimension_handle(self) -> Optional[str]:
        return self._first(330)

    @property
    def bits(self) -> int:
        return int(self._first(90, 0))

    @property
    def trans_space(self) -> bool:
        return bool(self._first(70, 0))

    def references(self) -> list[tuple[int, Reference]]:
        """(bit, reference) in the file's order; a perpendicular's extra
        last-point reference rides with bit 0."""
        refs: list[Reference] = []
        current = None
        for tag in self.tags:
            code, value = tag.code, tag.value
            if code == 1:
                current = Reference(osnap=0)
                refs.append(current)
                continue
            if current is None:
                continue
            if code == 72:
                current.osnap = int(value)
            elif code == 331:
                current.handles.append(value)
            elif code == 332:
                current.others.append(value)
            elif code == 73:
                current.subent = int(value)
            elif code == 91:
                current.gsmarker = int(value)
            elif code == 40:
                current.param = float(value)
            elif code == 10:
                current.last_point = tuple(value)
            elif code == 75:
                current.has_last = bool(value)
        out = []
        bits = [b for b in (1, 2, 4, 8, 16, 32) if self.bits & b]
        previous = None
        for ref in refs:
            if previous is not None and previous.has_last:
                previous.companion = ref
                out.append((0, ref))
            elif bits:
                out.append((bits.pop(0), ref))
            previous = ref
        return out

    # -- writing -----------------------------------------------------------------
    def set_content(self, dimension_handle: str, refs: dict[int, Reference],
                    rotated_type: int = 0, trans_space: bool = False) -> None:
        tags = [DXFTag(330, dimension_handle), DXFTag(90, sum(refs)),
                DXFTag(70, int(trans_space)), DXFTag(71, int(rotated_type))]
        for bit in sorted(refs):
            ref = refs[bit]
            tags += [DXFTag(1, REF_CLASS), DXFTag(72, ref.osnap)]
            tags += [DXFTag(331, h) for h in ref.handles]
            tags += [DXFTag(73, ref.subent), DXFTag(91, ref.gsmarker),
                     DXFTag(40, float(ref.param))]
            point = ref.last_point or (0.0, 0.0, NO_POINT)
            tags.append(DXFVertex(10, (float(point[0]), float(point[1]),
                                       float(point[2]) if len(point) > 2 else 0.0)))
            tags.append(DXFTag(75, int(ref.has_last)))
        self.tags = Tags(tags)

    def without_bits(self, drop: int) -> Tags:
        """The tags with the references of ``drop`` removed (and their
        last-point companions); 90 updated."""
        keep = [(bit, ref) for bit, ref in self.references()]
        refs, last_bit = {}, None
        for bit, ref in keep:
            if bit == 0:
                continue
            last_bit = bit
            if not bit & drop:
                refs[bit] = ref
        del last_bit
        copy = DimAssoc()
        copy.set_content(self.dimension_handle, refs,
                         int(self._first(71, 0)), self.trans_space)
        return copy.tags


factory.register_entity(DimAssoc)


class _QuietUntiedCopy:
    """ezdxf logs "copy process ignored DIMASSOC(...)" for every associative
    dimension copied (COPY, Ctrl+C, an undo snapshot): it is the intended
    outcome -- a dimension copied without its object is not tied to it, as
    in AutoCAD -- and on a real plan it filled the console by the hundred."""

    def filter(self, record) -> bool:
        return not str(record.getMessage()).startswith("copy process ignored DIMASSOC")


import logging  # noqa: E402

logging.getLogger("ezdxf").addFilter(_QuietUntiedCopy())


# -- finding them ------------------------------------------------------------------

def of_dimension(dim) -> Optional[DimAssoc]:
    """The DIMASSOC of ``dim``, when it has one."""
    if not dim.has_extension_dict:
        return None
    try:
        xdict = dim.get_extension_dict()
        handle = xdict.dictionary.get(XDICT_KEY)
    except Exception:  # noqa: BLE001 - a damaged dictionary is no tie
        return None
    if handle is None:
        return None
    if isinstance(handle, str):
        handle = dim.doc.entitydb.get(handle) if dim.doc else None
    return handle if isinstance(handle, DimAssoc) and handle.is_alive else None


def associations(document) -> list[tuple[object, DimAssoc]]:
    """(dimension, DIMASSOC) for every live associative dimension."""
    doc = document.doc
    out = []
    for obj in doc.objects.query("DIMASSOC"):
        if not isinstance(obj, DimAssoc) or not obj.is_alive:
            continue
        dim = doc.entitydb.get(obj.dimension_handle or "")
        if dim is not None and dim.is_alive and dim.dxftype() == "DIMENSION":
            out.append((dim, obj))
    return out


# -- where a reference is now --------------------------------------------------------

def _wcs(entity, point):
    from core import ocs

    return ocs.points_wcs(entity, [point])[0]


def _arc_point(cx, cy, r, angle):
    return (cx + r * math.cos(angle), cy + r * math.sin(angle))


def _polyline_vertices(entity):
    """(points in WCS, bulges, closed) for LWPOLYLINE and 2D POLYLINE."""
    from core import ocs

    if entity.dxftype() == "LWPOLYLINE":
        raw = list(entity.get_points("xyb"))
        pts = ocs.points_wcs(entity, [(p[0], p[1]) for p in raw])
        return pts, [p[2] for p in raw], bool(entity.closed)
    vertices = list(entity.vertices)
    pts = [(v.dxf.location.x, v.dxf.location.y) for v in vertices]
    if not entity.is_3d_polyline:
        pts = ocs.points_wcs(entity, pts)
    return pts, [v.dxf.get("bulge", 0.0) for v in vertices], bool(entity.is_closed)


def _segment(entity, gsmarker):
    """(start, end, bulge) of polyline segment ``gsmarker`` (1-based)."""
    pts, bulges, closed = _polyline_vertices(entity)
    n = len(pts)
    count = n if closed else n - 1
    index = (gsmarker or 1) - 1
    if not 0 <= index < count:
        return None
    return pts[index], pts[(index + 1) % n], bulges[index] or 0.0


def _bulge_arc(a, b, bulge):
    """(cx, cy, r, start angle, sweep) of a bulged segment."""
    theta = 4.0 * math.atan(bulge)
    chord = math.hypot(b[0] - a[0], b[1] - a[1])
    r = chord / (2.0 * math.sin(theta / 2.0))
    mx, my = (a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0
    d = r * math.cos(theta / 2.0)
    ux, uy = (b[0] - a[0]) / chord, (b[1] - a[1]) / chord
    cx, cy = mx - uy * d, my + ux * d
    start = math.atan2(a[1] - cy, a[0] - cx)
    return cx, cy, abs(r), start, theta


def _on_segment(a, b, bulge, t):
    if abs(bulge) < 1e-12:
        return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
    cx, cy, r, start, sweep = _bulge_arc(a, b, bulge)
    return _arc_point(cx, cy, r, start + sweep * t)


def resolve(entity, ref: Reference, near=None):
    """Where ``ref`` sits on ``entity`` now, or None when IngeCAD cannot
    tell (an object kind or snap it does not follow: left as it is)."""
    from core import ocs

    if entity is None or not entity.is_alive:
        return None
    kind = entity.dxftype()
    snap = ref.osnap
    if kind == "LINE":
        s, e = entity.dxf.start, entity.dxf.end
        s, e = (s.x, s.y), (e.x, e.y)
        if snap == START:
            return s
        if snap == OSNAP["END"]:
            return e if ref.param >= 0.5 else s
        if snap == OSNAP["MID"]:
            return ((s[0] + e[0]) / 2, (s[1] + e[1]) / 2)
        if snap in (OSNAP["NEA"], OSNAP["PER"]):
            return _on_segment(s, e, 0.0, ref.param)
        return None
    if kind in ("ARC", "CIRCLE"):
        c = ocs.center_wcs(entity)
        r = entity.dxf.radius
        if snap == OSNAP["CEN"]:
            return (c.x, c.y)
        if kind == "ARC":
            a0, a1 = (math.radians(a) for a in ocs.angles_wcs(entity))
            if snap == START:
                return _arc_point(c.x, c.y, r, a0)
            if snap == OSNAP["END"]:
                return _arc_point(c.x, c.y, r, a1)
            if snap == OSNAP["MID"]:
                sweep = (a1 - a0) % (2 * math.pi)
                return _arc_point(c.x, c.y, r, a0 + sweep / 2)
        if snap in (OSNAP["QUA"], OSNAP["NEA"], OSNAP["PER"]):
            return _arc_point(c.x, c.y, r, ref.param)
        return None
    if kind in ("LWPOLYLINE", "POLYLINE"):
        seg = _segment(entity, ref.gsmarker)
        if seg is None:
            return None
        a, b, bulge = seg
        if snap == START:
            return a
        if snap == OSNAP["END"]:
            return b if ref.param >= 0.5 else a
        if snap == OSNAP["MID"]:
            return _on_segment(a, b, bulge, 0.5)
        if snap in (OSNAP["NEA"], OSNAP["PER"]):
            return _on_segment(a, b, bulge, ref.param)
        if snap == OSNAP["CEN"] and abs(bulge) > 1e-12:
            cx, cy, *_ = _bulge_arc(a, b, bulge)
            return (cx, cy)
        return None
    return None


def _primitives(entity):
    """('seg', (a, b)) and ('circle', (c, r)) pieces of a curve; arcs are
    whole circles here, the nearest crossing picks the right one."""
    from core import ocs

    kind = entity.dxftype()
    if kind == "LINE":
        s, e = entity.dxf.start, entity.dxf.end
        return [("seg", ((s.x, s.y), (e.x, e.y)))]
    if kind in ("ARC", "CIRCLE"):
        c = ocs.center_wcs(entity)
        return [("circle", ((c.x, c.y), entity.dxf.radius))]
    if kind in ("LWPOLYLINE", "POLYLINE"):
        pts, bulges, closed = _polyline_vertices(entity)
        n = len(pts)
        out = []
        for i in range(n if closed else n - 1):
            a, b, bulge = pts[i], pts[(i + 1) % n], bulges[i] or 0.0
            if abs(bulge) < 1e-12:
                out.append(("seg", (a, b)))
            else:
                cx, cy, r, *_ = _bulge_arc(a, b, bulge)
                out.append(("circle", ((cx, cy), r)))
        return out
    return []


def _crossings(p, q):
    """Crossing points of two primitives (lines taken as infinite)."""
    (kp, gp), (kq, gq) = p, q
    if kp == "seg" and kq == "seg":
        (x1, y1), (x2, y2) = gp
        (x3, y3), (x4, y4) = gq
        den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        if abs(den) < 1e-12:
            return []
        t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / den
        return [(x1 + t * (x2 - x1), y1 + t * (y2 - y1))]
    if kp == "circle" and kq == "circle":
        (c1, r1), (c2, r2) = gp, gq
        dx, dy = c2[0] - c1[0], c2[1] - c1[1]
        d = math.hypot(dx, dy)
        if d == 0 or d > r1 + r2 + 1e-9 or d < abs(r1 - r2) - 1e-9:
            return []
        a = (r1 * r1 - r2 * r2 + d * d) / (2 * d)
        h = math.sqrt(max(r1 * r1 - a * a, 0.0))
        mx, my = c1[0] + a * dx / d, c1[1] + a * dy / d
        return [(mx + h * dy / d, my - h * dx / d), (mx - h * dy / d, my + h * dx / d)]
    (a, b), (c, r) = (gp, gq) if kp == "seg" else (gq, gp)
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    if length == 0:
        return []
    ux, uy = dx / length, dy / length
    t0 = (c[0] - a[0]) * ux + (c[1] - a[1]) * uy
    fx, fy = a[0] + t0 * ux, a[1] + t0 * uy
    dist = math.hypot(c[0] - fx, c[1] - fy)
    if dist > r + 1e-9:
        return []
    h = math.sqrt(max(r * r - dist * dist, 0.0))
    return [(fx - h * ux, fy - h * uy), (fx + h * ux, fy + h * uy)]


def _intersection(doc, ref: Reference, near):
    """INT / apparent intersection of the two objects, the crossing nearest
    to where the dimension point was (lines extended, as the snap does)."""
    first = doc.entitydb.get(ref.handle or "")
    second = doc.entitydb.get(ref.others[-1]) if ref.others else None
    if first is None or second is None or not (first.is_alive and second.is_alive):
        return None
    points = []
    try:
        for p in _primitives(first):
            for q in _primitives(second):
                points.extend(_crossings(p, q))
    except Exception:  # noqa: BLE001
        return None
    if not points:
        return None
    near = near if near is not None else points[0]
    best = min(points, key=lambda pt: math.hypot(pt[0] - near[0], pt[1] - near[1]))
    return (float(best[0]), float(best[1]))


def _foot(entity, ref: Reference, point):
    """The perpendicular from ``point`` onto the object (its line, the
    segment's line, or the circle's radius through the point)."""
    from core import ocs

    kind = entity.dxftype()
    if kind == "LINE":
        s, e = entity.dxf.start, entity.dxf.end
        seg = ((s.x, s.y), (e.x, e.y), 0.0)
    elif kind in ("LWPOLYLINE", "POLYLINE"):
        seg = _segment(entity, ref.gsmarker)
        if seg is None:
            return None
    elif kind in ("ARC", "CIRCLE"):
        c = ocs.center_wcs(entity)
        angle = math.atan2(point[1] - c.y, point[0] - c.x)
        return _arc_point(c.x, c.y, entity.dxf.radius, angle)
    else:
        return None
    a, b, bulge = seg
    if abs(bulge) > 1e-12:
        cx, cy, r, *_ = _bulge_arc(a, b, bulge)
        return _arc_point(cx, cy, r, math.atan2(point[1] - cy, point[0] - cx))
    return _on_segment(a, b, 0.0, _param_on(a, b, 0.0, point))


def where(doc, ref: Reference, near=None, _depth: int = 0):
    """The point of ``ref`` in ``doc``; None when it cannot be followed."""
    if ref.osnap == 0:
        point = ref.last_point
        if point is None or (len(point) > 2 and point[2] >= NO_POINT / 2):
            return None
        return (point[0], point[1])
    if len(ref.handles) > 1:
        return None                       # inside a block: not followed yet
    entity = doc.entitydb.get(ref.handle or "")
    if ref.osnap in (OSNAP["INT"], APPINT):
        if ref.others:
            return _intersection(doc, ref, near)
        # an apparent intersection taken on one object: its end
        return resolve(entity, Reference(START if ref.param < 0.5 else OSNAP["END"],
                                         ref.handles, ref.subent, ref.gsmarker,
                                         ref.param), near)
    # dropped from an object's point: AutoCAD re-solves the foot (its 40
    # goes stale). From a fixed point (osnap 0) the 10 is not in drawing
    # coordinates in real files (1382,531 on a 12-unit plan): keep the 40.
    if (ref.osnap == OSNAP["PER"] and ref.companion is not None
            and ref.companion.osnap != 0 and _depth < 4):
        origin = where(doc, ref.companion, near, _depth + 1)
        if origin is not None and entity is not None and entity.is_alive:
            return _foot(entity, ref, origin)
    return resolve(entity, ref, near)


def _xy(vec):
    return (vec.x, vec.y) if hasattr(vec, "x") else (vec[0], vec[1])


def updated_points(dim, assoc: DimAssoc) -> dict:
    """{definition point: where its object says it is now}, for the tied
    points IngeCAD can follow."""
    doc = dim.doc
    kind = int(dim.dxf.get("dimtype", 0)) & 15
    out = {}
    if kind in RADIAL:
        for bit, ref in assoc.references():
            if bit != 2:
                continue
            circle = doc.entitydb.get(ref.handle or "")
            if circle is None or not circle.is_alive \
                    or circle.dxftype() not in ("CIRCLE", "ARC"):
                continue
            from core import ocs

            c = ocs.center_wcs(circle)
            r = circle.dxf.radius
            far = _xy(dim.dxf.defpoint4)
            centre = _xy(dim.dxf.defpoint)
            if kind == 3:                 # diameter: defpoint is the far end
                centre = ((far[0] + centre[0]) / 2, (far[1] + centre[1]) / 2)
            angle = math.atan2(far[1] - centre[1], far[0] - centre[0])
            new_far = _arc_point(c.x, c.y, r, angle)
            out["defpoint4"] = new_far
            out["defpoint"] = ((c.x, c.y) if kind == 4
                               else _arc_point(c.x, c.y, r, angle + math.pi))
        return out
    slots = SLOTS.get(kind, {})
    for bit, ref in assoc.references():
        attr = slots.get(bit)
        if attr is None or not dim.dxf.hasattr(attr):
            continue
        point = where(doc, ref, near=_xy(dim.dxf.get(attr)))
        if point is not None:
            out[attr] = point
    return out


def tied_handles(assoc: DimAssoc) -> set:
    handles = set()
    for _bit, ref in assoc.references():
        handles.update(ref.handles[-1:])
        handles.update(ref.others[-1:])
    return handles


# -- creating them -------------------------------------------------------------------

def reference_at(document, point, kind: str, candidates, tolerance: float):
    """The AcDbOsnapPointRef for a point placed with object snap ``kind``
    on one of ``candidates`` (entities near the point), or None."""
    code = OSNAP.get(kind)
    if code is None:
        return None
    x, y = point
    best = None
    for entity in candidates:
        for ref in _candidate_refs(entity, code, (x, y)):
            p = resolve(entity, ref)
            if p is None:
                continue
            d = math.hypot(p[0] - x, p[1] - y)
            if d <= tolerance and (best is None or d < best[0]):
                best = (d, ref)
    return best[1] if best is not None else None


def _param_on(a, b, bulge, point):
    if abs(bulge) < 1e-12:
        dx, dy = b[0] - a[0], b[1] - a[1]
        length2 = dx * dx + dy * dy
        if length2 == 0:
            return 0.0
        return ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / length2
    cx, cy, _r, start, sweep = _bulge_arc(a, b, bulge)
    angle = math.atan2(point[1] - cy, point[0] - cx)
    delta = (angle - start) % (2 * math.pi) if sweep > 0 \
        else -((start - angle) % (2 * math.pi))
    return delta / sweep if sweep else 0.0


def _candidate_refs(entity, code, point):
    """Every reference of snap ``code`` the entity could give at point."""
    kind = entity.dxftype()
    handle = entity.dxf.handle
    end, mid, cen, near, per, qua = (OSNAP[k] for k in
                                     ("END", "MID", "CEN", "NEA", "PER", "QUA"))
    if kind == "LINE":
        if code == end:
            yield Reference(START, [handle], param=0.0)
            yield Reference(end, [handle], param=1.0)
        elif code == mid:
            yield Reference(mid, [handle], param=0.5)
        elif code in (near, per):
            s, e = entity.dxf.start, entity.dxf.end
            yield Reference(code, [handle],
                            param=_param_on((s.x, s.y), (e.x, e.y), 0.0, point))
        return
    if kind in ("ARC", "CIRCLE"):
        from core import ocs

        c = ocs.center_wcs(entity)
        angle = math.atan2(point[1] - c.y, point[0] - c.x)
        if code == cen:
            yield Reference(cen, [handle])
        elif kind == "ARC" and code == end:
            a0, a1 = (math.radians(a) for a in ocs.angles_wcs(entity))
            yield Reference(START, [handle], param=a0)
            yield Reference(end, [handle], param=a1)
        elif kind == "ARC" and code == mid:
            yield Reference(mid, [handle])
        elif code in (qua, near, per):
            yield Reference(code, [handle], param=angle)
        return
    if kind in ("LWPOLYLINE", "POLYLINE"):
        pts, bulges, closed = _polyline_vertices(entity)
        n = len(pts)
        for index in range(n if closed else n - 1):
            a, b, bulge = pts[index], pts[(index + 1) % n], bulges[index] or 0.0
            g = index + 1
            if code == end:
                yield Reference(START, [handle], gsmarker=g, param=0.0)
                yield Reference(end, [handle], gsmarker=g, param=1.0)
            elif code == mid:
                yield Reference(mid, [handle], gsmarker=g, param=0.5)
            elif code == cen and abs(bulge) > 1e-12:
                yield Reference(cen, [handle], gsmarker=g)
            elif code in (near, per):
                yield Reference(code, [handle], gsmarker=g,
                                param=_param_on(a, b, bulge, point))


def intersection_reference(first, second):
    """INT on two objects: AutoCAD's 72 = 6 with both of them."""
    return Reference(OSNAP["INT"], [first.dxf.handle], others=[second.dxf.handle])


# -- tying and untying ---------------------------------------------------------------

def attach(document, dim, refs: dict) -> Optional[DimAssoc]:
    """Tie ``dim``'s definition points to objects: {bit: Reference}."""
    if not refs:
        return None
    doc = document.doc
    doc.classes.add_class("DIMASSOC")
    xdict = (dim.get_extension_dict() if dim.has_extension_dict
             else dim.new_extension_dict())
    owner = xdict.dictionary.dxf.handle
    assoc = doc.objects.new_entity("DIMASSOC", {"owner": owner})
    assoc.set_reactors([owner])
    assoc.set_content(dim.dxf.handle, refs)
    xdict.dictionary[XDICT_KEY] = assoc
    for handle in tied_handles(assoc):
        entity = doc.entitydb.get(handle)
        if entity is not None and entity.is_alive:
            entity.append_reactor_handle(assoc.dxf.handle)
    _bump(document)
    return assoc


def detach(document, dim) -> Optional[Tags]:
    """Untie ``dim``; the tags it had (for an undo to tie it again)."""
    assoc = of_dimension(dim)
    if assoc is None:
        return None
    doc = document.doc
    tags = Tags(assoc.tags)
    for handle in tied_handles(assoc):
        entity = doc.entitydb.get(handle)
        if entity is not None and entity.is_alive:
            entity.discard_reactor_handle(assoc.dxf.handle)
    try:
        dim.get_extension_dict().dictionary.discard(XDICT_KEY)
    except Exception:  # noqa: BLE001
        pass
    doc.objects.delete_entity(assoc)
    _bump(document)
    return tags


def _refs_from_tags(tags: Tags) -> dict:
    probe = DimAssoc()
    probe.tags = Tags(tags)
    return {bit: ref for bit, ref in probe.references() if bit}


def _bump(document) -> None:
    document.dimassoc_epoch = getattr(document, "dimassoc_epoch", 0) + 1


def _cached(document) -> list:
    epoch = getattr(document, "dimassoc_epoch", 0)
    cache = getattr(document, "_dimassoc_cache", None)
    if cache is None or cache[0] != epoch or cache[1] is not document.doc:
        cache = (epoch, document.doc, associations(document))
        document._dimassoc_cache = cache
    return [(d, a) for d, a in cache[2] if d.is_alive and a.is_alive]


def dimassoc_mode(document) -> int:
    """$DIMASSOC: 2 associative, 1 not, 0 exploded (AutoCAD's default 2)."""
    try:
        return int(document.doc.header.get("$DIMASSOC", 2))
    except (TypeError, ValueError):
        return 2


# -- the reactor ----------------------------------------------------------------------

def _fingerprint(entity):
    if entity is None or not entity.is_alive:
        return None
    kind = entity.dxftype()
    dxf = entity.dxf
    try:
        if kind == "LINE":
            return (tuple(dxf.start), tuple(dxf.end))
        if kind == "CIRCLE":
            return (tuple(dxf.center), dxf.radius, tuple(dxf.get("extrusion", (0, 0, 1))))
        if kind == "ARC":
            return (tuple(dxf.center), dxf.radius, dxf.start_angle, dxf.end_angle,
                    tuple(dxf.get("extrusion", (0, 0, 1))))
        if kind == "LWPOLYLINE":
            return (tuple(map(tuple, entity.get_points("xyb"))), entity.closed,
                    dxf.get("elevation", 0.0), tuple(dxf.get("extrusion", (0, 0, 1))))
        if kind == "POLYLINE":
            return (tuple((tuple(v.dxf.location), v.dxf.get("bulge", 0.0))
                          for v in entity.vertices), entity.is_closed)
    except Exception:  # noqa: BLE001
        return ("?",)
    return (kind,)


def _dim_points(dim):
    return tuple((attr, _xy(dim.dxf.get(attr))) for attr in
                 ("defpoint", "defpoint2", "defpoint3", "defpoint4")
                 if dim.dxf.hasattr(attr))


def before(document):
    """What the reactor compares after a command; None when no dimension
    of the drawing is associative (then a command pays nothing)."""
    pairs = _cached(document)
    if not pairs:
        return None
    geometry = {}
    dims = {}
    for dim, assoc in pairs:
        dims[dim.dxf.handle] = _dim_points(dim)
        for handle in tied_handles(assoc):
            if handle not in geometry:
                geometry[handle] = _fingerprint(document.doc.entitydb.get(handle))
    return geometry, dims


def _close(p, q, tol=1e-9) -> bool:
    return abs(p[0] - q[0]) <= tol * max(1.0, abs(p[0])) \
        and abs(p[1] - q[1]) <= tol * max(1.0, abs(p[1]))


def react(document, state):
    """The command that keeps the associative dimensions true after an edit
    (or None): re-measure those whose objects moved; untie the points of
    one moved by itself, as AutoCAD does."""
    if state is None:
        return None
    geometry, dims = state
    db = document.doc.entitydb
    changed = {h for h, fp in geometry.items() if _fingerprint(db.get(h)) != fp}
    updates, untie = [], []
    for dim, assoc in _cached(document):
        handle = dim.dxf.handle
        if handle not in dims:
            continue
        tied = tied_handles(assoc)
        new = updated_points(dim, assoc)
        if tied & changed:
            points = {a: p for a, p in new.items() if not _close(p, _xy(dim.dxf.get(a)))}
            if points:
                updates.append((dim, points))
            continue
        if _dim_points(dim) == dims[handle]:
            continue
        # the dimension moved and its objects did not: the points that left
        # their object are not tied any more
        kind = int(dim.dxf.get("dimtype", 0)) & 15
        slots = SLOTS.get(kind, {})
        drop = 0
        for bit, _ref in assoc.references():
            attr = slots.get(bit) if kind not in RADIAL else "defpoint4"
            if bit and attr in new and not _close(new[attr], _xy(dim.dxf.get(attr)), 1e-7):
                drop |= bit
        if drop:
            untie.append((dim, drop))
    if not updates and not untie:
        return None
    return DimAssocReaction(updates, untie)


class DimAssocReaction:
    """Re-measures and unties, done and undone with the command that caused
    them (``History`` runs it as that command's follow-up)."""

    name = "DIMASSOC"
    needs_regen = False

    def __init__(self, updates, untie) -> None:
        from core.actions import DimGripCommand

        self.grips = [DimGripCommand.many(dim, points) for dim, points in updates]
        self.untie = untie
        self._before_tags: list = []

    @property
    def entities(self) -> list:
        return [g.dim for g in self.grips]

    def do(self, document) -> None:
        for grip in self.grips:
            grip.do(document)
        self._before_tags = []
        for dim, drop in self.untie:
            assoc = of_dimension(dim)
            if assoc is None:
                continue
            self._before_tags.append((dim, Tags(assoc.tags)))
            remaining = assoc.bits & ~drop
            if remaining:
                assoc.tags = assoc.without_bits(drop)
            else:
                detach(document, dim)
        _bump(document)

    def undo(self, document) -> None:
        for dim, tags in reversed(self._before_tags):
            assoc = of_dimension(dim)
            if assoc is not None:
                assoc.tags = tags
            else:
                attach(document, dim, _refs_from_tags(tags))
        for grip in reversed(self.grips):
            grip.undo(document)
        _bump(document)
