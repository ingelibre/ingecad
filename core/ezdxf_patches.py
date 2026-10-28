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
    _patch_exact_family_fonts()
    _patch_bold_italic_font_matching()
    _patch_metric_compatible_fonts()
    _patch_annotative_dimension_scales()
    _patch_lwpolyline_get_points()
    _patch_radial_dimension_layout()
    _patch_linear_dimension_direction()
    _patch_dxfreplace_mixed_surrogates()
    _patch_single_vertex_leader()
    _patch_dimrnd_zero()
    _patch_fixed_height_dimension_text()
    _patch_dimension_number_format()
    _patch_underscored_arrow_names()
    _patch_suppressed_dimension_line_arrows()
    _patch_narrow_linear_dimension_text()
    _patch_two_line_angular_sector()
    _patch_three_point_angular_sector()
    _patch_arc_length_symbol_text()
    _patch_dms_angular_text()
    _patch_linetype_dots()


def dms_text(degrees: float, dimadec: int, dimdsep: str = ".",
             trailing: bool = False) -> str:
    """An angle in degrees, minutes and seconds as AutoCAD writes it.

    DIMADEC 0 shows whole degrees, 1 and 2 minutes, 3 and 4 seconds, 5 to 8
    seconds with 1 to 4 decimals. Minutes and seconds are not padded --
    AutoCAD's own text in a colleague's plan reads 60°0'0" (DIMADEC 3) --
    and the rounding is done once, on the last unit shown, so 59.99" never
    reads 60". ``trailing`` drops trailing zeros of the seconds' decimals
    (DIMAZIN).
    """
    sign = "-" if degrees < 0 else ""
    value = abs(degrees)
    precision = max(0, int(dimadec))
    if precision < 1:
        return f"{sign}{int(round(value))}°"
    if precision < 3:
        d, m = divmod(int(round(value * 60.0)), 60)
        return f"{sign}{d}°{m}'"
    places = min(4, max(0, precision - 4))
    scale = 10 ** places
    d, rest = divmod(int(round(value * 3600.0 * scale)), 3600 * scale)
    m, seconds = divmod(rest, 60 * scale)
    whole, fraction = divmod(seconds, scale)
    text = f"{whole}"
    if places:
        digits = f"{fraction:0{places}d}"
        if trailing:
            digits = digits.rstrip("0")
        if digits:
            text += (dimdsep or ".") + digits
    return f"{sign}{d}°{m}'{text}\""


def _patch_dms_angular_text() -> None:
    """Degrees, minutes and seconds the way AutoCAD writes them.

    ezdxf rounded the seconds to DIMADEC-5 places and then printed them
    with DIMADEC decimals (45°26'7.00000" for 7.5"), and its rounding could
    leave 60" (GeoCad Yaguarete had to patch it). See ``dms_text``.
    """
    from ezdxf.render import dim_curved

    original = dim_curved.format_angular_text
    if getattr(original, "_ingecad_patch", False):
        return

    def format_angular_text(value, angle_units, dimrnd, dimdec, dimzin,
                            dimdsep):
        if angle_units == 1:
            degrees = math.degrees(value)
            if dimrnd:
                degrees = round(degrees / dimrnd) * dimrnd
            return dms_text(degrees, dimdec, dimdsep,
                            trailing=bool(int(dimzin or 0) & 8))
        return original(value, angle_units, dimrnd, dimdec, dimzin, dimdsep)

    format_angular_text._ingecad_patch = True
    dim_curved.format_angular_text = format_angular_text


def _patch_dimrnd_zero() -> None:
    """DIMRND 0 means "no rounding", as AutoCAD reads it.

    ezdxf hands DIMRND straight to ``xround``, where 0 means "remove the
    fraction", so every dimension of a style with DIMRND written as 0 -- an
    OK in the Modify Dimension Style dialog, or a colleague's drawing that
    carries the default explicitly -- lost its decimals on the next redraw
    (12.35 drawn as 12; Rafael's sixth review).
    """
    from ezdxf.render.dim_base import Measurement

    if getattr(Measurement.__init__, "_ingecad_patch", False):
        return
    original = Measurement.__init__

    def __init__(self, *args, **kwargs):
        original(self, *args, **kwargs)
        if not self.text_round:
            self.text_round = None

    __init__._ingecad_patch = True
    Measurement.__init__ = __init__


def _patch_fixed_height_dimension_text() -> None:
    """A text style with a fixed height sets a dimension's text unscaled;
    a negative DIMLFAC scales only in paper space.

    AutoCAD uses that height as it is -- DIMSCALE does not touch it -- but
    ezdxf multiplied it by DIMSCALE, so every redraw of such a dimension
    (a grip, STRETCH, a property change) blew its text up: a colleague's
    portico plan (DIMSCALE 304.8, style height 62.5) went from 62.5 to
    19050 on the first grip drop. The authors' own blocks are the judge:
    all 130 such dimensions of nine corpus plans carry the bare height.
    Drop it if ezdxf stops scaling a fixed height.

    An ANNOTATIVE text style is the exception: its height is a paper
    height, so the dimension's scale multiplies it like DIMTXT -- held
    bare, an annotative dimension kept a 2.5 text at 1:50 and 1:100 while
    its arrows grew (#85, Rafael).
    """
    from ezdxf.render import dim_base
    from ezdxf.render.dim_base import Measurement

    from core import annotative

    if getattr(Measurement.__init__, "_ingecad_fixed_height", False):
        return
    original = Measurement.__init__

    def __init__(self, dim_style, *args, **kwargs):
        original(self, dim_style, *args, **kwargs)
        doc = dim_style.dimension.doc
        text_style = dim_base.get_text_style(doc, self.text_style_name)
        height = text_style.dxf.get("height", 0.0)
        if height > 0.0 and not annotative.is_annotative(text_style):
            self.text_height = height
        if self.measurement_factor < 0.0:
            # "negative values are applied to paper space only" (DIMLFAC):
            # a model-space dimension read -10.00 for 10 (a corpus plan).
            self.measurement_factor = -self.measurement_factor \
                if _in_paper_space(dim_style.dimension) else 1.0

    __init__._ingecad_patch = True
    __init__._ingecad_fixed_height = True
    Measurement.__init__ = __init__


