# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Annotative scaling as AutoCAD stores it: read the scale representations.

An annotative object is defined at a paper size and carries one *scale
representation* per annotation scale it supports; model space and every
layout viewport each have one current annotation scale, and the object is
shown through the representation for that scale (AutoCAD Command Reference,
glossary p. 2645/2671). Nothing here is IngeCAD's own format -- every piece
is read where AutoCAD writes it, so a colleague's drawing round-trips as it
came (measured on the corpus: docs/reference/annotative/):

* the flag: XDATA ``AcadAnnotative`` = ``AnnotativeData { 1070 1, 1070 flag }``
  -- present with flag 0 on many objects, so presence alone means nothing;
* the representations: entity -> extension dictionary ->
  ``AcDbContextDataManager`` -> ``ACDB_ANNOTATIONSCALES`` -> one
  ``ACDB_*OBJECTCONTEXTDATA_CLASS`` object per scale, each pointing (340) at
  a SCALE in the ``ACAD_SCALELIST`` dictionary. The entity's own fields
  always mirror the representation flagged as default (290 = 1);
* CANNOSCALE: by *name*, in the ``AcDbVariableDictionary``;
* a layout viewport's scale: XRECORD ``ASDK_XREC_ANNOTATION_SCALE_INFO`` in
  its extension dictionary, pointing (340) at a SCALE. It is its own
  property: on 457 of 707 real viewports it is NOT the viewport's zoom;
* ANNOALLVISIBLE, saved per model space and per layout: XDATA ``AcadAnnoAV``
  on the LAYOUT object, default 1.

TEXT and MTEXT representations store no height: it follows from the scale,
``height x factor(scale) / factor(default)`` (exactly x6.000 between 1:1250
and 1:7500 on a real file).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

ANNO_APPID = "AcadAnnotative"
ALL_VISIBLE_APPID = "AcadAnnoAV"
SCALE_INFO_KEY = "ASDK_XREC_ANNOTATION_SCALE_INFO"
CONTEXT_MANAGER_KEY = "AcDbContextDataManager"
SCALES_KEY = "ACDB_ANNOTATIONSCALES"
_BODY_MARKER = "AcDbAnnotScaleObjectContextData"


@dataclass(frozen=True)
class Scale:
    """One entry of the drawing's scale list (a SCALE object)."""

    handle: str
    name: str
    paper: float
    drawing: float

    @property
    def factor(self) -> float:
        """Drawing units per paper unit: how much bigger than its paper size
        an annotation is drawn at this scale."""
        return self.drawing / self.paper if self.paper else 1.0


@dataclass(frozen=True)
class Representation:
    """One scale representation of an annotative object."""

    scale: Scale
    is_default: bool
    #: the class body: every tag after the annot-scale marker, 340 excluded
    tags: tuple = field(repr=False)

    def first(self, code: int, default=None):
        return next((v for c, v in self.tags if c == code), default)

    def all(self, code: int) -> list:
        return [v for c, v in self.tags if c == code]


def _subclass_tags(obj) -> list[list]:
    xtags = getattr(obj, "xtags", None)
    if xtags is None:
        return []
    return [[(t.code, t.value) for t in sub] for sub in xtags.subclasses]


def scale_from_object(obj) -> Optional[Scale]:
    if obj is None or obj.dxftype() != "SCALE":
        return None
    values = {}
    for sub in _subclass_tags(obj):
        for code, value in sub:
            values.setdefault(code, value)
    try:
        return Scale(obj.dxf.handle, str(values.get(300, "")),
                     float(values.get(140, 1.0)), float(values.get(141, 1.0)))
    except (TypeError, ValueError):
        return None


def scale_by_handle(doc, handle) -> Optional[Scale]:
    if not handle:
        return None
    return scale_from_object(doc.entitydb.get(handle))


def scale_list(doc) -> list[Scale]:
    """The drawing's named scales, in dictionary order."""
    scales = doc.rootdict.get("ACAD_SCALELIST")
    if scales is None:
        return []
    out = []
    for _key, obj in scales.items():
        scale = scale_from_object(obj)
        if scale is not None:
            out.append(scale)
    return out


def find_scale(doc, name: str) -> Optional[Scale]:
    return next((s for s in scale_list(doc) if s.name == name), None)


def is_annotative(entity) -> bool:
    """True when the object is annotative (the flag, not mere presence)."""
    dxftype = entity.dxftype()
    if dxftype in ("MULTILEADER", "MLEADER"):
        return bool(entity.dxf.get("is_annotative", 0))
    if not entity.has_xdata(ANNO_APPID):
        return False
    ints = [t.value for t in entity.get_xdata(ANNO_APPID) if t.code == 1070]
    return len(ints) >= 2 and ints[1] == 1


def _xdict_get(entity, key):
    if not entity.has_extension_dict:
        return None
    try:
        xdict = entity.get_extension_dict()
        return xdict[key] if key in xdict else None
    except Exception:
        return None


