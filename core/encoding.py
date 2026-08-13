# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Accents that survive "Save as DWG".

LibreDWG mangles non-ASCII text on the way into a DWG, and how it mangles it
depends on the version of the DXF it is fed. Measured on a drawing carrying
``CAÑERÍA Ø m² Nº45°`` in every place a string can live, converted with the
bundled ``dxf2dwg --as r2000`` and read back:

======================  ==================  ==================
place                   R2018 intermediate  R2000 intermediate
======================  ==================  ==================
layer / style / block   mangled             correct
TEXT, ATTRIB, dim text  mangled             correct
XDATA                   mangled             correct
MTEXT                   correct             mangled
======================  ==================  ==================

A modern DXF is UTF-8 and LibreDWG copies those bytes into a DWG that
declares the single-byte Windows codepage, so AutoCAD decodes ``CAÑERÍA`` as
``CAÃ‘ERÃA``. Feeding it a pre-r2007 DXF (already in that codepage) fixes
everything except MTEXT, where it then emits ``\\U+xxxx`` escapes computed
from the wrong code points (``Ñ`` came back as Cyrillic ``х``).

So this module does both halves of the fix:

1. the intermediate DXF goes out as R2000 — the version the DWG will have
   anyway, so nothing an r2000 DWG could carry is lost by the downgrade; and
2. MTEXT text is pre-escaped to ``\\U+xxxx`` **by us**, which is AutoCAD's own
   notation for a character the codepage cannot hold. Pure ASCII leaves
   LibreDWG nothing to mistranslate, and AutoCAD renders it as the character.

Reported upstream as LibreDWG issue #1393. When that lands this module can go;
until then it is the difference between a colleague reading ``CAÑERÍA Ø150``
and reading ``CAÃ‘ERÃA Ã˜150``.
"""
from __future__ import annotations

import re
from pathlib import Path

#: The DXF version handed to ``dxf2dwg``. Matches the DWG we write (r2000),
#: which is why the downgrade costs nothing.
INTERMEDIATE_DXF_VERSION = "AC1015"


def escape_non_ascii(text: str) -> str:
    """``Nº 45°`` -> ``N\\U+00BA 45\\U+00B0`` — AutoCAD's own escape.

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
    """Write the DXF that ``dxf2dwg`` will convert, with accents that survive.

    The document is restored to exactly its previous state afterwards: the
    caller's drawing must not notice that this happened.
    """
    escaped: list[tuple] = []
    for entity in _mtext_entities(doc):
        original = entity.text
        replaced = escape_non_ascii(original)
        if replaced != original:
            escaped.append((entity, original))
            entity.text = replaced
    old_version = doc.dxfversion
    try:
        doc.dxfversion = INTERMEDIATE_DXF_VERSION
        doc.saveas(dxf_path)
    finally:
        doc.dxfversion = old_version
        for entity, original in escaped:
            entity.text = original
