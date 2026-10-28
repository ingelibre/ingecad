# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
r"""The DXF handed to the DWG converter, and the escapes read back from one.

``dxf2dwg`` writes an r2000 DWG, and what it does with the DXF it is given
depends on that file's own version. Measured on real drawings, with the
converters IngeCAD ships:

* A drawing whose DXF version is **pre-R13** loses everything: the DWG comes
  back with zero entities (LibreDWG's pre-R13 writer gap, issue #1386). Four
  R12 files in the test bench did exactly that.
* Handing it an **R2000** DXF instead converts those same four completely.

So the intermediate always goes out as R2000. That is the version the DWG
will have anyway, which is what makes the downgrade free: nothing an r2000
DWG could carry is lost by it.

Accents used to need a second half here — MTEXT pre-escaped to ``\U+xxxx``,
because LibreDWG mangled non-ASCII text on the way in. That was
LibreDWG issue #1393, fixed by PR #1375 and shipped in ``vendor/`` since the
0.14.8580 re-vendorization, so the escaping is gone: the file now carries the
text the user actually typed.

Reading the escapes back stays. AutoCAD itself writes ``\U+xxxx`` for a
character its codepage cannot hold, and ezdxf does not decode it, so without
this the canvas shows the raw code instead of the character.
"""

from __future__ import annotations

import re
from pathlib import Path

#: The DXF version handed to ``dxf2dwg``. Matches the DWG we write (r2000),
#: which is why the downgrade costs nothing.
INTERMEDIATE_DXF_VERSION = "AC1015"


def escape_non_ascii(text: str) -> str:
    """``Nº 45°`` -> ``N\\U+00BA 45\\U+00B0`` — AutoCAD's own escape.

    Not used when saving any more (see the module docstring); kept as the
    documented inverse of :func:`decode_escapes`, which the tests pin.

    Characters outside ASCII become ``\\U+`` plus four uppercase hex digits.
    Anything already ASCII, MTEXT's own formatting codes included, is left
    exactly as it is: those are ASCII by construction.
    """
    if text.isascii():
        return text
    out = []
    for ch in text:
        if ord(ch) < 128:
            out.append(ch)
        elif ord(ch) > 0xFFFF:
            # Beyond the BMP there is no four-digit escape; a surrogate pair
            # is what AutoCAD writes.
            code = ord(ch) - 0x10000
            out.append(f"\\U+{0xD800 + (code >> 10):04X}"
                       f"\\U+{0xDC00 + (code & 0x3FF):04X}")
        else:
            out.append(f"\\U+{ord(ch):04X}")
    return "".join(out)


#: ``\U+00D1`` and its surrogate-pair form, as AutoCAD writes them.
_ESCAPE_RE = re.compile(r"\\U\+([0-9A-Fa-f]{4})")


def decode_escapes(text: str) -> str:
    """``N\\U+00BA 45`` -> ``Nº 45``, surrogate pairs included.

    The inverse of :func:`escape_non_ascii`. Text without an escape is
    returned unchanged and untouched.
    """
    if "\\U+" not in text:
        return text

    def one(match) -> str:
        return chr(int(match.group(1), 16))

    decoded = _ESCAPE_RE.sub(one, text)
    # A pair of escaped surrogates is one character, not two.
    try:
        return decoded.encode("utf-16", "surrogatepass").decode("utf-16")
    except UnicodeError:
        return decoded


def decode_escapes_in_document(doc) -> int:
    """Decode the escapes of every MTEXT in a freshly-opened drawing.

    Returns how many entities changed, for the tests. Only MTEXT: that is
    where AutoCAD puts these escapes, and it is the only place we write them.
    """
    changed = 0
    for entity in _mtext_entities(doc):
        text = entity.text
        decoded = decode_escapes(text)
        if decoded != text:
            entity.text = decoded
            changed += 1
    return changed