def representations(entity) -> list[Representation]:
    """Every scale representation the object carries (empty if none)."""
    manager = _xdict_get(entity, CONTEXT_MANAGER_KEY)
    if manager is None or SCALES_KEY not in manager:
        return []
    doc = entity.doc
    out = []
    for _key, obj in manager[SCALES_KEY].items():
        subs = _subclass_tags(obj)
        if not subs:
            continue    # a dangling entry: the context object is gone
        is_default = False
        body: list = []
        in_body = False
        scale_handle = None
        for sub in subs[1:]:
            for code, value in sub:
                if code == 100:
                    in_body = in_body or value == _BODY_MARKER
                    continue
                if not in_body:
                    if code == 290:
                        is_default = bool(value)
                    continue
                if code == 340 and scale_handle is None:
                    scale_handle = value
                    continue
                body.append((code, value))
        scale = scale_by_handle(doc, scale_handle)
        if scale is not None:
            out.append(Representation(scale, is_default, tuple(body)))
    return out


def _variable(doc, name: str) -> Optional[str]:
    variables = doc.rootdict.get("AcDbVariableDictionary")
    if variables is None or name not in variables:
        return None
    try:
        return str(variables.get(name).dxf.value)
    except Exception:
        return None


def current_scale(doc) -> Optional[Scale]:
    """CANNOSCALE: the annotation scale of model space."""
    name = _variable(doc, "CANNOSCALE")
    return find_scale(doc, name) if name else None


def viewport_scale(viewport) -> Optional[Scale]:
    """The annotation scale a layout viewport shows annotations at."""
    record = _xdict_get(viewport, SCALE_INFO_KEY)
    if record is None or record.dxftype() != "XRECORD":
        return None
    handle = next((t.value for t in record.tags if t.code == 340), None)
    return scale_by_handle(viewport.doc, handle)


def all_visible(layout) -> bool:
    """ANNOALLVISIBLE of a space (its LAYOUT object); AutoCAD's default is 1."""
    try:
        obj = layout.dxf_layout
    except AttributeError:
        obj = layout
    try:
        if obj.has_xdata(ALL_VISIBLE_APPID):
            ints = [t.value for t in obj.get_xdata(ALL_VISIBLE_APPID)
                    if t.code == 1070]
            if ints:
                return ints[0] != 0
    except Exception:
        pass
    return True


def has_annotative(space) -> bool:
    """Does ``space`` (a layout or block) hold any annotative object?"""
    return any(is_annotative(e) for e in space)


# -- picking the representation to draw ---------------------------------------

#: returned by :func:`representation_for` when the object must not be drawn
HIDDEN = object()


def representation_for(entity, scale: Optional[Scale],
                       show_all: bool = True):
    """What to draw for ``entity`` in a space whose annotation scale is
    ``scale``: a :class:`Representation`, None (draw the entity as it is) or
    :data:`HIDDEN`.

    A scale is matched by its SCALE object first and by name second (xref
    binding leaves duplicates such as ``1:100_1_1``). An object that does not
    support the space's scale is hidden when ANNOALLVISIBLE is 0 and shown at
    its default representation otherwise -- the manual says "only one" is
    shown (p. 2151) and not which; the default is what the object's own
    fields hold.
    """
    if scale is None or not is_annotative(entity):
        return None
    reps = representations(entity)
    if not reps:
        return None
    match = next((r for r in reps if r.scale.handle == scale.handle), None)
    if match is None:
        match = next((r for r in reps if r.scale.name == scale.name), None)
    if match is None:
        return None if show_all else HIDDEN
    return None if match.is_default else match


def _default_factor(entity) -> Optional[float]:
    rep = next((r for r in representations(entity) if r.is_default), None)
    return rep.scale.factor if rep is not None else None


def virtual_representation(entity, rep: Representation):
    """A virtual copy of ``entity`` laid out as ``rep`` says.

    Built outside the entity database (the regen runs in a worker thread and
    ``entity.copy()`` would add dictionaries to the document), carrying the
    original handle so the drawing is attributed to the real object: picking
    and hiding keep working. None when the type has nothing to substitute.
    """
    from ezdxf.entities import factory

    dxftype = entity.dxftype()
    base = _default_factor(entity)
    ratio = rep.scale.factor / base if base else 1.0
    attribs = entity.dxfattribs(drop={"handle", "owner"})
    if dxftype == "TEXT":
        attribs["halign"] = rep.first(70, attribs.get("halign", 0))
        attribs["rotation"] = rep.first(50, attribs.get("rotation", 0.0))
        attribs["insert"] = _point(rep.first(10), attribs.get("insert"))
        attribs["align_point"] = _point(rep.first(11),
                                        attribs.get("align_point"))
        attribs["height"] = entity.dxf.height * ratio
    elif dxftype == "MTEXT":
        attribs["attachment_point"] = rep.first(
            70, attribs.get("attachment_point", 1))
        attribs["text_direction"] = _point(rep.first(10),
                                           attribs.get("text_direction"))
        attribs.pop("rotation", None)     # the direction says it
        attribs["insert"] = _point(rep.first(11), attribs.get("insert"))
        attribs["char_height"] = entity.dxf.char_height * ratio
        width = rep.first(40)
        if width is not None:
            attribs["width"] = float(width)
    elif dxftype == "DIMENSION":
        block = rep.first(2)
        if not block or block not in entity.doc.blocks:
            return None
        attribs["geometry"] = block
    elif dxftype == "INSERT":
        attribs["rotation"] = rep.first(50, attribs.get("rotation", 0.0))
        attribs["insert"] = _point(rep.first(10), attribs.get("insert"))
        for code, name in ((41, "xscale"), (42, "yscale"), (43, "zscale")):
            value = rep.first(code)
            if value is not None:
                attribs[name] = float(value)
    elif dxftype == "LEADER":
        vertices = [_point(v, None) for v in rep.all(10)]
        if len(vertices) < 2 or None in vertices:
            return None
    else:
        return None
    virtual = factory.new(dxftype, dxfattribs=attribs, doc=entity.doc)
    virtual.dxf.handle = entity.dxf.handle
    if dxftype == "MTEXT":
        virtual.text = entity.text
    elif dxftype == "LEADER":
        virtual.vertices = vertices
    elif dxftype == "INSERT" and entity.attribs:
        # attributes keep their own (default) layout for now
        virtual.attribs = list(entity.attribs)
    return virtual