def _in_paper_space(entity) -> bool:
    """True when ``entity`` sits directly on a paper-space layout."""
    doc = entity.doc
    owner = entity.dxf.get("owner", None)
    if doc is None or owner is None:
        return False
    record = doc.entitydb.get(owner)
    return record is not None and record.dxftype() == "BLOCK_RECORD" \
        and record.is_any_paperspace


def _patch_dimension_number_format() -> None:
    """Dimension numbers round as AutoCAD rounds them, and a DIMPOST without
    ``<>`` is a suffix.

    ezdxf formats with Python's ``{:.2f}``: ties go to the even digit and
    float noise decides the rest, so 0.405 read ".40", 2.625 "2.62" and a
    measured 2.99499999999 "2.99" where the author's AutoCAD wrote .41, 2.63
    and 3.00 (158 dimensions of 55 corpus plans after a no-op grip). Half
    rounds away from zero here, after a relative nudge of 3e-11: AutoCAD
    reads 2.99499999999 as 3.00 but 0.3149999999437 as .31, and of 0, 1e-11,
    3e-11, 1e-10 and 1e-9 it is the one that matches the most corpus
    dimensions.

    A DIMPOST of "m" or " Tub.PVC 63mm" -- no ``<>`` -- made ezdxf raise,
    aborting every edit of those dimensions (2141 of them in 53 plans);
    AutoCAD appends it to the number (DIMPOST, Command Reference).
    """
    from decimal import ROUND_HALF_UP, Decimal

    from ezdxf.render import dim_base

    if getattr(dim_base.format_text, "_ingecad_patch", False):
        return
    original_format = dim_base.format_text
    original_post = dim_base.apply_dimpost

    def format_text(value, dimrnd=None, dimdec=2, dimzin=0, dimdsep="."):
        if dimdec is not None and math.isfinite(value):
            if dimrnd:
                value = dim_base.xround(value, dimrnd)
                dimrnd = None
            nudged = value + math.copysign(3e-11 * max(1.0, abs(value)), value)
            value = float(Decimal(repr(nudged)).quantize(
                Decimal(1).scaleb(-int(dimdec)), rounding=ROUND_HALF_UP))
        return original_format(value, dimrnd, dimdec, dimzin, dimdsep)

    def apply_dimpost(text, dimpost):
        if "<>" not in dimpost:
            return text + dimpost
        return original_post(text, dimpost)

    format_text._ingecad_patch = True
    dim_base.format_text = format_text
    dim_base.apply_dimpost = apply_dimpost


def _patch_underscored_arrow_names() -> None:
    """``_NONE`` (or any standard arrow written with AutoCAD's leading
    underscore) is that arrow even when the drawing has no block of the name.

    ezdxf looked for a user block called "_NONE", found none, and raised
    "Undefined block": every edit of 1314 dimensions in 8 corpus plans
    aborted. When the block exists it is still used as it is.
    """
    from ezdxf.render.arrows import ARROWS
    from ezdxf.render.dim_base import BaseDimensionRenderer

    if getattr(BaseDimensionRenderer.add_blockref, "_ingecad_patch", False):
        return
    original = BaseDimensionRenderer.add_blockref

    def add_blockref(self, name, *args, **kwargs):
        if name and name not in ARROWS and name.startswith("_") \
                and not self.geometry.has_block(name) and name[1:] in ARROWS:
            name = name[1:]
        return original(self, name, *args, **kwargs)

    add_blockref._ingecad_patch = True
    BaseDimensionRenderer.add_blockref = add_blockref


def _patch_suppressed_dimension_line_arrows() -> None:
    """DIMSD1/DIMSD2 suppress "the first dimension line and arrowhead"
    (DIMSD1, Command Reference); ezdxf dropped the line and kept drawing the
    arrow, so a redrawn dimension sprouted ticks its author had suppressed
    (arrow-count mismatches 2980 -> 112 over a corpus sample with this)."""
    from ezdxf.render.dim_base import BaseDimensionRenderer

    if getattr(BaseDimensionRenderer.__init__, "_ingecad_patch", False):
        return
    original = BaseDimensionRenderer.__init__

    def __init__(self, *args, **kwargs):
        original(self, *args, **kwargs)
        line = getattr(self, "dimension_line", None)
        arrows = getattr(self, "arrows", None)
        if line is not None and arrows is not None:
            arrows.suppress1 = arrows.suppress1 or line.suppress1
            arrows.suppress2 = arrows.suppress2 or line.suppress2

    __init__._ingecad_patch = True
    BaseDimensionRenderer.__init__ = __init__


