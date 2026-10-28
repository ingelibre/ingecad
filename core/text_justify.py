# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A TEXT's justification changed without moving the text (#77).

AutoCAD's Properties palette (and JUSTIFYTEXT) change which point of the
text is its alignment point; the letters stay where they are. ezdxf's
``set_placement`` moves the text instead, so the new alignment point is
worked out here from the text's own box: its width, cap height and
descender (ezdxf.tools.text_size), turned by its rotation.
"""
from __future__ import annotations

import math

#: AutoCAD's Justify list, in the Properties palette's order:
#: (label, ezdxf TextEntityAlignment name).
JUSTIFICATIONS = (
    ("Left", "LEFT"), ("Center", "CENTER"), ("Right", "RIGHT"),
    ("Aligned", "ALIGNED"), ("Middle", "MIDDLE"), ("Fit", "FIT"),
    ("Top left", "TOP_LEFT"), ("Top center", "TOP_CENTER"),
    ("Top right", "TOP_RIGHT"), ("Middle left", "MIDDLE_LEFT"),
    ("Middle center", "MIDDLE_CENTER"), ("Middle right", "MIDDLE_RIGHT"),
    ("Bottom left", "BOTTOM_LEFT"), ("Bottom center", "BOTTOM_CENTER"),
    ("Bottom right", "BOTTOM_RIGHT"),
)

#: MTEXT attachment points 1-9, as AutoCAD lists them.
ATTACHMENTS = (
    ("Top left", 1), ("Top center", 2), ("Top right", 3),
    ("Middle left", 4), ("Middle center", 5), ("Middle right", 6),
    ("Bottom left", 7), ("Bottom center", 8), ("Bottom right", 9),
)


def justification(text) -> str:
    return text.get_align_enum().name


def _offset(name: str, width: float, cap: float, descent: float,
            x_height: float) -> tuple[float, float]:
    """Where the alignment point sits from the left end of the baseline,
    by the renderer's rules (ezdxf.addons.drawing.text): MIDDLE is the
    centre of the LOWER-case height, the MIDDLE_* ones of the capitals."""
    if name in ("LEFT", "ALIGNED", "FIT", "TOP_LEFT", "MIDDLE_LEFT", "BOTTOM_LEFT"):
        x = 0.0
    elif name in ("RIGHT", "TOP_RIGHT", "MIDDLE_RIGHT", "BOTTOM_RIGHT"):
        x = width
    else:
        x = width / 2.0
    if name.startswith("TOP_"):
        y = cap
    elif name.startswith("MIDDLE_"):
        y = cap / 2.0
    elif name.startswith("BOTTOM_"):
        y = -descent
    elif name == "MIDDLE":
        y = x_height / 2.0
    else:                                   # baseline: LEFT/CENTER/RIGHT/ALIGNED/FIT
        y = 0.0
    return x, y


def _measure(text) -> tuple[float, float, float, float]:
    """(width, cap height, descent, lower-case height) as the renderer
    measures them: the same font (a CI box with other fonts put MIDDLE
    0.04 off when it came from the cap and the descent)."""
    from ezdxf.entities import get_font_name
    from ezdxf.fonts import fonts
    from ezdxf.tools.text_size import text_size

    size = text_size(text)
    # the font from the text's own height: make_font applies a stand-in
    # font's scale itself, and size.cap_height already carries it
    metrics = fonts.make_font(get_font_name(text),
                              text.dxf.get_default("height"),
                              text.dxf.get_default("width")).measurements
    return size.width, size.cap_height, metrics.descender_height, metrics.x_height


def _turn(text):
    angle = math.radians(text.dxf.get("rotation", 0.0))
    cos, sin = math.cos(angle), math.sin(angle)
    return lambda dx, dy: (dx * cos - dy * sin, dx * sin + dy * cos)


def baseline_start(text, measured=None) -> tuple[float, float]:
    """The left end of a TEXT's baseline, whatever its justification:
    the point that stays put when the justification changes."""
    measured = measured or _measure(text)
    _align, p1, _p2 = text.get_placement()
    ox, oy = _turn(text)(*_offset(justification(text), *measured))
    return p1.x - ox, p1.y - oy


def set_justification(text, name: str) -> None:
    """Give a TEXT the justification ``name`` (a TextEntityAlignment name)
    without moving its letters."""
    from ezdxf.enums import TextEntityAlignment

    if name == justification(text):
        return
    measured = _measure(text)
    turned = _turn(text)
    base = baseline_start(text, measured)
    nx, ny = turned(*_offset(name, *measured))
    target = (base[0] + nx, base[1] + ny)
    align = getattr(TextEntityAlignment, name)
    if name in ("ALIGNED", "FIT"):
        ex, ey = turned(measured[0], 0.0)
        text.set_placement(target, (base[0] + ex, base[1] + ey), align=align)
    else:
        text.set_placement(target, align=align)
