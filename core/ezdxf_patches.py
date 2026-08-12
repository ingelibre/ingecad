# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Targeted runtime fixes for ezdxf bugs that corrupt real drawings.

Applied once at import (core.document imports this module). Each patch
documents the upstream defect so it can be dropped when fixed there.
"""
from __future__ import annotations

import math

from ezdxf.entities.polygon import DXFPolygon
from ezdxf.tools import pattern as _pattern_tools

_APPLIED = False


def apply() -> None:
    global _APPLIED
    if _APPLIED:
        return
    _APPLIED = True
    _patch_polygon_transform()
    _patch_mtext_mask_rendering()


def _patch_polygon_transform() -> None:
    """HATCH/MPOLYGON.transform re-applies the FULL pattern rotation/scale.

    ezdxf 1.4.4 DXFPolygon.transform passes the ABSOLUTE new pattern
    scale/angle to Pattern.scale(), but Pattern.scale applies its arguments
    RELATIVE to the already-realized pattern lines (compare with
    set_pattern_angle, which passes ``angle - dxf.pattern_angle``). Every
    transform therefore rotates the pattern lines by the full pattern angle
    again — a pure translation (MOVE/COPY/paste) visibly re-orients the
    pattern, corrupts it cumulatively, and can explode ezdxf's hatching
    density (a 0.01 s AR-SAND hatch became 2 s after one paste).

    Fix: snapshot the realized lines, let the original transform update the
    dxf header fields (those ARE computed correctly), then rebuild the lines
    from the snapshot with the RELATIVE delta.

    Reported upstream: https://github.com/mozman/ezdxf/issues/1399 (still
    present on master/1.4.5b0 — the scale half was fixed there, the angle
    half was not). Drop this patch once a fixed release ships.
    """
    original = DXFPolygon.transform

    def transform(self, m):
        pattern = self.pattern if self.has_pattern_fill else None
        snapshot = pattern.as_list() if pattern and pattern.lines else None
        old_scale = self.dxf.pattern_scale
        old_angle = self.dxf.pattern_angle
        result = original(self, m)
        if snapshot is not None and self.pattern:
            factor = (self.dxf.pattern_scale / old_scale
                      if old_scale not in (0, 0.0) else 1.0)
            delta = self.dxf.pattern_angle - old_angle
            if math.isclose(factor, 1.0) and math.isclose(delta, 0.0):
                rebuilt = snapshot
            else:
                rebuilt = _pattern_tools.scale_pattern(
                    snapshot, factor=factor, angle=delta)
            self.pattern.clear()
            for line in rebuilt:
                self.pattern.add_line(*line)
        return result

    transform._ingecad_patch = True  # marker for tests / idempotence
    DXFPolygon.transform = transform


def _patch_mtext_mask_rendering() -> None:
    """A background mask on a PLAIN mtext never renders.

    The drawing add-on draws the mask only in its complex-mtext renderer,
    and ``is_complex_mtext`` routes there on columns, inline codes or an
    exotic text style — not on ``bg_fill``. An MTEXT with a mask but no
    formatting takes the simple path, which ignores the mask entirely, so
    AutoCAD shows the opaque background and our canvas does not.

    Route masked mtext through the complex renderer, whose mask support is
    complete (ACI, true colour, canvas colour, text frame).
    """
    from ezdxf.addons.drawing import frontend as _frontend

    original = _frontend.is_complex_mtext

    def is_complex_mtext(mtext) -> bool:
        if mtext.dxf.get("bg_fill", 0):
            return True
        return original(mtext)

    _frontend.is_complex_mtext = is_complex_mtext
