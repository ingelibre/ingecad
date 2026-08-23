# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A sheet must not redraw the model it does not show.

Measured on a real sheet with ten viewports: rebuilding it cost 4 742 ms, of
which 4 264 ms were the ten viewport passes — every pass the same price,
because nothing cached. Yet each viewport shows between 0.5% and 18% of the
model: **94% of that work was on entities no viewport displays**, processed in
full and then clipped away.

Culling them is exact by construction — what falls outside the rectangle is
what the clipper discards — but only if every doubt resolves towards drawing.
That is what these tests pin: the rectangle carries a margin, a twisted
viewport gets the larger circumscribed rectangle, and anything unmeasurable
is never skipped.
"""
from __future__ import annotations

import sys
from pathlib import Path

import ezdxf
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from render.backend import (VIEWPORT_CULL_MARGIN,  # noqa: E402
                            _viewport_model_rect)


class _Fake:
    """The handful of DXF attributes the rectangle is read from."""

    def __init__(self, **attrs):
        self._attrs = attrs

    def __getattr__(self, name):
        try:
            return self._attrs[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def get(self, name, default=None):
        return self._attrs.get(name, default)


def _vp(**attrs):
    base = dict(view_center_point=(0.0, 0.0), view_height=100.0,
                width=200.0, height=100.0)
    base.update(attrs)
    return type("VP", (), {"dxf": _Fake(**base)})()


def test_the_rectangle_is_the_view_plus_a_margin() -> None:
    x0, y0, x1, y1 = _viewport_model_rect(_vp())
    # view is 200 x 100 in model units (aspect 2), centred on the origin
    assert (x1 - x0) == pytest.approx(200.0 * (1 + 2 * VIEWPORT_CULL_MARGIN))
    assert (y1 - y0) == pytest.approx(100.0 * (1 + 2 * VIEWPORT_CULL_MARGIN))
    assert x0 < -100.0 and x1 > 100.0        # strictly bigger than the view


def test_a_twisted_viewport_gets_a_bigger_rectangle() -> None:
    """Circumscribing the rotated view is safe; inscribing it would clip."""
    plain = _viewport_model_rect(_vp())
    turned = _viewport_model_rect(_vp(view_twist_angle=45.0))
    assert (turned[2] - turned[0]) > (plain[2] - plain[0])
    assert (turned[3] - turned[1]) > (plain[3] - plain[1])


def test_anything_unstatable_culls_nothing() -> None:
    assert _viewport_model_rect(_vp(view_height=0.0)) is None
    assert _viewport_model_rect(_vp(view_height=float("inf"))) is None
    assert _viewport_model_rect(_vp(view_height=float("nan"))) is None
    assert _viewport_model_rect(
        _vp(view_center_point=(float("nan"), 0.0))) is None
    assert _viewport_model_rect(type("VP", (), {"dxf": _Fake()})()) is None


def test_a_broken_aspect_falls_back_to_square_not_to_nothing() -> None:
    rect = _viewport_model_rect(_vp(height=0.0))
    assert rect is not None
    assert (rect[2] - rect[0]) == (rect[3] - rect[1])


def test_an_entity_outside_the_view_is_skipped_and_one_inside_is_not() -> None:
    from render.backend import (TolerantFrontend, TolerantRenderContext,
                                VertexBackend, frontend_config)

    doc = ezdxf.new(setup=True)
    msp = doc.modelspace()
    inside = msp.add_line((0, 0), (10, 10))
    outside = msp.add_line((10_000, 10_000), (10_010, 10_010))

    backend = VertexBackend(0.01)
    frontend = TolerantFrontend(TolerantRenderContext(doc), backend,
                                frontend_config(0.01))
    assert frontend._outside_viewport(outside) is False   # no viewport active

    frontend._vp_rect = _viewport_model_rect(_vp())
    assert frontend._outside_viewport(inside) is False
    assert frontend._outside_viewport(outside) is True


def test_an_unmeasurable_entity_is_never_skipped() -> None:
    from render.backend import (TolerantFrontend, TolerantRenderContext,
                                VertexBackend, frontend_config)

    doc = ezdxf.new(setup=True)
    backend = VertexBackend(0.01)
    frontend = TolerantFrontend(TolerantRenderContext(doc), backend,
                                frontend_config(0.01))
    frontend._vp_rect = _viewport_model_rect(_vp())

    class Unmeasurable:
        def __getattr__(self, name):
            raise RuntimeError("no bounding box for you")

    assert frontend._outside_viewport(Unmeasurable()) is False


def test_a_viewport_showing_everything_measures_nothing() -> None:
    """Culling that can skip nothing must not be paid for.

    A one-viewport sheet is exactly this: the rectangle already contains the
    drawing, so measuring every entity to discover that is pure loss.
    """
    from render.backend import _rect_covers_model

    doc = ezdxf.new(setup=True)
    doc.header["$EXTMIN"] = (0, 0, 0)
    doc.header["$EXTMAX"] = (50, 50, 0)
    vp = _vp()
    vp.doc = doc

    assert _rect_covers_model((-1, -1, 100, 100), vp) is True
    assert _rect_covers_model((10, 10, 40, 40), vp) is False   # shows a part
    assert _rect_covers_model((-1, -1, 49, 100), vp) is False  # misses a strip


def test_unknown_extents_keep_the_culling() -> None:
    """Doubt resolves towards culling here: it is never wrong, only slower."""
    from render.backend import _rect_covers_model

    doc = ezdxf.new(setup=True)
    doc.header["$EXTMIN"] = (1e20, 1e20, 0)      # never regenerated
    doc.header["$EXTMAX"] = (-1e20, -1e20, 0)
    vp = _vp()
    vp.doc = doc
    assert _rect_covers_model((-1e30, -1e30, 1e30, 1e30), vp) is False

    orphan = _vp()                               # no document at all
    assert _rect_covers_model((-1, -1, 1, 1), orphan) is False