# -- writing, exactly as AutoCAD does ------------------------------------------

#: context class per entity type: (DXF class name, C++ class name)
CONTEXT_CLASSES = {
    "TEXT": ("ACDB_TEXTOBJECTCONTEXTDATA_CLASS", "AcDbTextObjectContextData"),
    "MTEXT": ("ACDB_MTEXTOBJECTCONTEXTDATA_CLASS",
              "AcDbMTextObjectContextData"),
    # linear (rotated) and aligned dimensions share AutoCAD's "AlDim" class
    # (measured on file G: docs/reference/annotative, 2.3)
    "DIMENSION": ("ACDB_ALDIMOBJECTCONTEXTDATA_CLASS",
                  "AcDbAlignedDimensionObjectContextData"),
}
#: radius and diameter dimensions have context classes of their own, the
#: common dimension body plus their arc points (LibreDWG's dwg.h, after the
#: Open Design spec: RADIM 11-31 first arc point; DMDIM 11-31 and 12-32);
#: no drawing of the corpus carries one, so the writer was checked with ODA
DIM_CONTEXT_CLASSES = {
    0: CONTEXT_CLASSES["DIMENSION"],
    1: CONTEXT_CLASSES["DIMENSION"],
    3: ("ACDB_DMDIMOBJECTCONTEXTDATA_CLASS",
        "AcDbDiametricDimensionObjectContextData"),
    4: ("ACDB_RADIMOBJECTCONTEXTDATA_CLASS",
        "AcDbRadialDimensionObjectContextData"),
}
#: dimension types (dimtype & 7) that can carry scale representations
_DIM_TYPES_WITH_CONTEXT = tuple(DIM_CONTEXT_CLASSES)
#: CLASS flags AutoCAD writes for SCALE and every context class (measured)
_CLASS_FLAGS = 1153


def _register_class(doc, name: str, cpp: str) -> None:
    from ezdxf.entities.dxfclass import DXFClass

    if (name, cpp) in doc.classes.classes:
        return
    cls = DXFClass.new(doc=doc)
    cls.update_dxf_attribs({
        "name": name, "cpp_class_name": cpp, "app_name": "ObjectDBX Classes",
        "flags": _CLASS_FLAGS, "was_a_proxy": 0, "is_an_entity": 0})
    doc.classes.register(cls)


def _new_object(doc, dxftype: str, owner: str, subclasses: list[list]):
    """A custom-class object from raw tags, owned by (and reacting to)
    ``owner`` -- the shape AutoCAD gives SCALE and context objects."""
    from ezdxf.entities.dxfentity import DXFTagStorage
    from ezdxf.lldxf.extendedtags import ExtendedTags

    lines = [(0, dxftype)]
    for sub in subclasses:
        for code, value in sub:
            # tags read back from an object hold points as tuples/vectors:
            # write them out as the x/y/z groups they came from
            if isinstance(value, (tuple, list)) or hasattr(value, "xyz"):
                parts = list(value.xyz) if hasattr(value, "xyz") else list(value)
                for offset, part in enumerate(parts[:3]):
                    lines.append((code + 10 * offset, repr(float(part))))
            else:
                lines.append((code, value))
    text = "".join(f"{c}\n{v}\n" for c, v in lines)
    obj = DXFTagStorage.load(ExtendedTags.from_text(text), doc)
    doc.entitydb.add(obj)           # assigns the handle
    doc.objects.add_object(obj)
    obj.dxf.owner = owner
    obj.set_reactors([owner])
    return obj


def ensure_scale(doc, name: str, paper: float, drawing: float) -> Scale:
    """The named scale, added to ``ACAD_SCALELIST`` when the drawing lacks it."""
    found = find_scale(doc, name)
    if found is not None:
        return found
    scales = doc.rootdict.get("ACAD_SCALELIST")
    if scales is None:
        scales = doc.rootdict.add_new_dict("ACAD_SCALELIST", hard_owned=True)
    _register_class(doc, "SCALE", "AcDbScale")
    key = f"*A{len(scales) + 1}"
    while key in scales:
        key = f"*A{int(key[2:]) + 1}"
    obj = _new_object(doc, "SCALE", scales.dxf.handle, [
        [(100, "AcDbScale"), (70, 0), (300, name), (140, repr(float(paper))),
         (141, repr(float(drawing))), (290, 1 if name == "1:1" else 0)]])
    scales[key] = obj
    return scale_from_object(obj)