def _patch_narrow_linear_dimension_text() -> None:
    """Text that does not fit between the extension lines goes BESIDE them.

    DIMTMOVE 0 ("Beside the dimension line", the ISO-25 and AutoCAD
    default) moves the text with the dimension line: outside, past the
    second extension line (the first with DIMJUST 1), past the arrowhead
    when that went outside too, at the same distance above the line as any
    other dimension, and the dimension line runs on under it. ezdxf left
    such text centred between the extension lines -- on top of them and of
    the arrows -- and lifted it above their ends (DIMEXE more than every
    other dimension's text): a 2.56 mm dimension of a tester's part read
    "ahogada" and "despegada de la línea" next to well-placed ones (#102).

    Placed by hand (a user location), over the line (DIMTMOVE 1/2) or forced
    inside (DIMTIX), ezdxf's own layout stands.

    Whether the text fits, and how far it then sits, takes its real width in
    the dimension's text style, as AutoCAD measures it: ezdxf counted every
    character as wide as it is tall ("2,56" = 10 mm at 2.5), which pushed
    text out of spaces it fits in and left a gap before text set beside.
    """
    from ezdxf.render.dim_base import Measurement
    from ezdxf.render.dim_linear import LinearDimension

    if getattr(LinearDimension.default_text_location, "_ingecad_patch", False):
        return
    original_measurement_init = Measurement.__init__
    estimate = Measurement.text_width

    def measurement_init(self, dim_style, *args, **kwargs):
        original_measurement_init(self, dim_style, *args, **kwargs)
        font = None
        try:
            style = dim_style.doc.styles.get(self.text_style_name)
            font = style.dxf.font or None
        except Exception:
            pass
        self._ingecad_font = font

    def text_width(self, text: str) -> float:
        font = getattr(self, "_ingecad_font", None)
        if font and text and "\\" not in text and "{" not in text:
            try:
                from ezdxf.fonts import fonts

                return fonts.make_font(font, self.text_height,
                                       self.text_width_factor).text_width(text)
            except Exception:
                pass
        return estimate(self, text)       # stacked/formatted text: ezdxf's guess

    Measurement.__init__ = measurement_init
    Measurement.text_width = text_width
    original_location = LinearDimension.default_text_location
    original_extensions = LinearDimension.add_arrow_extension_lines
    original_line = LinearDimension.add_dimension_line

    def beside(self) -> bool:
        m = self.measurement
        try:
            rule = int(self.dim_style.get("dimtmove", 0) or 0)
        except (TypeError, ValueError):
            rule = 0
        return (m.text_is_outside and m.user_location is None
                and m.text_halign in (0, 1, 2) and rule == 0)

    def default_text_location(self):
        self._ingecad_beside = None
        if not beside(self):
            return original_location(self)
        m = self.measurement
        first = m.text_halign == 1
        anchor = self.dim_line_start if first else self.dim_line_end
        out = -self.dim_line_vec if first else self.dim_line_vec
        arrow = (self.arrows.arrow_size
                 if self.arrows_outside and not self.arrows.has_ticks else 0.0)
        near = arrow + m.text_gap
        self._ingecad_beside = (first, arrow, near + self._total_text_width)
        location = anchor + out * (near + self._total_text_width / 2.0)
        return location + self.dim_line_vec.orthogonal().normalize(
            m.text_vertical_distance())

    def add_arrow_extension_lines(self):
        side = getattr(self, "_ingecad_beside", None)
        if side is None or self.measurement.vertical_placement == 0:
            return original_extensions(self)
        # the text side's tail is drawn, longer, by add_dimension_line
        arrows = self.arrows
        attr = "suppress1" if side[0] else "suppress2"
        kept = getattr(arrows, attr)
        setattr(arrows, attr, True)
        try:
            original_extensions(self)
        finally:
            setattr(arrows, attr, kept)

    def add_dimension_line(self, start, end):
        original_line(self, start, end)
        side = getattr(self, "_ingecad_beside", None)
        if side is None or self.measurement.vertical_placement == 0:
            return              # centred text: no line through it
        first, arrow, far = side
        anchor = self.dim_line_start if first else self.dim_line_end
        out = -self.dim_line_vec if first else self.dim_line_vec
        self.add_line(anchor + out * arrow, anchor + out * far,
                      dxfattribs=self.dimension_line.dxfattribs())

    default_text_location._ingecad_patch = True
    LinearDimension.default_text_location = default_text_location
    LinearDimension.add_arrow_extension_lines = add_arrow_extension_lines
    LinearDimension.add_dimension_line = add_dimension_line


def _patch_two_line_angular_sector() -> None:
    """A 2-line angular dimension measures the sector its arc point (16)
    lies in, as AutoCAD does.

    Two lines make four angles; ezdxf took the rays from the line ends
    farthest from the vertex and went counter-clockwise from the first to
    the second, whatever the arc point said: a 27 degree dimension read 333.
    Each ray is turned so that the arc point lies between the two, and they
    are ordered counter-clockwise across it.
    """
    from ezdxf.render.dim_curved import AngularDimension

    if getattr(AngularDimension.get_ext1_dir, "_ingecad_patch", False):
        return
    original1 = AngularDimension.get_ext1_dir
    original2 = AngularDimension.get_ext2_dir

    def sector(self):
        cached = self.__dict__.get("_ingecad_sector")
        if cached is not None:
            return cached
        d1, d2 = original1(self), original2(self)
        result = (d1, d2)
        arc = self.dim_line_location - self.center_of_arc
        def cross(u, v):
            return u.x * v.y - u.y * v.x

        if arc.magnitude > 1e-12:
            arc = arc.normalize()
            for s1 in (d1, -d1):
                for s2 in (d2, -d2):
                    a, b = (s1, s2) if cross(s1, s2) >= 0 else (s2, s1)
                    # arc inside the counter-clockwise sector a -> b
                    if cross(a, arc) >= -1e-12 and cross(arc, b) >= -1e-12:
                        result = (a, b)
                        break
                else:
                    continue
                break
        self.__dict__["_ingecad_sector"] = result
        return result

    def get_ext1_dir(self):
        return sector(self)[0]

    def get_ext2_dir(self):
        return sector(self)[1]

    get_ext1_dir._ingecad_patch = True
    AngularDimension.get_ext1_dir = get_ext1_dir
    AngularDimension.get_ext2_dir = get_ext2_dir


