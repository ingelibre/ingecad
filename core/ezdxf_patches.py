# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Targeted runtime fixes for ezdxf bugs that corrupt real drawings.

Applied once at import (core.document imports this module). Each patch
documents the upstream defect so it can be dropped when fixed there.
"""
from __future__ import annotations

import math

from ezdxf.entities.lwpolyline import (DEFAULT_FORMAT, FORMAT_CODES,
                                       LWPolyline, format_point)
from ezdxf.entities.polygon import DXFPolygon
from ezdxf.math import Vec2 as _Vec2
from ezdxf.tools import pattern as _pattern_tools

_APPLIED = False


def apply() -> None:
    global _APPLIED
    if _APPLIED:
        return
    _APPLIED = True
    _patch_polygon_transform()
    _patch_mtext_mask_rendering()
    _patch_bold_italic_font_matching()
    _patch_lwpolyline_get_points()
    _patch_radial_dimension_layout()


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


def _patch_bold_italic_font_matching() -> None:
    """``\\fArial|b1;`` renders exactly like regular text.

    The text renderer asks ``fonts.find_best_match`` for the run's font
    with the right ``weight``/``italic`` — but leaves ``style`` at its
    default ``"Regular"``. The matcher filters by style FIRST, and when
    that leaves a single face (the regular one, since bold faces are
    styled ``"Bold"``) it returns it immediately, never reaching the
    weight comparison. Result: bold and italic are silently dropped for
    every font whose family ships separate weight files — i.e. all of
    them.

    Translate the weight/italic request into the style string the cache
    actually uses; fall back to the original request when the family has
    no such face (the sort-by-weight tail then still picks the closest).
    """
    from ezdxf.fonts import fonts as _fonts

    original = _fonts.find_best_match

    def find_best_match(*, family="sans-serif", style="Regular", weight=400,
                        width=5, italic=False):
        if style == "Regular" and (weight >= 600 or italic):
            wanted = ("Bold Italic" if weight >= 600 and italic
                      else "Bold" if weight >= 600 else "Italic")
            found = original(family=family, style=wanted, weight=weight,
                             width=width, italic=italic)
            if found is not None:
                return found
        return original(family=family, style=style, weight=weight,
                        width=width, italic=italic)

    find_best_match._ingecad_patch = True
    _fonts.find_best_match = find_best_match


#: One accessor per format code, so any format keeps ``format_point``'s exact
#: semantics: components come out in the order the string lists them, unknown
#: characters are skipped, and ``v`` is the (x, y) pair as one tuple.
_POINT_PART = {
    "x": lambda p: p[0],
    "y": lambda p: p[1],
    "s": lambda p: p[2],
    "e": lambda p: p[3],
    "b": lambda p: p[4],
    "v": lambda p: (p[0], p[1]),
}


def _patch_lwpolyline_get_points() -> None:
    """``LWPolyline.get_points`` builds a dict per point, via ``locals()``.

    Not a correctness bug -- a cost. ``format_point`` calls ``locals()`` to
    look components up by name, so reading one polyline's vertices allocates
    one dictionary per vertex. Profiling a regen of a 10 847-entity plan put
    that path at ~20% of the whole rebuild: 2 million calls, because the
    drawing frontend asks every LWPOLYLINE for its points as "xyb" on the way
    to a Path.

    The replacement resolves the format ONCE per call and then indexes the
    packed values, which measured 7.6x faster (144 ms -> 19 ms for 200 000
    points) and returns the same tuples. Drop this patch if ezdxf stops
    rebuilding a namespace per vertex.
    """
    if getattr(LWPolyline.get_points, "_ingecad_patch", False):
        return

    def get_points(self, format: str = DEFAULT_FORMAT):
        codes = [c for c in format.lower() if c in FORMAT_CODES]
        if codes == ["x", "y", "b"]:
            # what ezdxf.path asks for, and the reason this patch exists
            return [(p[0], p[1], p[4]) for p in self.lwpoints]
        if codes == ["x", "y", "s", "e", "b"]:
            return [tuple(p) for p in self.lwpoints]
        try:
            parts = [_POINT_PART[c] for c in codes]
        except KeyError:      # a code we do not know: let ezdxf answer
            return [format_point(p, format=format) for p in self.lwpoints]
        return [tuple(part(p) for part in parts) for p in self.lwpoints]

    get_points.__doc__ = LWPolyline.get_points.__doc__
    get_points._ingecad_patch = True
    LWPolyline.get_points = get_points


def _patch_radial_dimension_layout() -> None:
    """DIMRADIUS / DIMDIAMETER with the text outside and DIMTOFL on.

    The norm (ISO 129-1 / UNE 1-039) and AutoCAD's metric ISO-25 style, whose
    DIMTOFL is on, draw the dimension line across the circle with the
    arrowheads INSIDE it -- tips on the circle pointing outward, one on each
    side of the diameter -- and the text outside on an extension of that
    line. When the circle is too small for the arrowheads they go outside,
    tips on the circle pointing in, and the line still runs across.

    ezdxf 1.4 draws neither. With a default location the near arrow sits
    outside pointing in while the far one sits inside pointing out (both
    INSERTs carry the same rotation); with a user location and DIMTMOVE 0/1
    the far arrow is missing and the line stops at the centre. A tester
    flagged the diameter dimension as "fuera de norma" for exactly that.

    Text inside, or DIMTOFL off (the imperial Standard style), keep ezdxf's
    own paths. DIMTMOVE 2 (text moved freely, no leader) keeps ezdxf's
    across-the-circle layout without the extension, as the variable says;
    ezdxf reads an unset DIMTMOVE as 2 where AutoCAD's default is 0, so the
    value is read here with AutoCAD's default.
    """
    from ezdxf.render.dim_diameter import DiameterDimension
    from ezdxf.render.dim_radius import RadiusDimension

    if getattr(RadiusDimension.render_user_location, "_ingecad_patch", False):
        return

    def iso_case(self) -> bool:
        m = self.measurement
        return (bool(m.text_is_outside) and bool(self.outside_text_force_dimline)
                and self.dim_style.get("dimtmove", 0) != 2)

    def arrows_fit_inside(self) -> bool:
        """Room for the arrowheads inside the circle, with the text gap."""
        need = self.arrows.arrow_size + self.measurement.text_gap
        if self.dimension.dimtype == 4:      # radius: between centre and circle
            return self.radius >= need
        return 2.0 * self.radius >= 2.0 * need

    def ext_line(self, start, user: bool) -> None:
        """The extension from the circle (or the outside arrow) to the text."""
        m = self.measurement
        if m.text_outside_horizontal:
            if user:
                self.add_horiz_ext_line_user(start)
            else:
                self.add_horiz_ext_line_default(start)
        elif user:
            self.add_radial_ext_line_user(start)
        else:
            self.add_radial_ext_line_default(start)

    # -- radius -----------------------------------------------------------------
    radius_user = RadiusDimension.render_user_location
    radius_default = RadiusDimension.render_default_location
    radius_text = RadiusDimension.get_default_text_location

    def radius_iso(self, user: bool) -> None:
        inside = arrows_fit_inside(self)
        if self.arrows.suppress1:
            base = self.point_on_circle
        else:
            base = self.add_arrow(self.point_on_circle, rotate=not inside)
        if inside:
            self.add_radial_dim_line(base)          # centre to the arrow's base
            ext_line(self, self.point_on_circle, user)
        else:
            self.add_radial_dim_line(self.point_on_circle)
            ext_line(self, base, user)

    def render_user_location_radius(self) -> None:
        if iso_case(self):
            radius_iso(self, user=True)
        else:
            radius_user(self)

    def render_default_location_radius(self) -> None:
        if iso_case(self):
            radius_iso(self, user=False)
        else:
            radius_default(self)

    def default_text_location(self, original):
        """With the arrowhead inside there is no arrow between the circle
        and the text: the default text sits a gap past the circle."""
        m = self.measurement
        if (iso_case(self) and not m.text_outside_horizontal
                and arrows_fit_inside(self)):
            text_direction = _Vec2.from_deg_angle(m.text_rotation)
            vertical = text_direction.orthogonal(ccw=True)
            hdist = self._total_text_width / 2.0 + m.text_gap
            midpoint = self.point_on_circle + self.dim_line_vec * hdist
            return midpoint + vertical * m.text_vertical_distance()
        return original(self)

    def get_default_text_location_radius(self):
        return default_text_location(self, radius_text)

    # -- diameter ---------------------------------------------------------------
    diameter_user = DiameterDimension.render_user_location
    diameter_default = DiameterDimension.render_default_location
    diameter_text = DiameterDimension.get_default_text_location

    def diameter_iso(self, user: bool) -> None:
        inside = arrows_fit_inside(self)
        # arrow 1 sits on the text side, arrow 2 across the circle
        near = self._add_arrow_1(rotate=not inside)
        far = self._add_arrow_2(rotate=inside)
        if inside:
            self.add_diameter_dim_line(near, far)   # base to base, through the centre
            ext_line(self, self.point_on_circle, user)
        else:
            self.add_diameter_dim_line(self.point_on_circle, self.point_on_circle2)
            ext_line(self, near, user)

    def render_user_location_diameter(self) -> None:
        if iso_case(self):
            diameter_iso(self, user=True)
        else:
            diameter_user(self)

    def render_default_location_diameter(self) -> None:
        if iso_case(self):
            diameter_iso(self, user=False)
        else:
            diameter_default(self)

    def get_default_text_location_diameter(self):
        return default_text_location(self, diameter_text)

    for cls, user, default, text in (
            (RadiusDimension, render_user_location_radius,
             render_default_location_radius, get_default_text_location_radius),
            (DiameterDimension, render_user_location_diameter,
             render_default_location_diameter,
             get_default_text_location_diameter)):
        user._ingecad_patch = True
        cls.render_user_location = user
        cls.render_default_location = default
        cls.get_default_text_location = text