def set_annotative(entity, on: bool = True) -> None:
    """Write the AcadAnnotative flag the way AutoCAD does."""
    doc = entity.doc
    if ANNO_APPID not in doc.appids:
        doc.appids.add(ANNO_APPID)
    entity.set_xdata(ANNO_APPID, [
        (1000, "AnnotativeData"), (1002, "{"), (1070, 1),
        (1070, 1 if on else 0), (1002, "}")])


def set_current_scale(doc, scale: Scale) -> None:
    """CANNOSCALE, by name, where AutoCAD keeps it."""
    variables = doc.rootdict.get("AcDbVariableDictionary")
    if variables is None:
        variables = doc.rootdict.add_new_dict("AcDbVariableDictionary",
                                              hard_owned=True)
    variables.set_or_add_dict_var("CANNOSCALE", scale.name)


def set_viewport_scale(viewport, scale: Scale) -> None:
    """A layout viewport's annotation scale (its own property, not its zoom)."""
    if not viewport.has_extension_dict:
        viewport.new_extension_dict()
    xdict = viewport.get_extension_dict()
    record = (xdict[SCALE_INFO_KEY] if SCALE_INFO_KEY in xdict
              else xdict.add_xrecord(SCALE_INFO_KEY))
    record.reset([(90, 1), (340, scale.handle)])


def set_all_visible(layout, on: bool) -> None:
    """ANNOALLVISIBLE of one space (model space or a layout)."""
    obj = layout.dxf_layout
    if ALL_VISIBLE_APPID not in obj.doc.appids:
        obj.doc.appids.add(ALL_VISIBLE_APPID)
    obj.set_xdata(ALL_VISIBLE_APPID, [(1070, 1 if on else 0)])


def _body_for(entity) -> list:
    dxftype = entity.dxftype()
    if dxftype == "TEXT":
        ins = entity.dxf.insert
        align = entity.dxf.get("align_point", ins)
        return [(70, entity.dxf.get("halign", 0)),
                (50, repr(float(entity.dxf.get("rotation", 0.0)))),
                (10, repr(ins[0])), (20, repr(ins[1])),
                (11, repr(align[0])), (21, repr(align[1]))]
    if dxftype == "MTEXT":
        d = entity.dxf.get("text_direction", (1.0, 0.0, 0.0))
        ins = entity.dxf.insert
        return [(70, entity.dxf.get("attachment_point", 1)),
                (10, repr(d[0])), (20, repr(d[1])), (30, repr(d[2])),
                (11, repr(ins[0])), (21, repr(ins[1])), (31, repr(ins[2])),
                (40, repr(float(entity.dxf.get("width", 0.0)))),
                (41, "0.0"), (42, "0.0"), (43, "0.0"), (71, 0)]
    if dxftype == "DIMENSION" and (entity.dimtype & 7) in _DIM_TYPES_WITH_CONTEXT:
        kind = entity.dimtype & 7
        mid = entity.dxf.get("text_midpoint", (0.0, 0.0, 0.0))

        def point(code, value):
            return [(code, repr(float(value[0]))), (code + 10, repr(float(value[1]))),
                    (code + 20, repr(float(value[2]) if len(value) > 2 else 0.0))]

        # the measured body: the *D block of this scale, then the dimension's
        # text placement, then the kind's own subclass
        body = [(100, "AcDbDimensionObjectContextData"),
                (2, entity.dxf.get("geometry", "")), (293, 0),
                (10, repr(float(mid[0]))), (20, repr(float(mid[1]))),
                (294, 1), (140, "0.0"), (298, 0), (291, 0), (70, 1),
                (292, 0), (71, 0), (280, 31), (295, 0), (296, 0), (297, 0)]
        zero = (0.0, 0.0, 0.0)
        if kind in (0, 1):
            body += [(100, "AcDbAlignedDimensionObjectContextData")] \
                + point(11, entity.dxf.get("defpoint", zero))
        elif kind == 4:
            body += [(100, "AcDbRadialDimensionObjectContextData")] \
                + point(11, entity.dxf.get("defpoint4", zero))
        else:
            body += [(100, "AcDbDiametricDimensionObjectContextData")] \
                + point(11, entity.dxf.get("defpoint4", zero)) \
                + point(12, entity.dxf.get("defpoint", zero))
        return body
    raise ValueError(f"{dxftype} cannot carry scale representations yet")