def _patch_three_point_angular_sector() -> None:
    """A 3-point angular dimension measures the side its arc (10) is on.

    ezdxf always went counter-clockwise from the first point to the second,
    so a dimension drawn on the other side read 360 minus its angle (158
    for 202): 326 of 709 in a corpus sample. When the arc lies outside that
    sweep, the two legs are taken the other way round.
    """
    import math

    from ezdxf.render.dim_curved import Angular3PDimension

    if getattr(Angular3PDimension.__init__, "_ingecad_patch", False):
        return
    original = Angular3PDimension.__init__

    def ccw(a, b) -> float:
        return (math.atan2(b.y, b.x) - math.atan2(a.y, a.x)) % math.tau

    def __init__(self, dimension, ucs=None, override=None):
        dxf = dimension.dxf
        center = dxf.get("defpoint4", None)
        p1, p2 = dxf.get("defpoint2", None), dxf.get("defpoint3", None)
        arc = dxf.get("defpoint", None)
        swap = False
        if all(v is not None for v in (center, p1, p2, arc)):
            d1, d2, da = p1 - center, p2 - center, arc - center
            if da.magnitude > 1e-12 and d1.magnitude > 1e-12 \
                    and d2.magnitude > 1e-12:
                swap = ccw(d1, da) > ccw(d1, d2) + 1e-12
        if swap:
            dxf.defpoint2, dxf.defpoint3 = p2, p1
        try:
            original(self, dimension, ucs, override)
        finally:
            if swap:
                dxf.defpoint2, dxf.defpoint3 = p1, p2

    __init__._ingecad_patch = True
    Angular3PDimension.__init__ = __init__


def _patch_arc_length_symbol_text() -> None:
    """No "( " in front of an arc length.

    DIMARCSYM 0 (the default) puts AutoCAD's arc symbol before the number;
    AutoCAD draws it as an ARC in the block, never as text. ezdxf wrote the
    two characters "( " instead, so every arc-length dimension redrawn from
    a colleague's plan read "( 6,62" for "6,62". The number now matches;
    the little arc itself is not drawn yet.
    """
    from ezdxf.render.dim_curved import ArcLengthMeasurement

    # its own flag: the inherited Measurement.__init__ already carries
    # _ingecad_patch, which would make this return before patching
    if getattr(ArcLengthMeasurement.__init__, "_ingecad_arc_prefix", False):
        return
    original = ArcLengthMeasurement.__init__

    def __init__(self, *args, **kwargs):
        original(self, *args, **kwargs)
        self.has_arc_length_prefix = False

    __init__._ingecad_patch = True
    __init__._ingecad_arc_prefix = True
    ArcLengthMeasurement.__init__ = __init__


def _patch_single_vertex_leader() -> None:
    """A LEADER with a single vertex is written and kept, not dropped.

    ezdxf 1.4 requires two vertices: ``Leader.preprocess_export`` skips a
    LEADER with fewer, and ``Leader.audit`` (run by ``recover.readfile``)
    deletes it. Real drawings carry them — all 73 leaders of a road plan in
    the corpus have one vertex, and ODA File Converter reads them as such —
    so Save as DWG and Save as DXF silently lost every one. With the patch
    only a LEADER without any vertex is refused. Drop it if ezdxf accepts a
    single vertex.
    """
    from ezdxf.entities.dxfgfx import DXFGraphic
    from ezdxf.entities.leader import Leader

    if getattr(Leader.preprocess_export, "_ingecad_patch", False):
        return
    original_audit = Leader.audit

    def preprocess_export(self, tagwriter) -> bool:
        return len(self.vertices) >= 1

    def audit(self, auditor) -> None:
        if len(self.vertices) >= 1:
            DXFGraphic.audit(self, auditor)   # everything but the count
        else:
            original_audit(self, auditor)

    preprocess_export._ingecad_patch = True
    Leader.preprocess_export = preprocess_export
    Leader.audit = audit


def _dxf_backslash_replace(exc):
    """ezdxf's "dxfreplace" error handler, one character at a time.

    ezdxf 1.4 hands the WHOLE unencodable run to ``surrogateescape`` as soon
    as it meets a lone surrogate U+DC80..U+DCFF (a byte that was not UTF-8
    when the file was read). ``surrogateescape`` then fails on any other
    character in the same run, and the whole save dies with "'charmap'
    codec can't encode characters". Real drawings carry exactly that mix:
    XRECORD groups 300/302 holding binary blobs that LibreDWG emits as text
    (181 such strings in one COFOPRI plan). One corpus sample of 95 had 13
    Save-as-DWG failures from this alone.

    Handling a single character per call lets each kind take its own path:
    the surrogate goes back to the byte it came from — the blob is written
    as it was read — and anything else is escaped as ezdxf does.
    """
    if not isinstance(exc, UnicodeEncodeError):
        return _EZDXF_DXFREPLACE(exc)
    x = ord(exc.object[exc.start])
    if 0xDC80 <= x <= 0xDCFF:
        return bytes([x - 0xDC00]), exc.start + 1
    if x <= 0xFF:
        return "\\x%02x" % x, exc.start + 1
    if x <= 0xFFFF:
        return "\\U+%04x" % x, exc.start + 1
    return "\\U+%08x" % x, exc.start + 1


def _patch_dxfreplace_mixed_surrogates() -> None:
    import codecs

    global _EZDXF_DXFREPLACE
    from ezdxf.lldxf.encoding import dxf_backslash_replace

    _EZDXF_DXFREPLACE = dxf_backslash_replace
    codecs.register_error("dxfreplace", _dxf_backslash_replace)


_EZDXF_DXFREPLACE = None


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


