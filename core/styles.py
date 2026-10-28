# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Text and dimension styles — the AutoCAD STYLE and DIMSTYLE tables.

Every operation is an undoable Command so the style tables round-trip like
everything else. Text styles carry font / height / width factor / oblique;
dimension styles expose the handful of variables a plan actually needs (text
height, arrow size, overall scale, decimals, text style). The ezdxf document
IS the model — these edit ``doc.styles`` and ``doc.dimstyles`` directly.
"""
from __future__ import annotations

from core.commands import Command

# The dimension variables surfaced in the panel (name -> default).
DIM_VARS = {
    "dimtxt": 2.5,     # text height
    "dimasz": 2.5,     # arrow size
    "dimscale": 1.0,   # overall scale
    "dimexe": 1.25,    # extension beyond dim line
    "dimexo": 0.625,   # extension line offset
    "dimdec": 2,       # decimal places
    "dimtxsty": "Standard",   # text style
}


# AutoCAD's metric ISO-25 dimension style — the acadiso default. Seeded into
# every new drawing so the panel shows an established style (and the $DIMSTYLE
# header, which ezdxf defaults to "ISO-25", points at a real table entry).
ISO25_DIM = {
    "dimtxt": 2.5, "dimasz": 2.5, "dimexe": 1.25, "dimexo": 0.625,
    "dimgap": 0.625, "dimdec": 2, "dimscale": 1.0, "dimtad": 1,
    "dimtxsty": "Standard", "dimlfac": 1.0,
    # Fit, as acadiso.dwt's ISO-25 sets it: dimension line drawn even when
    # the text is outside (for a circle: the line across it, arrowheads
    # inside), text aligned with the line in and out, text moved with the
    # line. ezdxf's own defaults agree, except that its renderer reads an
    # unset DIMTMOVE as 2 -- writing them makes the file say it.
    "dimtofl": 1, "dimtix": 0, "dimatfit": 3, "dimtmove": 0,
    "dimtih": 0, "dimtoh": 0, "dimcen": 2.5,
    # Colours ByBlock, as acadiso's ISO-25: the dimension line, extension
    # lines and text take the DIMENSION's own colour -- its layer's, or an
    # override set on it -- so a dimension moved to a red layer turns red.
    # Unset, ezdxf wrote ByLayer on the block content, which followed the
    # layer but never the dimension's own colour.
    "dimclrd": 0, "dimclre": 0, "dimclrt": 0,
}


# Plot scales an engineer dimensions at; each seeds a dim style whose overall
# scale (DIMSCALE) matches, so model-space dimensions plot at the right size.
DIM_SCALES = (50, 100, 200, 500)


# The ISO-25 entries that are LENGTHS, and so have to be converted when the
# drawing is not in millimetres. The rest (counts, flags, factors) do not.
_DIM_LENGTHS = ("dimtxt", "dimasz", "dimexe", "dimexo", "dimgap")


def iso25_for(unit_factor: float = 1.0) -> dict:
    """ISO-25 expressed in the drawing's own unit.

    ISO-25 is defined in millimetres. In a drawing whose unit is the metre,
    2.5 mm of text is 0.0025 units — leaving it at 2.5 would put a text a
    thousand times too big on the plan, which is the classic way a metric
    drawing goes wrong.
    """
    attribs = dict(ISO25_DIM)
    if unit_factor != 1.0:
        for key in _DIM_LENGTHS:
            attribs[key] = attribs[key] * unit_factor
    return attribs


def install_default_styles(document, unit_factor: float = 1.0,
                           overwrite: bool = False) -> None:
    """Seed the standard styles a fresh AutoCAD drawing carries (idempotent).

    A metric ISO-25 dimension style plus one per common plot scale (1:50 …
    1:500), so the Dimension tab opens with a ready series to pick from.
    ``unit_factor`` is drawing units per millimetre (see core.templates).
    ``overwrite`` re-stamps entries that already exist, which is what
    applying a template to a just-created document needs: Document.new()
    seeds the millimetre sizes before the unit is known.
    """
    doc = document.doc
    base = iso25_for(unit_factor)

    def put(name: str, attribs: dict) -> None:
        if name not in doc.dimstyles:
            doc.dimstyles.new(name, dxfattribs=attribs)
        elif overwrite:
            style = doc.dimstyles.get(name)
            for key, value in attribs.items():
                style.set_dxf_attrib(key, value)

    put("ISO-25", base)
    for scale in DIM_SCALES:
        name = f"Acot-{scale}"        # ':' is not a valid DXF table name char
        attribs = dict(base)
        attribs["dimscale"] = float(scale)
        put(name, attribs)
    if doc.header.get("$DIMSTYLE", "Standard") not in doc.dimstyles:
        doc.header["$DIMSTYLE"] = "ISO-25"


# -- queries ------------------------------------------------------------------

def text_style_names(document) -> list[str]:
    return [s.dxf.name for s in document.doc.styles]


def current_text_style(document) -> str:
    return document.doc.header.get("$TEXTSTYLE", "Standard")


def text_style_props(document, name: str) -> dict:
    from core import annotative

    s = document.doc.styles.get(name)
    return {
        "font": s.dxf.get("font", ""),
        "height": s.dxf.get("height", 0.0),
        "width": s.dxf.get("width", 1.0),
        "oblique": s.dxf.get("oblique", 0.0),
        # a paper height when on (the STYLE dialog's "Annotative" box)
        "annotative": annotative.is_annotative(s),
    }


def dim_style_names(document) -> list[str]:
    return [d.dxf.name for d in document.doc.dimstyles]


def current_dim_style(document) -> str:
    return document.doc.header.get("$DIMSTYLE", "Standard")


def dim_style_props(document, name: str) -> dict:
    from core import annotative

    d = document.doc.dimstyles.get(name)
    props = {k: d.dxf.get(k, default) for k, default in DIM_VARS.items()}
    props["annotative"] = annotative.is_annotative(d)
    return props


def _split_annotative(attribs: dict):
    """(dxf attribs, annotative flag or None): the flag is XDATA, not a
    DXF attribute, and every style command takes it in the same dict."""
    attribs = dict(attribs)
    flag = attribs.pop("annotative", None)
    return attribs, (None if flag is None else bool(flag))


def unique_name(existing, base: str) -> str:
    if base not in existing:
        return base
    i = 1
    while f"{base}{i}" in existing:
        i += 1
    return f"{base}{i}"


# -- text style commands ------------------------------------------------------

class NewTextStyleCommand(Command):
    name = "STYLE"

    def __init__(self, style_name: str, attribs: dict | None = None) -> None:
        self.style_name = style_name
        self.attribs = dict(attribs or {})

    def do(self, document) -> None:
        from core import annotative

        attribs, flag = _split_annotative(self.attribs)
        style = document.doc.styles.new(self.style_name, dxfattribs=attribs)
        if flag:
            annotative.set_style_annotative(style, True)
        document.dirty = True

    def undo(self, document) -> None:
        document.doc.styles.remove(self.style_name)
        document.dirty = True


class DeleteTextStyleCommand(Command):
    name = "STYLE"

    def __init__(self, style_name: str) -> None:
        self.style_name = style_name
        self._attribs: dict = {}

    def do(self, document) -> None:
        s = document.doc.styles.get(self.style_name)
        self._attribs = dict(s.dxf.all_existing_dxf_attribs())
        self._attribs.pop("handle", None)
        self._attribs.pop("owner", None)
        document.doc.styles.remove(self.style_name)
        document.dirty = True

    def undo(self, document) -> None:
        attribs = {k: v for k, v in self._attribs.items() if k != "name"}
        document.doc.styles.new(self.style_name, dxfattribs=attribs)
        document.dirty = True


class SetTextStylePropsCommand(Command):
    name = "STYLE"

    def __init__(self, style_name: str, props: dict) -> None:
        self.style_name = style_name
        self.props = props
        self._old: dict = {}

    def do(self, document) -> None:
        from core import annotative

        s = document.doc.styles.get(self.style_name)
        props, flag = _split_annotative(self.props)
        if flag is not None and flag == annotative.is_annotative(s):
            flag = None                  # unchanged: leave the XDATA alone
        self._old_flag = None
        self._old = {k: s.dxf.get(k, None) for k in props}
        for k, v in props.items():
            s.dxf.set(k, v)
        if flag is not None:
            self._old_flag = annotative.is_annotative(s)
            annotative.set_style_annotative(s, flag)
        document.dirty = True

    def undo(self, document) -> None:
        from core import annotative

        s = document.doc.styles.get(self.style_name)
        for k, v in self._old.items():
            if v is None:
                s.dxf.discard(k)
            else:
                s.dxf.set(k, v)
        if getattr(self, "_old_flag", None) is not None:
            annotative.set_style_annotative(s, self._old_flag)
        document.dirty = True


class SetCurrentTextStyleCommand(Command):
    name = "STYLE"

    def __init__(self, style_name: str) -> None:
        self.style_name = style_name
        self._old: str | None = None

    def do(self, document) -> None:
        self._old = document.doc.header.get("$TEXTSTYLE", "Standard")
        document.doc.header["$TEXTSTYLE"] = self.style_name
        document.dirty = True

    def undo(self, document) -> None:
        document.doc.header["$TEXTSTYLE"] = self._old
        document.dirty = True


# -- dimension style commands -------------------------------------------------

class NewDimStyleCommand(Command):
    name = "DIMSTYLE"

    def __init__(self, style_name: str, attribs: dict | None = None) -> None:
        self.style_name = style_name
        self.attribs = dict(attribs or {})

    def do(self, document) -> None:
        from core import annotative

        attribs, flag = _split_annotative(self.attribs)
        style = document.doc.dimstyles.new(self.style_name, dxfattribs=attribs)
        if flag:
            annotative.set_style_annotative(style, True)
        document.dirty = True

    def undo(self, document) -> None:
        document.doc.dimstyles.remove(self.style_name)
        document.dirty = True


class DeleteDimStyleCommand(Command):
    name = "DIMSTYLE"

    def __init__(self, style_name: str) -> None:
        self.style_name = style_name
        self._attribs: dict = {}

    def do(self, document) -> None:
        d = document.doc.dimstyles.get(self.style_name)
        self._attribs = dict(d.dxf.all_existing_dxf_attribs())
        self._attribs.pop("handle", None)
        self._attribs.pop("owner", None)
        document.doc.dimstyles.remove(self.style_name)
        document.dirty = True

    def undo(self, document) -> None:
        attribs = {k: v for k, v in self._attribs.items() if k != "name"}
        document.doc.dimstyles.new(self.style_name, dxfattribs=attribs)
        document.dirty = True


def dim_style_attribs(document, name: str) -> dict:
    """Every explicit DXF attribute of a dimension style (for Start With)."""
    from core import annotative

    d = document.doc.dimstyles.get(name)
    attribs = dict(d.dxf.all_existing_dxf_attribs())
    for skip in ("handle", "owner", "name"):
        attribs.pop(skip, None)
    attribs["annotative"] = annotative.is_annotative(d)
    return attribs


def fixed_text_heights(document) -> dict[str, float]:
    """{text style: height} of the text styles that fix their height."""
    out = {}
    for style in document.doc.styles:
        try:
            height = float(style.dxf.get("height", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        if height > 0.0:
            out[style.dxf.name] = height
    return out


def dim_text_height(doc, get) -> float:
    """The height a dimension's text is drawn at, before DIMSCALE.

    AutoCAD (Dimension Style, Text Height): "If a fixed text height is set
    in the Text Style (the text style height is greater than 0), that height
    overrides the text height set here" -- and ezdxf draws it so. ``get`` is
    a ``(key, default) -> value`` lookup: a style's ``dxf.get`` or a
    dimension's override ``get``. The one answer for everything that needs
    the height -- the drawing, the style dialog's preview, DIMSPACE's
    spacing, a leader's text, a centre mark's size -- which each read DIMTXT
    alone and disagreed with the drawing when the style was fixed.
    """
    name = get("dimtxsty", None) or "Standard"
    try:
        if name in doc.styles:
            fixed = float(doc.styles.get(name).dxf.get("height", 0.0) or 0.0)
            if fixed > 0.0:
                return fixed
    except Exception:                          # noqa: BLE001 - use DIMTXT
        pass
    try:
        return float(get("dimtxt", 2.5) or 2.5)
    except (TypeError, ValueError):
        return 2.5


#: What a dimension style means by a variable it does not write, where
#: ezdxf knows no default: no text style is the Standard one.
_UNWRITTEN = {"dimtxsty": "Standard"}


def dim_style_differences(document, name: str, base: str) -> list[tuple[str, object]]:
    """What ``name`` sets differently from ``base``, as (variable, value),
    for the Dimension Style Manager's Description ("ISO-25 + Arrow size =
    2"). Compared on EFFECTIVE values -- a variable a style does not write
    counts as its default -- so two styles that agree are not listed as
    different just because one of them spells the value out (a style made
    from ISO-25 listed a dozen identical variables and hid its real change).
    """
    from core import annotative

    styles = document.doc.dimstyles
    one, other = styles.get(name), styles.get(base)
    keys = set(one.dxf.all_existing_dxf_attribs()) | \
        set(other.dxf.all_existing_dxf_attribs())
    keys -= {"handle", "owner", "name", "flags"}

    def value(style, key):
        if style.dxf.hasattr(key):
            return style.dxf.get(key)
        if key in _UNWRITTEN:
            return _UNWRITTEN[key]
        try:
            return style.dxf.get_default(key)
        except Exception:                    # noqa: BLE001 - no default known
            return None

    def same(a, b) -> bool:
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return abs(float(a) - float(b)) <= 1e-9
        return (a or None) == (b or None)

    out = [(key, value(one, key)) for key in sorted(keys)
           if not same(value(one, key), value(other, key))]
    if annotative.is_annotative(one) != annotative.is_annotative(other):
        out.append(("annotative", annotative.is_annotative(one)))
    return out


def rerender_dimensions(document, style_name: str) -> None:
    """Re-render every dimension that uses ``style_name`` — AutoCAD applies a
    modified style to the dimensions drawn with it. Superseded *D blocks are
    dropped unless shared (dimensions inside block references share theirs)."""
    from core.actions import rerender_dimension

    for e in list(document.doc.entitydb.values()):
        if not e.is_alive or e.dxftype() not in ("DIMENSION", "ARC_DIMENSION"):
            continue
        if e.dxf.get("dimstyle", None) != style_name:
            continue
        try:
            rerender_dimension(document, e)
        except Exception:
            continue


class SetDimStylePropsCommand(Command):
    name = "DIMSTYLE"
    needs_regen = True

    def __init__(self, style_name: str, props: dict) -> None:
        self.style_name = style_name
        self.props = props
        self._old: dict = {}

    def do(self, document) -> None:
        from core import annotative

        d = document.doc.dimstyles.get(self.style_name)
        props, flag = _split_annotative(self.props)
        if flag is not None and flag == annotative.is_annotative(d):
            flag = None                  # unchanged: leave the XDATA alone
        self._old_flag = None
        if flag or (flag is None and annotative.is_annotative(d)):
            props["dimscale"] = 0.0      # p. 2249: CANNOSCALE sizes it
        self._old = {k: d.dxf.get(k, None) for k in props}
        if flag is not None:
            self._old.setdefault("dimscale", d.dxf.get("dimscale", None))
        for k, v in props.items():
            d.dxf.set(k, v)
        if flag is not None:
            self._old_flag = annotative.is_annotative(d)
            annotative.set_style_annotative(d, flag)
        rerender_dimensions(document, self.style_name)
        document.dirty = True

    def undo(self, document) -> None:
        from core import annotative

        d = document.doc.dimstyles.get(self.style_name)
        for k, v in self._old.items():
            if v is None:
                d.dxf.discard(k)
            else:
                d.dxf.set(k, v)
        if getattr(self, "_old_flag", None) is not None:
            annotative.set_style_annotative(d, self._old_flag)
            if not self._old_flag and self._old.get("dimscale") is not None:
                d.dxf.dimscale = self._old["dimscale"]
        rerender_dimensions(document, self.style_name)
        document.dirty = True


class RenameDimStyleCommand(Command):
    """Rename a dimension style: duplicate under the new name, repoint every
    dimension that used it, keep $DIMSTYLE current, drop the old entry."""

    name = "DIMSTYLE"

    def __init__(self, old: str, new: str) -> None:
        self.old = old
        self.new = new

    def do(self, document) -> None:
        self._apply(document, self.old, self.new)

    def undo(self, document) -> None:
        self._apply(document, self.new, self.old)

    @staticmethod
    def _apply(document, old: str, new: str) -> None:
        doc = document.doc
        doc.tables.dimstyles.duplicate_entry(old, new)
        for e in doc.entitydb.values():
            if e.is_alive and e.dxftype() in ("DIMENSION", "ARC_DIMENSION") \
                    and e.dxf.get("dimstyle", None) == old:
                e.dxf.dimstyle = new
        if doc.header.get("$DIMSTYLE", "Standard") == old:
            doc.header["$DIMSTYLE"] = new
        doc.dimstyles.remove(old)
        document.dirty = True


class SetCurrentDimStyleCommand(Command):
    name = "DIMSTYLE"

    def __init__(self, style_name: str) -> None:
        self.style_name = style_name
        self._old: str | None = None

    def do(self, document) -> None:
        self._old = document.doc.header.get("$DIMSTYLE", "Standard")
        document.doc.header["$DIMSTYLE"] = self.style_name
        document.dirty = True

    def undo(self, document) -> None:
        document.doc.header["$DIMSTYLE"] = self._old
        document.dirty = True