def render_scale_block(dim, scale: Scale) -> dict:
    """Draw ``dim`` at ``scale`` into a *D block of its own and leave the
    dimension as it was; the representation fields of that drawing ({group
    code: value}: the block, the text position, the line's defpoint).

    An annotative dimension is sized by its scale: DIMSCALE = the scale's
    factor, exactly as one born at that scale is drawn (AddDimensionCommand).
    """
    from types import SimpleNamespace

    from core.actions import _stamp_dim_block_byblock

    saved_block = dim.dxf.get("geometry", None)
    had_mid = dim.dxf.hasattr("text_midpoint")
    saved_mid = dim.dxf.get("text_midpoint", None)
    saved_defpoint = dim.dxf.get("defpoint", None)
    saved_acad = list(dim.get_xdata("ACAD")) if dim.has_xdata("ACAD") else None
    global _drawing_scale
    _drawing_scale += 1
    try:
        override = dim.override()
        override["dimscale"] = scale.factor
        override.render()
        block = dim.dxf.get("geometry", "")
        _stamp_dim_block_byblock(SimpleNamespace(doc=dim.doc), dim)
        mid = dim.dxf.get("text_midpoint", saved_mid) or (0.0, 0.0, 0.0)
        defpoint = dim.dxf.get("defpoint", saved_defpoint) or (0.0, 0.0, 0.0)
    finally:
        _drawing_scale -= 1
        if saved_block is not None:
            dim.dxf.geometry = saved_block
        if had_mid:
            dim.dxf.text_midpoint = saved_mid
        else:
            dim.dxf.discard("text_midpoint")
        if saved_defpoint is not None:
            dim.dxf.defpoint = saved_defpoint
        dim.discard_xdata("ACAD")
        if saved_acad is not None:
            dim.set_xdata("ACAD", saved_acad)
    layout = {2: block, 10: float(mid[0]), 20: float(mid[1])}
    if (dim.dimtype & 7) in (0, 1):      # the line's defpoint is per scale
        layout.update({11: float(defpoint[0]), 21: float(defpoint[1])})
    return layout


#: depth of render_scale_block: its own render must not refresh again
_drawing_scale = 0


def refresh_scale_blocks(dim) -> None:
    """Redraw the blocks of every non-default scale of an annotative
    dimension from the dimension as it is now. Called after anything
    redraws or moves it (grips, STRETCH, MOVE, a style change...): AutoCAD
    keeps every scale's drawing in step with the dimension, and the extra
    blocks were left behind -- the 2:1 viewport showed the old dimension."""
    if _drawing_scale or dim.dxftype() != "DIMENSION" or dim.doc is None \
            or not is_annotative(dim):
        return
    for rep in [r for r in representations(dim) if not r.is_default]:
        old_block = rep.first(2)
        if remove_representation(dim, rep.scale) is None:
            continue
        add_representation(dim, rep.scale, default=False)
        drop_unreferenced_block(dim.doc, old_block)


def block_referenced(doc, name: str) -> bool:
    """Is the anonymous *D block drawn by any dimension -- as its own
    geometry or as one of its scale representations?"""
    for e in doc.entitydb.values():
        if not e.is_alive:
            continue
        if e.dxftype() in ("DIMENSION", "ARC_DIMENSION") \
                and e.dxf.get("geometry", None) == name:
            return True
        if e.dxftype().endswith("DIMOBJECTCONTEXTDATA_CLASS"):
            for sub in _subclass_tags(e):
                if any(c == 2 and v == name for c, v in sub):
                    return True
    return False


def drop_unreferenced_block(doc, name) -> None:
    if name and name in doc.blocks and not block_referenced(doc, name):
        try:
            doc.blocks.delete_block(name, safe=False)
        except Exception:                        # noqa: BLE001
            pass


def supports_representation(entity) -> bool:
    """Can :func:`add_representation` write a body for this entity?"""
    dxftype = entity.dxftype()
    if dxftype in ("TEXT", "MTEXT"):
        return True
    return dxftype == "DIMENSION" and (entity.dimtype & 7) in _DIM_TYPES_WITH_CONTEXT


def add_representation(entity, scale: Scale, *, default: bool,
                       layout: Optional[dict] = None) -> None:
    """Give ``entity`` a representation for ``scale``.

    The body is laid out from the entity's own fields, overridden by
    ``layout`` ({group code: value}) -- how a representation at another
    scale gets its own position. Makes the entity annotative.
    """
    dxftype = entity.dxftype()
    name, cpp = (DIM_CONTEXT_CLASSES[entity.dimtype & 7]
                 if dxftype == "DIMENSION" else CONTEXT_CLASSES[dxftype])
    doc = entity.doc
    _register_class(doc, name, cpp)
    if dxftype == "DIMENSION" and not default and layout is None:
        # another scale draws its own block (AutoCAD: a 4-scale dimension
        # owns 4 *D blocks) -- pointing at the default one drew it at the
        # default's size in every viewport
        layout = render_scale_block(entity, scale)
    body = _body_for(entity)
    if layout:
        body = [(c, repr(layout[c]) if isinstance(layout[c], float)
                 else layout[c]) if c in layout else (c, v) for c, v in body]
    if not entity.has_extension_dict:
        entity.new_extension_dict()
    xdict = entity.get_extension_dict()
    manager = (xdict[CONTEXT_MANAGER_KEY] if CONTEXT_MANAGER_KEY in xdict
               else xdict.add_dictionary(CONTEXT_MANAGER_KEY, hard_owned=True))
    scales = (manager[SCALES_KEY] if SCALES_KEY in manager
              else manager.add_new_dict(SCALES_KEY, hard_owned=True))
    obj = _new_object(doc, name, scales.dxf.handle, [
        [(100, "AcDbObjectContextData"), (70, 4), (290, 1 if default else 0)],
        [(100, _BODY_MARKER), (340, scale.handle)] + body])
    key = f"*A{len(scales) + 1}"
    while key in scales:
        key = f"*A{int(key[2:]) + 1}"
    scales[key] = obj
    set_annotative(entity, True)