def _patch_exact_family_fonts() -> None:
    """A text in Ubuntu draws in Ubuntu, not in Ubuntu Mono.

    ezdxf picks the font family by PREFIX: "Ubuntu" found "Ubuntu Mono",
    "Noto Sans" found "Noto Sans Sora Sompeng" -- a monospace or a script
    font in place of the one the style names, wherever another family
    starts with the same words (GeoCad Yaguarete had to patch it; fontconfig
    answers both right). When an installed family has exactly the name
    asked for, the choice is made among its faces only, with ezdxf's own
    rule (style, then weight, italic, width). Anything else -- a font that
    is not installed -- goes on to the metric twins below.
    """
    from ezdxf.fonts import font_manager as _fm
    from ezdxf.fonts import fonts as _fonts

    if getattr(_fonts.find_best_match, "_ingecad_exact_family", False):
        return
    original = _fonts.find_best_match

    def find_best_match(*, family="sans-serif", style="Regular", weight=400,
                        width=5, italic=False):
        found = original(family=family, style=style, weight=weight,
                         width=width, italic=italic)
        wanted = _fm.GENERIC_FONT_FAMILY.get(family, family)
        if found is None or found.family.lower() == str(wanted).lower():
            return found
        try:
            cache = _fonts.font_manager._font_cache._cache
        except AttributeError:
            return found
        exact = [e for e in cache.values()
                 if e.font_face.family.lower() == str(wanted).lower()]
        if not exact:
            return found
        styled = _fm.filter_style(style, exact)
        if len(styled) == 1:
            return styled[0].font_face
        pool = styled or exact
        return min(pool, key=lambda e: (
            abs(e.font_face.weight - weight),
            e.font_face.is_italic is not italic,
            abs(e.font_face.width - width))).font_face

    find_best_match._ingecad_patch = True
    find_best_match._ingecad_exact_family = True
    _fonts.find_best_match = find_best_match


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


#: Microsoft's core fonts and the free fonts drawn on their exact metrics,
#: which every Linux desktop ships (Ubuntu installs them by default): a text
#: in Liberation Sans is as long as in Arial, so a title block filled in
#: AutoCAD still fits its boxes. File names as AutoCAD styles store them.
METRIC_COMPATIBLE_FILES = {
    "arial.ttf": "LiberationSans-Regular.ttf",
    "arialbd.ttf": "LiberationSans-Bold.ttf",
    "ariali.ttf": "LiberationSans-Italic.ttf",
    "arialbi.ttf": "LiberationSans-BoldItalic.ttf",
    "arialn.ttf": "LiberationSansNarrow-Regular.ttf",
    "arialnb.ttf": "LiberationSansNarrow-Bold.ttf",
    "times.ttf": "LiberationSerif-Regular.ttf",
    "timesbd.ttf": "LiberationSerif-Bold.ttf",
    "timesi.ttf": "LiberationSerif-Italic.ttf",
    "timesbi.ttf": "LiberationSerif-BoldItalic.ttf",
    "cour.ttf": "LiberationMono-Regular.ttf",
    "courbd.ttf": "LiberationMono-Bold.ttf",
    "couri.ttf": "LiberationMono-Italic.ttf",
    "courbi.ttf": "LiberationMono-BoldItalic.ttf",
}
METRIC_COMPATIBLE_FAMILIES = {
    "arial": "Liberation Sans",
    "arial narrow": "Liberation Sans Narrow",
    "times new roman": "Liberation Serif",
    "courier new": "Liberation Mono",
}
#: The twins share the originals' advance widths per em, but ezdxf -- like
#: AutoCAD -- sizes text by its CAPITAL height, and Liberation's capitals sit
#: lower in the em: drawn at the same height, Liberation Sans came out 4 %
#: wider than Arial (Courier's twin 13 % narrower). Each factor brings the
#: twin back to the original's widths; measured as width(original) /
#: width(twin) over the same text, with both fonts installed. The capitals
#: end up that much shorter, the length is Arial's -- which is what keeps a
#: title block's text inside its boxes.
METRIC_COMPATIBLE_SCALE = {
    "arial.ttf": 0.9611, "arialbd.ttf": 0.9611,
    "ariali.ttf": 0.9611, "arialbi.ttf": 0.9611,
    "arialn.ttf": 0.9611, "arialnb.ttf": 0.9611,
    "times.ttf": 0.9748, "timesbd.ttf": 0.9769,
    "timesi.ttf": 0.9582, "timesbi.ttf": 0.9555,
    "cour.ttf": 1.1530, "courbd.ttf": 1.1121,
    "couri.ttf": 1.1530, "courbi.ttf": 1.1121,
}


_ASKED_BY_TWIN = {twin.lower(): asked for asked, twin in METRIC_COMPATIBLE_FILES.items()}


def _patch_annotative_dimension_scales() -> None:
    """Every redraw or move of a dimension redraws its other scales too.

    An annotative dimension carries one *D block per annotation scale. ezdxf
    redraws (``DimStyleOverride.render``) and moves (``Dimension.transform``)
    only the dimension's own, so after a grip edit, STRETCH, MOVE or a style
    change the other scales showed the dimension as it had been. Hooked here,
    once, rather than at the dozen places that redraw a dimension.
    """
    from ezdxf.entities.dimension import Dimension
    from ezdxf.entities.dimstyleoverride import DimStyleOverride

    if getattr(DimStyleOverride.render, "_ingecad_patch", False):
        return
    original_render = DimStyleOverride.render
    original_transform = Dimension.transform

    def render(self, *args, **kwargs):
        upright_dimension(self.dimension)
        result = original_render(self, *args, **kwargs)
        from core.annotative import refresh_scale_blocks

        refresh_scale_blocks(self.dimension)
        return result

    def transform(self, m):
        result = original_transform(self, m)
        from core.annotative import refresh_scale_blocks

        refresh_scale_blocks(self)
        return result

    render._ingecad_patch = True
    transform._ingecad_patch = True
    DimStyleOverride.render = render
    Dimension.transform = transform