def repair_invalid_defaults(doc) -> int:
    """Normalize impossible MTEXT values a broken writer left behind.

    Every DWG IngeCAD saved before v0.4.5 carries them: the intermediate DXF
    omitted groups equal to their default (as DXF allows) and LibreDWG stored
    the missing group as ZERO — so multiline text came back with
    ``line_spacing_factor 0.0`` and every line of the paragraph drew on top
    of the first. The valid range is 0.25-4.0 and 0 is not a flow direction
    or a spacing style, so this only ever touches corrupt values.

    Returns how many entities changed, for the tests.
    """
    changed = 0
    for entity in _mtext_entities(doc):
        dirty = False
        d = entity.dxf
        factor = d.get("line_spacing_factor", None)
        if factor is not None and not (0.25 <= factor <= 4.0):
            d.line_spacing_factor = 1.0
            dirty = True
        if d.get("line_spacing_style", None) == 0:
            d.line_spacing_style = 1
            dirty = True
        if d.get("flow_direction", None) == 0:
            d.flow_direction = 1
            dirty = True
        changed += dirty
    return changed


#: Dimension-style variables whose value ezdxf assumes, when the group is
#: absent, to be something other than the DXF default of 0.
_DIMSTYLE_ZERO_DEFAULTS = ("dimadec", "dimaltd", "dimarcsym", "dimatfit",
                           "dimazin", "dimdec", "dimgap", "dimtdec",
                           "dimtmove", "dimtofl", "dimzin")


def repair_dimstyle_defaults(doc) -> int:
    """Write out the zeros LibreDWG left implicit in every DIMSTYLE.

    dwg2dxf omits a dimension-style group whose value is 0 (as DXF allows:
    an absent group is 0), but ezdxf fills some of them with its own
    defaults -- DIMZIN 8 above all, so a style the author set to show
    trailing zeros lost them on the first redraw of each dimension ("0.10"
    became "0.1" after a grip edit in dozens of corpus plans). Measured on
    a real plan against ``dwgread -O JSON``: every absent group was 0 in
    the DWG. Returns how many styles changed, for the tests.
    """
    changed = 0
    for style in doc.dimstyles:
        dirty = False
        for name in _DIMSTYLE_ZERO_DEFAULTS:
            if not style.dxf.hasattr(name):
                style.dxf.set(name, 0)
                dirty = True
        changed += dirty
    return changed


def _mtext_entities(doc):
    """Every MTEXT in the document — model space, layouts and blocks."""
    for layout in doc.layouts:
        for entity in layout:
            if entity.dxftype() == "MTEXT":
                yield entity
    for block in doc.blocks:
        for entity in block:
            if entity.dxftype() == "MTEXT":
                yield entity


# -- FIELD objects, R2007+ -> R2000 ---------------------------------------------
# ezdxf does not know FIELD and keeps its tags verbatim, so a drawing read
# from an R2007+ DWG carries the R2007+ layout of every FIELD into the R2000
# intermediate. There each value is ``90 type, payload``; R2007+ adds ``93``
# format flags before it and ``94``/``300``/``302`` after, and drops the
# payload when flag 1 is set. LibreDWG, reading an R2000 DXF, took the
# leading 93 for the child count and aborted the WHOLE save ("No class for
# FIELD"): 34 of the first 266 corpus drawings. The R2000 form below is what
# LibreDWG writes and reads for R2000 (the field's own value first, then the
# children), with the value groups of ODA's R2000 output.

#: Payload of a value by data type, for when R2007+ left it out.
_FIELD_DEFAULT_PAYLOAD = {
    0: ((91, 0),), 1: ((91, 0),), 2: ((140, 0.0),), 4: ((1, ""),),
    8: ((92, 0),), 16: ((11, 0.0), (21, 0.0)),
    32: ((11, 0.0), (21, 0.0), (31, 0.0)), 64: ((330, "0"),),
}
_FIELD_PAYLOAD_CODES = frozenset({91, 140, 1, 92, 310, 11, 21, 31, 330})
_FIELD_R2007_ONLY = frozenset({94, 300, 302})