def _point(value, fallback):
    if value is None:
        return fallback
    if isinstance(value, (tuple, list)):
        x, y = float(value[0]), float(value[1])
        z = float(value[2]) if len(value) > 2 else 0.0
        return (x, y, z)
    try:
        return (float(value.x), float(value.y), float(value.z))
    except AttributeError:
        return fallback


# -- creating annotative objects (A2) -------------------------------------------

from core.commands import Command  # noqa: E402  (the reader above is import-light)


def default_scale(doc) -> Scale:
    """1:1, added to the scale list when the drawing has none."""
    return ensure_scale(doc, "1:1", 1.0, 1.0)


def seed_standard_scales(doc) -> None:
    """A new drawing's scale list, as AutoCAD's templates carry one (#73:
    IngeCAD's started empty, so only 1:1 was ever offered): the same list
    PLOT and PAGESETUP offer, core.units.STANDARD_SCALES."""
    from core.units import STANDARD_SCALES, scale_text

    for num, den in STANDARD_SCALES:
        ensure_scale(doc, scale_text(num, den), num, den)


def standard_scale(doc, name: str) -> Optional[Scale]:
    """``name`` from the drawing's scale list; a standard scale the list
    lacks (a DXF from another program carries none) is added on use."""
    found = find_scale(doc, name)
    if found is not None:
        return found
    from core.units import STANDARD_SCALES, scale_text

    for num, den in STANDARD_SCALES:
        if scale_text(num, den) == name.strip():
            return ensure_scale(doc, name.strip(), num, den)
    return None


def scale_or_default(doc) -> Scale:
    """CANNOSCALE, or 1:1 when the drawing never set one."""
    return current_scale(doc) or default_scale(doc)


def creation_scale(document) -> Scale:
    """The annotation scale a NEW object of the current space is born with:
    model space's CANNOSCALE (1:1 when unset); the sheet itself is paper, so
    1:1; a block open in the Block Editor follows CANNOSCALE too."""
    doc = document.doc
    space = document.current_space()
    if getattr(space, "is_any_paperspace", False):
        return default_scale(doc)
    return scale_or_default(doc)


def style_is_annotative(document, table: str, name: str) -> bool:
    """Is the text style (``table`` = "styles") or dimension style
    ("dimstyles") annotative? The flag rides the table entry's XDATA, as on
    any object (the acad(iso).dwt "Annotative" styles carry it)."""
    entries = getattr(document.doc, table)
    if name not in entries:
        return False
    return is_annotative(entries.get(name))


def set_style_annotative(entry, on: bool) -> None:
    """Flag a STYLE / DIMSTYLE table entry. An annotative dimension style
    also forces DIMSCALE to 0 (p. 2249): CANNOSCALE sizes its dimensions."""
    set_annotative(entry, on)
    if on and entry.dxftype() == "DIMSTYLE":
        entry.dxf.dimscale = 0.0


def remove_representations(entity) -> None:
    """Drop every context object of ``entity`` (before deleting it: ezdxf's
    delete leaves those of a file's own, soft-owned managers orphaned in
    OBJECTS, measured). Deleting the manager takes its hard-owned scale
    dictionary and context objects with it."""
    manager = _xdict_get(entity, CONTEXT_MANAGER_KEY)
    if manager is None:
        return
    try:
        entity.get_extension_dict().discard(CONTEXT_MANAGER_KEY)
    except Exception:                            # noqa: BLE001
        pass
    if manager.is_alive:
        scales = manager[SCALES_KEY] if SCALES_KEY in manager else None
        doc = entity.doc
        try:
            doc.objects.delete_entity(manager)
        except Exception:                        # noqa: BLE001
            pass
        # a soft-owned scale dictionary (a colleague's file) survives that
        if scales is not None and scales.is_alive:
            for _key, obj in list(scales.items()):
                if obj is not None and obj.is_alive:
                    try:
                        doc.objects.delete_entity(obj)
                    except Exception:            # noqa: BLE001
                        pass
            try:
                doc.objects.delete_entity(scales)
            except Exception:                    # noqa: BLE001
                pass