def upright_dimension(dim) -> bool:
    """Turn a mirrored DIMENSION (extrusion 0,0,-1) into the same dimension
    seen from above, before it is redrawn.

    ezdxf writes the redrawn block in WCS but the display still applies the
    dimension's flipped OCS, so every mirrored dimension of a plan jumped to
    -X when it was redrawn (477 of 477 in a fence plan, 1.5 million units
    away). With extrusion (0, 0, -1) an OCS point (x, y, z) is (-x, y, -z)
    in WCS and an angle t is 180 - t; groups 11, 12 and 16 are OCS, the
    other points already WCS. True if it changed.
    """
    dxf = dim.dxf
    extrusion = dxf.get("extrusion", None)
    if extrusion is None or abs(extrusion[0]) > 1e-12 \
            or abs(extrusion[1]) > 1e-12 or extrusion[2] > -0.5:
        return False
    for name in ("text_midpoint", "insert", "defpoint5"):
        if dxf.hasattr(name):
            p = dxf.get(name)
            dxf.set(name, (-p[0], p[1], -p[2]))
    for name in ("angle", "horizontal_direction", "text_rotation"):
        if dxf.hasattr(name) and dxf.is_supported(name):
            dxf.set(name, (180.0 - float(dxf.get(name))) % 360.0)
    dxf.extrusion = (0.0, 0.0, 1.0)
    return True


def add_metric_compatible_synonyms(manager) -> None:
    """Let each Microsoft core font's file name answer with its Liberation
    twin when the font itself is not installed.

    The entry KEEPS the asked name -- its face says "arial.ttf" while its
    file is Liberation's -- so the text renderer still knows Arial was asked
    for and can apply METRIC_COMPATIBLE_SCALE. An installed Arial keeps
    answering for itself.
    """
    from ezdxf.fonts.font_manager import CacheEntry

    cache = manager._font_cache
    for asked, twin in METRIC_COMPATIBLE_FILES.items():
        if asked in cache or twin not in cache:
            continue
        entry = cache[twin]
        cache._cache[cache.key(asked)] = CacheEntry(
            entry.file_path, entry.font_face._replace(filename=asked))


def is_twin_standing_in(manager, name: str) -> bool:
    """Is ``name`` (a Microsoft core font) answered by its Liberation twin?"""
    twin = METRIC_COMPATIBLE_FILES.get(str(name).lower())
    if twin is None:
        return False
    try:
        entry = manager._font_cache[name]
    except KeyError:
        return False
    return entry.file_path.name.lower() == twin.lower()


def _patch_metric_compatible_fonts() -> None:
    """A drawing asking for Arial on a Linux without it gets Liberation Sans.

    The DWG stores a font's NAME. Where the font is missing ezdxf falls back
    to the first of its defaults it finds -- DejaVu Sans Condensed on Linux,
    wider and heavier than Arial, so texts came out bold-looking and longer
    than in AutoCAD (Rafael's PDFs). The fonts made on Arial's, Times New
    Roman's and Courier New's exact widths are what Linux itself substitutes;
    they are used only when the real font is not installed, by file name
    (a text style's "arial.ttf") and by family (MTEXT's ``\\fArial|``).
    """
    from ezdxf.fonts import fonts as _fonts

    if getattr(_fonts.find_best_match, "_ingecad_metric_fonts", False):
        return
    add_metric_compatible_synonyms(_fonts.font_manager)

    original = _fonts.find_best_match

    def find_best_match(*, family="sans-serif", style="Regular", weight=400,
                        width=5, italic=False):
        found = original(family=family, style=style, weight=weight,
                         width=width, italic=italic)
        if found is not None and found.family.lower() == str(family).lower():
            return found
        twin = METRIC_COMPATIBLE_FAMILIES.get(str(family).lower())
        if twin is not None:
            match = original(family=twin, style=style, weight=weight,
                             width=width, italic=italic)
            if match is not None and match.family.lower() == twin.lower():
                # answer with the asked font's own entry, so it is scaled
                asked = _ASKED_BY_TWIN.get(match.filename.lower())
                if asked and _fonts.font_manager.has_font(asked):
                    return _fonts.font_manager.get_font_face(asked)
                return match
        return found

    find_best_match._ingecad_patch = True
    find_best_match._ingecad_metric_fonts = True
    _fonts.find_best_match = find_best_match

    original_cache = _fonts.TrueTypeFont.create_cache

    def create_cache(self, ttf: str):
        cache = original_cache(self, ttf)
        name = str(ttf).lower()
        factor = METRIC_COMPATIBLE_SCALE.get(name)
        if factor and not getattr(cache, "_ingecad_scaled", False) \
                and is_twin_standing_in(_fonts.font_manager, name):
            plain = cache.get_scaling_factor
            cache.get_scaling_factor = lambda cap_height: plain(cap_height) * factor
            cache._ingecad_scaled = True
        return cache

    _fonts.TrueTypeFont.create_cache = create_cache

    # The glyphs of a twin standing in are scaled by METRIC_COMPATIBLE_SCALE
    # (Arial's widths), so its capitals stand that much lower than the text
    # height; text_size kept reporting the full height. Anything placing
    # text by its measured box -- MIRROR's readable text, a justification
    # change -- then put it 0.1-0.2 units off on a Linux without Arial (the
    # release CI; most users). The cap height follows the glyphs now.
    from ezdxf.tools import text_size as _text_size

    original_size = _text_size.text_size
    if not getattr(original_size, "_ingecad_patch", False):
        def text_size(text):
            size = original_size(text)
            factor = _twin_factor(text)
            if factor == 1.0:
                return size
            # total_height comes from the font's measurements, already
            # scaled; cap_height is the text's height, by definition
            return _text_size.TextSize(size.width, size.cap_height * factor,
                                       size.total_height)

        text_size._ingecad_patch = True
        _text_size.text_size = text_size