def _r2000_field_value(tags, i):
    """Read one value starting at ``tags[i]``; return (R2000 tags, next i)."""
    from ezdxf.lldxf.types import DXFTag

    if i < len(tags) and tags[i].code == 93:
        i += 1                                   # format flags: R2007+ only
    if i >= len(tags) or tags[i].code != 90:
        return None, i
    data_type = int(tags[i].value)
    out = [tags[i]]
    i += 1
    payload = []
    while i < len(tags) and tags[i].code in _FIELD_PAYLOAD_CODES:
        payload.append(tags[i])
        i += 1
    if not payload:
        payload = [DXFTag(code, value) for code, value in
                   _FIELD_DEFAULT_PAYLOAD.get(data_type, ((91, 0),))]
        if data_type not in _FIELD_DEFAULT_PAYLOAD:
            out = [DXFTag(90, 0)]                # no R2000 spelling: unknown
    out += payload
    while i < len(tags) and tags[i].code in _FIELD_R2007_ONLY:
        i += 1
    return out, i


def _r2000_field_tags(tags):
    """The AcDbField subclass of an R2007+ FIELD, in its R2000 layout, or
    None when it does not look like one (left alone, then)."""
    from ezdxf.lldxf.types import DXFTag

    codes = [t.code for t in tags]
    try:
        start = codes.index(300, codes.index(96)) + 1   # evaluation error msg
    except ValueError:
        return None
    out = list(tags[:start])
    own, i = _r2000_field_value(tags, start)
    if own is None:
        return None
    out += own
    if i >= len(tags) or tags[i].code != 93:
        return None
    count = int(tags[i].value)
    out.append(tags[i])
    i += 1
    for _ in range(count):
        if i >= len(tags) or tags[i].code != 6:
            return None
        out.append(tags[i])
        child, i = _r2000_field_value(tags, i + 1)
        if child is None:
            return None
        out += child
    out += [t for t in tags[i:] if t.code in (301, 9, 98)] or \
        [DXFTag(301, ""), DXFTag(98, 0)]
    return out


def _downgrade_fields(doc) -> list:
    """Rewrite every FIELD to R2000 in place; return what undoes it."""
    if doc.dxfversion < "AC1021":
        return []
    undo = []
    for obj in doc.objects:
        if obj.dxftype() != "FIELD" or not hasattr(obj, "xtags"):
            continue
        for sub in obj.xtags.subclasses:
            if sub and sub[0].value == "AcDbField":
                new = _r2000_field_tags(sub)
                if new is not None:
                    undo.append((sub, list(sub)))
                    sub[:] = new
    return undo


def write_dwg_intermediate(doc, dxf_path: Path) -> None:
    """Write the DXF that ``dxf2dwg`` will convert.

    Every optional group is written EXPLICITLY, defaults included. DXF says
    "absent means default", and ezdxf therefore omits a group whose value
    equals its default — but LibreDWG's DXF importer stores a missing group
    as ZERO instead of applying the default. Marco caught the visible case:
    an MTEXT with the default line spacing came back from Save as DWG with
    ``line_spacing_factor 1.0 -> 0.0`` (plus flow_direction and spacing
    style 1 -> 0), which stacks every line of the paragraph on top of the
    first one. Writing the groups out closes the whole family, not just
    MTEXT — the same pattern was LibreDWG's MINSERT bug (upstream #1385).

    The document is restored to exactly its previous state afterwards: the
    caller's drawing must not notice that this happened.
    """
    from ezdxf.lldxf.tagwriter import TagWriter

    # force_optional only writes optional groups whose VALUE exists; an
    # MTEXT drawn in IngeCAD never had them set, so materialize the three
    # spacing defaults first (and restore after: the caller's drawing must
    # not notice). The synthetic round-trip test caught this hole.
    materialized = []
    for entity in _mtext_entities(doc):
        d = entity.dxf
        for name, default in (("line_spacing_factor", 1.0),
                              ("line_spacing_style", 1),
                              ("flow_direction", 1)):
            if not d.hasattr(name):
                d.set(name, default)
                materialized.append((d, name))

    old_version = doc.dxfversion
    original_init = TagWriter.__init__

    def forced_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        # Instance attribute, set in __init__ — a class attribute would be
        # shadowed, which is why this wraps the constructor.
        self.force_optional = True

    fields = _downgrade_fields(doc)
    try:
        doc.dxfversion = INTERMEDIATE_DXF_VERSION
        TagWriter.__init__ = forced_init
        doc.saveas(dxf_path)
    finally:
        TagWriter.__init__ = original_init
        doc.dxfversion = old_version
        for sub, original in fields:
            sub[:] = original
        for namespace, name in materialized:
            namespace.discard(name)