def remove_representation(entity, scale: Scale):
    """Take the representation for ``scale`` off the entity. Returns what
    :func:`restore_representation` needs, or None when the entity does not
    carry that scale. The default one cannot go (OBJECTSCALE: "The current
    scale or scales referenced by objects or views cannot be deleted")."""
    manager = _xdict_get(entity, CONTEXT_MANAGER_KEY)
    if manager is None or SCALES_KEY not in manager:
        return None
    scales = manager[SCALES_KEY]
    doc = entity.doc
    for key, obj in list(scales.items()):
        subs = _subclass_tags(obj)
        handle = next((v for sub in subs for c, v in sub if c == 340), None)
        if handle != scale.handle:
            continue
        is_default = any(c == 290 and bool(v) for sub in subs for c, v in sub)
        if is_default:
            return None
        saved = [sub for sub in subs[1:]]
        dxftype = obj.dxftype()
        del scales[key]                  # a hard-owned entry: this deletes it
        if obj.is_alive:
            try:
                doc.objects.delete_entity(obj)
            except Exception:            # noqa: BLE001 - already gone
                pass
        return (dxftype, saved)
    return None


def restore_representation(entity, saved) -> None:
    """Put back what :func:`remove_representation` took (undo)."""
    dxftype, subclasses = saved
    manager = _xdict_get(entity, CONTEXT_MANAGER_KEY)
    if manager is None or SCALES_KEY not in manager:
        return
    scales = manager[SCALES_KEY]
    obj = _new_object(entity.doc, dxftype, scales.dxf.handle, subclasses)
    key = f"*A{len(scales) + 1}"
    while key in scales:
        key = f"*A{int(key[2:]) + 1}"
    scales[key] = obj


def has_scale(entity, scale: Scale) -> bool:
    return any(r.scale.handle == scale.handle for r in representations(entity))


def annotate_new_entity(document, entity, paper_height: Optional[float] = None) -> bool:
    """A TEXT/MTEXT just created: when its text style is annotative, make it
    annotative at the current annotation scale -- its typed height is a
    PAPER height, so the model height is that times the scale's factor, and
    it gets its one (default) representation. True when it did."""
    dxftype = entity.dxftype()
    if dxftype not in ("TEXT", "MTEXT"):
        return False
    style = entity.dxf.get("style", "Standard")
    if not style_is_annotative(document, "styles", style):
        return False
    scale = creation_scale(document)
    field_name = "height" if dxftype == "TEXT" else "char_height"
    paper = float(paper_height if paper_height is not None
                  else entity.dxf.get(field_name, 0.0))
    entity.dxf.set(field_name, paper * scale.factor)
    if dxftype == "MTEXT" and entity.dxf.hasattr("width"):
        entity.dxf.width = float(entity.dxf.width) * scale.factor
    add_representation(entity, scale, default=True)
    return True


def annotate_new_dimension(document, dim, scale: Scale) -> None:
    """A dimension just rendered under an annotative style: the flag and,
    for the linear/aligned kinds, its default representation."""
    if supports_representation(dim):
        add_representation(dim, scale, default=True)
    else:
        set_annotative(dim, True)


def entities_supporting(space, scale: Scale) -> list:
    """The annotative objects of ``space`` that carry ``scale``."""
    return [e for e in space if is_annotative(e) and has_scale(e, scale)]


class SetAnnotationScaleCommand(Command):
    """CANNOSCALE (model space) or a layout viewport's own annotation scale,
    as one undo step; with ANNOAUTOSCALE on, the objects of that space that
    support the scale being left gain the new one (they keep their place)."""

    name = "CANNOSCALE"
    needs_regen = True

    def __init__(self, scale_name: str, viewport=None, autoscale: bool = False) -> None:
        self.scale_name = scale_name
        self.viewport = viewport
        self.autoscale = autoscale
        self._old: Optional[str] = None
        self._added: list = []

    def do(self, document) -> None:
        doc = document.doc
        scale = find_scale(doc, self.scale_name)
        if scale is None:
            raise ValueError(f"no scale named {self.scale_name!r} in the drawing")
        self._added = []
        if self.viewport is not None:
            old = viewport_scale(self.viewport)
            self._old = old.name if old else None
            set_viewport_scale(self.viewport, scale)
        else:
            old = current_scale(doc)
            self._old = old.name if old else None
            set_current_scale(doc, scale)
        if self.autoscale and old is not None and old.handle != scale.handle:
            space = doc.modelspace()
            for entity in entities_supporting(space, old):
                if not has_scale(entity, scale) and supports_representation(entity):
                    add_representation(entity, scale, default=False)
                    self._added.append(entity)
        document.dirty = True

    def undo(self, document) -> None:
        doc = document.doc
        scale = find_scale(doc, self.scale_name)
        for entity in self._added:
            if entity.is_alive and scale is not None:
                remove_representation(entity, scale)
        self._added = []
        old = find_scale(doc, self._old) if self._old else None
        if self.viewport is not None:
            if old is not None:
                set_viewport_scale(self.viewport, old)
            elif self.viewport.has_extension_dict:
                xdict = self.viewport.get_extension_dict()
                if SCALE_INFO_KEY in xdict:
                    record = xdict[SCALE_INFO_KEY]
                    xdict.discard(SCALE_INFO_KEY)
                    try:
                        doc.objects.delete_entity(record)
                    except Exception:            # noqa: BLE001
                        pass
        else:
            if old is not None:
                set_current_scale(doc, old)
            else:
                variables = doc.rootdict.get("AcDbVariableDictionary")
                if variables is not None and "CANNOSCALE" in variables:
                    variables.discard("CANNOSCALE")
        document.dirty = True