def _twin_factor(text) -> float:
    """METRIC_COMPATIBLE_SCALE of a TEXT's font when its twin stands in."""
    from ezdxf.fonts import fonts as _fonts

    try:
        doc = text.doc
        style = doc.styles.get(text.dxf.get("style", "Standard"))
        name = str(style.dxf.get("font", "") or "").lower()
    except Exception:  # noqa: BLE001 -- no style: nothing to scale
        return 1.0
    factor = METRIC_COMPATIBLE_SCALE.get(name)
    if factor and is_twin_standing_in(_fonts.font_manager, name):
        return factor
    return 1.0


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
    """DIMRADIUS / DIMDIAMETER drawn by the drafting norm (#67).

    The rule Rafael teaches from ISO 129 / UNE, and Marco chose over
    AutoCAD's ISO-25 rendering (2026-10-09):

    * the text does not fit inside: text outside, the arrowheads OUTSIDE
      with their tips on the circle pointing to the centre, the dimension
      line still through the centre and extended to carry the text; on a
      diameter the far arrowhead too, with the line running a short way
      past it (one arrowhead length past its tail: 5 mm with ISO-25) -- a
      line cut at the arrow "as with a knife" reads wrong;
    * the text fits inside: arrowheads inside, the text on the dimension
      line, no extension of any kind; a diameter spans the whole circle.

    ezdxf 1.4 draws the outside case with the arrowheads inside (or one in,
    one out), and a diameter with its text placed inside as a single leader
    from the text to the circle -- half a diameter.

    DIMTOFL off (the imperial Standard style) keeps ezdxf's own paths.
    DIMTMOVE 2 (text moved freely, no leader) keeps ezdxf's across-the-
    circle layout without the extension, as the variable says; ezdxf reads
    an unset DIMTMOVE as 2 where AutoCAD's default is 0, so the value is
    read here with AutoCAD's default.
    """
    from ezdxf.render.dim_diameter import DiameterDimension
    from ezdxf.render.dim_radius import RadiusDimension

    if getattr(RadiusDimension.render_user_location, "_ingecad_patch", False):
        return

    def iso_case(self) -> bool:
        m = self.measurement
        return (bool(m.text_is_outside) and bool(self.outside_text_force_dimline)
                and self.dim_style.get("dimtmove", 0) != 2)

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
        if self.arrows.suppress1:
            base = self.point_on_circle
        else:
            base = self.add_arrow(self.point_on_circle, rotate=True)  # outside, to the centre
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
        """ezdxf's own: past the outside arrowhead, now always where it is."""
        return original(self)

    def get_default_text_location_radius(self):
        return default_text_location(self, radius_text)

    # -- diameter ---------------------------------------------------------------
    diameter_user = DiameterDimension.render_user_location
    diameter_default = DiameterDimension.render_default_location
    diameter_text = DiameterDimension.get_default_text_location

    def diameter_iso(self, user: bool) -> None:
        # both arrowheads outside, tips on the circle pointing to the centre
        near = self._add_arrow_1(rotate=True)
        far = self._add_arrow_2(rotate=False)
        self.add_diameter_dim_line(self.point_on_circle, self.point_on_circle2)
        ext_line(self, near, user)
        # the far side runs on past its arrowhead
        outward = (self.point_on_circle2 - self.center).normalize()
        self.add_line(far, far + outward * self.arrows.arrow_size,
                      dxfattribs=self.dimension_line.dxfattribs())

    def diameter_across_with_text_inside(self) -> bool:
        """Text placed inside the circle, on the dimension line: ezdxf takes
        it for text moved off the line and draws a single leader from the
        text to the circle -- one arrowhead, no diameter (#67). AutoCAD and
        the norm draw the whole diameter, both arrowheads, the text on it."""
        m = self.measurement
        return (not m.text_is_outside and not m.text_inside_horizontal
                and self.dim_style.get("dimtmove", 0) != 2)

    def render_user_location_diameter(self) -> None:
        if iso_case(self):
            diameter_iso(self, user=True)
        elif diameter_across_with_text_inside(self):
            near = self._add_arrow_1(rotate=False)
            far = self._add_arrow_2(rotate=True)
            self.add_diameter_dim_line(near, far)
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


def _patch_linear_dimension_direction() -> None:
    """DIMLINEAR / DIMALIGNED picked right-to-left must draw the same.

    AutoCAD draws a linear dimension's text readable from the bottom or the
    right of the sheet (ISO 129-1; DIMTIH/DIMTOH 0), above the dimension
    line in that reading direction, and the pick order of the two origins
    changes nothing about it. ezdxf's LinearDimension takes the direction
    from defpoint2 -> defpoint3 and the text rotation from the raw angle,
    so origins picked against the reading direction render mirrored: the
    text under the line (upside down for an aligned one), the dimension
    line overshooting the extension lines, the arrowheads outside pointing
    in. A tester who dimensioned a rectangle from its right corner to its
    left one got exactly that ("la cota debajo y las flechas por fuera"),
    and nobody looks at which corner they click first.

    The renderer reads the angle and the two origins once, in its
    constructor, so they are handed to it normalised -- the angle folded
    into (-90, 90], the origins in that direction's order -- and restored
    on the entity afterwards: the DIMENSION keeps the user's order and
    angle (DIMCONTINUE and DIMBASELINE chain from them), only the *D block
    is drawn the way AutoCAD draws it.
    """
    from ezdxf.render.dim_linear import LinearDimension

    if getattr(LinearDimension.__init__, "_ingecad_patch", False):
        return
    original = LinearDimension.__init__

    def __init__(self, dimension, ucs=None, override=None):
        dxf = dimension.dxf
        raw_angle = float(dxf.get("angle", 0.0))
        angle = _square(reading_angle(aligned_angle(dimension, raw_angle)))
        p1 = _Vec2(dxf.get("defpoint2", (0, 0)))
        p2 = _Vec2(dxf.get("defpoint3", (0, 0)))
        against = (p2 - p1).dot(_Vec2.from_deg_angle(angle)) < 0.0
        folded = abs(angle - raw_angle) > 1e-9
        if against:
            dxf.defpoint2, dxf.defpoint3 = dxf.defpoint3, dxf.defpoint2
        if folded:
            dxf.angle = angle
        try:
            original(self, dimension, ucs, override)
        finally:
            if against:
                dxf.defpoint2, dxf.defpoint3 = dxf.defpoint3, dxf.defpoint2
            if folded:
                dxf.angle = raw_angle

    __init__._ingecad_patch = True
    LinearDimension.__init__ = __init__

    from ezdxf.entities import dimension as dimension_module
    from ezdxf.lldxf import const

    tools = dimension_module.MEASUREMENT_TOOLS
    measure = tools[const.DIM_ALIGNED]
    if not getattr(measure, "_ingecad_patch", False):
        def measure_aligned(dim):
            raw = float(dim.dxf.get("angle", 0.0))
            angle = _square(aligned_angle(dim, raw))
            if abs(angle - raw) < 1e-12:
                return measure(dim)
            dim.dxf.angle = angle
            try:
                return measure(dim)
            finally:
                dim.dxf.angle = raw

        measure_aligned._ingecad_patch = True
        tools[const.DIM_ALIGNED] = measure_aligned


