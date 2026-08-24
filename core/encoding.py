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

    try:
        doc.dxfversion = INTERMEDIATE_DXF_VERSION
        TagWriter.__init__ = forced_init
        doc.saveas(dxf_path)
    finally:
        TagWriter.__init__ = original_init
        doc.dxfversion = old_version
        for namespace, name in materialized:
            namespace.discard(name)