class AnnotativePropertyCommand(Command):
    """Properties > Annotative: Yes/No on texts and dimensions that exist
    (#73). Rafael made his dimension and text styles annotative AFTER
    dimensioning (review 6, 44:00-47:00): the dimensions already drawn kept
    their plain size, and OBJECTSCALE answered "no annotative objects"
    because, as in AutoCAD, a style does not change the objects already
    made with it -- AutoCAD's way is this property.

    Yes: the object gets a representation at the current annotation scale
    (CANNOSCALE). A text keeps its model height (its paper height is that
    over the scale); a dimension is drawn again at that scale (DIMSCALE =
    the scale's factor), as one born in an annotative style is.
    No: its scale representations go; it keeps the look it has.
    """

    name = "ANNOTATIVE"
    needs_regen = True

    def __init__(self, entities, on: bool) -> None:
        self.entities = [e for e in entities if e.dxftype() in ("TEXT", "MTEXT", "DIMENSION")]
        self.on = bool(on)
        self._saved: list = []

    def do(self, document) -> None:
        from core.actions import rerender_dimension

        doc = document.doc
        scale = current_scale(doc) or default_scale(doc)
        self._saved = []
        for entity in self.entities:
            if is_annotative(entity) == self.on:
                continue
            self._saved.append((entity, entity.get_xdata(ANNO_APPID)
                                if entity.has_xdata(ANNO_APPID) else None,
                                entity.get_xdata("ACAD") if entity.has_xdata("ACAD") else None,
                                [r.scale.name for r in representations(entity)]))
            if self.on:
                if entity.dxftype() == "DIMENSION":
                    override = entity.override()
                    override["dimscale"] = scale.factor
                    override.commit()
                    rerender_dimension(document, entity)
                    annotate_new_dimension(document, entity, scale)
                elif supports_representation(entity):
                    add_representation(entity, scale, default=True)
                else:
                    set_annotative(entity, True)
            else:
                remove_representations(entity)
                entity.discard_xdata(ANNO_APPID)
        document.dirty = True

    def undo(self, document) -> None:
        from core.actions import rerender_dimension

        for entity, anno, acad, scales in reversed(self._saved):
            remove_representations(entity)
            entity.discard_xdata(ANNO_APPID)
            if anno is not None:
                entity.set_xdata(ANNO_APPID, list(anno))
            for index, name in enumerate(scales):
                found = find_scale(document.doc, name)
                if found is not None and supports_representation(entity):
                    add_representation(entity, found, default=index == 0)
            if entity.dxftype() == "DIMENSION":
                entity.discard_xdata("ACAD")
                if acad is not None:
                    entity.set_xdata("ACAD", list(acad))
                rerender_dimension(document, entity)
        self._saved = []
        document.dirty = True


class ObjectScaleCommand(Command):
    """OBJECTSCALE Add / Delete on a selection, one undo step."""

    name = "OBJECTSCALE"
    needs_regen = True

    def __init__(self, entities: list, scale_name: str, add: bool) -> None:
        self.entities = [e for e in entities if is_annotative(e)]
        self.scale_name = scale_name
        self.add = add
        self._done: list = []      # (entity, saved) for Delete; entities for Add
        # How many were left as they were (the scale already there, or not
        # there to delete). A COUNT -- not ``skipped``, which on the editing
        # commands is the list of entities that could not be transformed and
        # which the tool controller reads as such: an int there raised
        # TypeError and left Add Current Scale hanging, mute, until a second
        # Enter (Rafael's seventh review, 22:01-22:19).
        self.unchanged = 0

    def do(self, document) -> None:
        scale = find_scale(document.doc, self.scale_name)
        if scale is None:
            raise ValueError(f"no scale named {self.scale_name!r} in the drawing")
        self._done = []
        self.unchanged = 0
        for entity in self.entities:
            if self.add:
                if has_scale(entity, scale) or not supports_representation(entity):
                    self.unchanged += 1
                    continue
                add_representation(entity, scale, default=False)
                self._done.append((entity, None))
            else:
                saved = remove_representation(entity, scale)
                if saved is None:
                    self.unchanged += 1
                    continue
                self._done.append((entity, saved))
        document.dirty = True

    def undo(self, document) -> None:
        scale = find_scale(document.doc, self.scale_name)
        for entity, saved in reversed(self._done):
            if not entity.is_alive:
                continue
            if self.add:
                if scale is not None:
                    remove_representation(entity, scale)
            else:
                restore_representation(entity, saved)
        self._done = []
        document.dirty = True


class SetAllVisibleCommand(Command):
    """ANNOALLVISIBLE of one space."""

    name = "ANNOALLVISIBLE"
    needs_regen = True

    def __init__(self, layout, on: bool) -> None:
        self.layout = layout
        self.on = on
        self._old = True

    def do(self, document) -> None:
        self._old = all_visible(self.layout)
        set_all_visible(self.layout, self.on)
        document.dirty = True

    def undo(self, document) -> None:
        set_all_visible(self.layout, self._old)
        document.dirty = True