def aligned_angle(dimension, angle: float) -> float:
    """The direction a linear dimension is measured along, in degrees.

    An ALIGNED dimension runs along its two origins whatever its group 50
    says: AutoCAD writes 0 there (464 of 803 aligned dimensions of a corpus
    sample), and ezdxf, which measures and draws along that angle, turned a
    vertical 2.54 into "0" on the first grip edit. A rotated dimension keeps
    its ``angle``.
    """
    dxf = dimension.dxf
    if int(dxf.get("dimtype", 0)) & 7 != 1:
        return angle
    p1 = _Vec2(dxf.get("defpoint2", (0, 0)))
    p2 = _Vec2(dxf.get("defpoint3", (0, 0)))
    if p1.isclose(p2):
        return angle
    return (p2 - p1).angle_deg


def _square(angle: float) -> float:
    """``angle`` snapped onto a multiple of 90 degrees when it is one but
    for float noise. ezdxf intersects the dimension's construction rays in
    slope/intercept form: at UTM coordinates a "vertical" 89.9999999958
    degrees (AutoCAD's origins differ by 1e-13 in x) put the intercept near
    1e16 and rounded the dimension line to whole units -- 1.60 drew as 2.00.
    A millionth of a degree is invisible at any plotted scale."""
    nearest = round(angle / 90.0) * 90.0
    return nearest if abs(angle - nearest) < 1e-6 else angle


def reading_angle(angle: float) -> float:
    """The direction a dimension line of ``angle`` degrees is READ along:
    the same line folded into (-90, 90], so its text reads from the bottom
    or from the right of the sheet (AutoCAD's rule for aligned text)."""
    a = angle % 360.0
    if 90.0 < a <= 270.0:
        a -= 180.0
    elif a > 270.0:
        a -= 360.0
    return a


def _patch_linetype_dots() -> None:
    """A linetype's dot reaches the backend as a zero-length line (#87).

    ezdxf stretches every element of a pattern to ``min_dash_length``, the
    dots of DASHDOT, CENTER and PHANTOM included, so each dot was drawn as
    a stroke shorter than a pixel: GL lit it or not depending on where it
    fell, and Rafael found the dots "muy difíciles de ver". (Leaving the
    dot at 0 does not do: ezdxf's C renderer drops zero-length dashes.)
    Here what the renderer leaves at that length or shorter collapses to
    its midpoint, a zero-length line, which the screen backend draws as a
    pixel or a square of the pen's width and the plot as a pen-wide dot.
    """
    from ezdxf.addons.drawing.pipeline import LinetypeStage2d
    from ezdxf.math import Vec2
    from ezdxf.render import linetypes

    if getattr(LinetypeStage2d.draw_line, "_ingecad_patch", False):
        return

    def dotted(stage, properties, lines):
        pattern = properties.linetype_pattern
        if not any(v == 0.0 for v in pattern[0::2]):
            return lines
        limit = stage.config.min_dash_length * stage.get_ltype_scale() * (1 + 1e-9)
        out = []
        for s, e in lines:
            if (e - s).magnitude <= limit:
                m = s.lerp(e)
                out.append((m, m))
            else:
                out.append((s, e))
        return out

    original_line = LinetypeStage2d.draw_line
    original_path = LinetypeStage2d.draw_path

    def draw_line(self, start, end, properties):
        if self.solid_lines_only or len(properties.linetype_pattern) < 2:
            return original_line(self, start, end, properties)
        renderer = linetypes.LineTypeRenderer(self.pattern(properties))
        s, e = Vec2(start), Vec2(end)
        self.next_stage.draw_solid_lines(
            dotted(self, properties, list(renderer.line_segment(s, e))),
            properties)

    def draw_path(self, path, properties):
        if self.solid_lines_only or len(properties.linetype_pattern) < 2:
            return original_path(self, path, properties)
        renderer = linetypes.LineTypeRenderer(self.pattern(properties))
        vertices = path.flattening(self.config.max_flattening_distance, segments=16)
        self.next_stage.draw_solid_lines(
            dotted(self, properties,
                   [(Vec2(s), Vec2(e)) for s, e in renderer.line_segments(vertices)]),
            properties)

    draw_line._ingecad_patch = True
    LinetypeStage2d.draw_line = draw_line
    LinetypeStage2d.draw_path = draw_path
