# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The Drawing Window Colors model (AutoCAD's Options ▸ Display ▸ Colors).

AutoCAD keeps one colour per (context, interface element): 2D model space,
sheet/layout and Block editor each have a "Uniform background", and the
crosshair colour lives in the same dialog. This module is the headless
model those settings live in — the dialog edits it, the renderer reads it.

What makes the background more than a clear colour: ACI 7 entities flip
(white over a dark canvas, black over a light one) and text background
masks fill with the canvas colour. Both already key off the layout
properties ezdxf resolves against, so the chosen colour must reach the
render context — see ``TolerantRenderContext`` — and changing it needs a
regen, not just a repaint.
"""
from __future__ import annotations

from PySide6.QtCore import QSettings

#: QSettings keys, one per context.
SETTINGS = {
    "model": "colors/model_background",
    "sheet": "colors/sheet_background",
    "block_editor": "colors/block_editor_background",
}

#: IngeCAD's own defaults — exactly the colours the app has always used.
DEFAULTS = {
    "model": "#212630",         # the cool dark model canvas
    "sheet": "#3C4146",         # the gray desk around the white paper
    "block_editor": "#2D2821",  # the warm dark "you are in the editor" tone
}

#: AutoCAD's "Restore classic colors": black model space. The other two
#: contexts have no classic counterpart here, so they restore to defaults.
CLASSIC = {
    "model": "#000000",
    "sheet": DEFAULTS["sheet"],
    "block_editor": DEFAULTS["block_editor"],
}


def _valid(value: str) -> bool:
    return (isinstance(value, str) and len(value) == 7
            and value.startswith("#")
            and all(c in "0123456789abcdefABCDEF" for c in value[1:]))


def background(context: str) -> str:
    """The configured background of ``context``, as ``#RRGGBB``."""
    raw = str(QSettings().value(SETTINGS[context], "") or "")
    return raw if _valid(raw) else DEFAULTS[context]


def set_background(context: str, color: str) -> None:
    if not _valid(color):
        raise ValueError(f"not an #RRGGBB color: {color!r}")
    QSettings().setValue(SETTINGS[context], color)


def restore(context: str) -> None:
    """Back to IngeCAD's default for one context."""
    QSettings().remove(SETTINGS[context])


def restore_all() -> None:
    for context in SETTINGS:
        restore(context)


def restore_classic() -> None:
    """AutoCAD's classic look: black model space."""
    for context, color in CLASSIC.items():
        set_background(context, color)


def rgba(context: str) -> tuple[float, float, float, float]:
    """The background as GL floats, for ``scene.background``."""
    value = background(context)
    return (int(value[1:3], 16) / 255.0,
            int(value[3:5], 16) / 255.0,
            int(value[5:7], 16) / 255.0,
            1.0)


def is_light(context: str) -> bool:
    r, g, b, _a = rgba(context)
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) > 0.5
