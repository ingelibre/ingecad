# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Leaders, headless: LEADER (+ its MTEXT annotation) and MULTILEADER.

Reference: ``docs/reference/dim/autocad-leaders.md`` (LEADER p. 1032,
MLEADER p. 1174, QLEADER p. 1576 of the AutoCAD Command Reference).

A LEADER's text is a separate MTEXT the leader points to (group 340), placed
past a horizontal *hook line* one arrow-size long when the last segment is
not horizontal, at DIMGAP from the hook, vertically centred (the reference,
"Mtext"). Both entities come out of ONE command, so undo removes both.

A MULTILEADER is one entity; ezdxf's ``MultiLeaderMTextBuilder`` lays out
the dogleg (landing) and the text from the MLEADERSTYLE.
"""
from __future__ import annotations

from core.actions import AddEntityCommand, dress_new_entity

#: acad metric defaults, used when neither the style nor the header says
DEFAULTS = {"dimasz": 2.5, "dimtxt": 2.5, "dimgap": 0.625, "dimscale": 1.0}


def dimstyle_name(doc) -> str:
    """The current dimension style ($DIMSTYLE), Standard when unknown."""
    name = doc.header.get("$DIMSTYLE", "Standard")
    return name if name in doc.dimstyles else "Standard"


def dimstyle_values(doc) -> tuple[float, float, float]:
    """(arrow size, text height, text gap) in drawing units, DIMSCALE applied."""
    style = doc.dimstyles.get(dimstyle_name(doc))

    def value(attr: str) -> float:
        v = None
        if style is not None:
            try:
                v = style.dxf.get(attr, None)
            except Exception:                 # noqa: BLE001 - an odd style
                v = None
        if v is None or v <= 0:
            v = doc.header.get("$" + attr.upper(), None)
        if v is None or v <= 0:
            v = DEFAULTS[attr]
        return float(v)

    scale = value("dimscale") or 1.0
    from core.styles import dim_text_height

    def get(key, default=None):
        if key == "dimtxt":
            return value("dimtxt")
        return style.dxf.get(key, default) if style is not None else default

    height = dim_text_height(doc, get)
    return value("dimasz") * scale, height * scale, value("dimgap") * scale


def text_style_name(doc) -> str:
    name = doc.header.get("$TEXTSTYLE", "Standard")
    return name if name in doc.styles else "Standard"


def leader_text_layout(points, arrow_size: float, gap: float):
    """Where a LEADER's annotation goes.

    Returns ``(hook_end | None, text_insert, attachment, to_right)``: the
    hook line's end when one is needed (the last segment is not horizontal),
    the MTEXT insert point at DIMGAP past it, and its attachment (middle
    left when the text sits to the right of the leader, middle right
    otherwise) -- the reference's "vertically centered and horizontally
    aligned according to the X axis direction of the last two vertices".
    """
    last, prev = points[-1], points[-2]
    to_right = last[0] >= prev[0]
    horizontal = abs(last[1] - prev[1]) < 1e-9
    sign = 1.0 if to_right else -1.0
    hook = None if horizontal else (last[0] + sign * arrow_size, last[1])
    end = hook or last
    insert = (end[0] + sign * gap, end[1])
    return hook, insert, (4 if to_right else 6), to_right


class AddLeaderCommand(AddEntityCommand):
    """A LEADER and the MTEXT it annotates, created and undone together.

    ``entity`` is the leader (what every additive path already knows how
    to show); ``extra_entities`` carries the text, so the overlay and the
    caches learn about both without a regen.
    """

    def __init__(self, name: str, factory) -> None:
        super().__init__(name, factory)
        self.extra_entities: list = []

    def do(self, document) -> None:
        leader, extras = self._factory(self.space(document))
        self.entity, self.extra_entities = leader, list(extras)
        for entity in [leader, *self.extra_entities]:
            dress_new_entity(document, entity)
        document.dirty = True

    def undo(self, document) -> None:
        space = self.space(document)
        handles = []
        for entity in [self.entity, *self.extra_entities]:
            if entity is not None and entity.is_alive:
                handles.append(entity.dxf.handle)
                space.delete_entity(entity)
        self.removed_handles = handles
        self.entity, self.extra_entities = None, []
        document.dirty = True


def add_leader(points, text_lines=None, *, arrow: bool = True,
               spline: bool = False, text_width: float = 0.0) -> AddLeaderCommand:
    """LEADER through ``points`` (2+), optionally annotated with MTEXT lines.

    ``text_width`` 0 leaves the text unlimited (QLEADER's "Specify text
    width <0>").
    """
    points = [(float(p[0]), float(p[1])) for p in points]
    if len(points) < 2:
        raise ValueError("a leader needs two points")
    lines = list(text_lines or [])

    def make(space):
        doc = space.doc
        arrow_size, text_height, gap = dimstyle_values(doc)
        vertices = list(points)
        mtext = None
        has_hook, to_right = False, True
        if lines:
            hook, insert, attachment, to_right = leader_text_layout(
                points, arrow_size, gap)
            if hook is not None:
                vertices.append(hook)
                has_hook = True
            mtext = space.add_mtext("\\P".join(lines), dxfattribs={
                "char_height": text_height,
                "width": float(text_width or 0.0),
                "style": text_style_name(doc)})
            mtext.set_location(insert, attachment_point=attachment)
        attribs = {
            "path_type": 1 if spline else 0,
            "has_arrowhead": 1 if arrow else 0,
            "has_hookline": 1 if has_hook else 0,
            "hookline_direction": 1 if (has_hook and to_right) else 0,
            "annotation_type": 0 if mtext is not None else 3,
            "text_height": text_height,
            "text_width": float(text_width or 0.0),
        }
        leader = space.add_leader(vertices, dimstyle=dimstyle_name(doc),
                                  dxfattribs=attribs)
        if mtext is not None:
            leader.dxf.annotation_handle = mtext.dxf.handle
        return leader, ([mtext] if mtext is not None else [])

    return AddLeaderCommand("LEADER", make)


def mleader_style_name(doc, wanted: str | None = None) -> str:
    """The MLEADERSTYLE to use: ``wanted`` if it exists, else the current
    one ($CMLEADERSTYLE), else Standard."""
    try:
        styles = doc.mleader_styles
    except Exception:                          # noqa: BLE001 - no table
        return "Standard"
    for name in (wanted, doc.header.get("$CMLEADERSTYLE", None), "Standard"):
        if name and name in styles:
            return name
    for style in styles:
        return style.dxf.name
    return "Standard"


def mleader_text_height(doc, style: str | None = None) -> float:
    """The text height an MLEADER of ``style`` will get."""
    try:
        mstyle = doc.mleader_styles.get(mleader_style_name(doc, style))
    except Exception:  # noqa: BLE001 -- no style: ezdxf's default
        mstyle = None
    if mstyle is None:
        return 4.0
    scale = float(mstyle.dxf.get("scale", 1.0) or 1.0)
    return float(mstyle.dxf.get("char_height", 4.0) or 4.0) * scale


def add_mleader(leader_points, landing, text: str = "", *,
                leader_type: str = "S", landing_on: bool = True,
                content: str = "M", block_name: str | None = None,
                style: str | None = None) -> AddEntityCommand:
    """MULTILEADER: leader line through ``leader_points`` (arrowhead first),
    dogleg starting at ``landing``, then the content.

    ``leader_type``: S straight, P spline, N none. ``content``: M mtext,
    B block (``block_name``), N none. The MLEADERSTYLE gives the text
    height, arrow size, dogleg length and landing gap.
    """
    pts = [(float(p[0]), float(p[1])) for p in leader_points]
    landing = (float(landing[0]), float(landing[1]))

    def make(space):
        from ezdxf.math import Vec2
        from ezdxf.render import mleader as ml

        doc = space.doc
        name = mleader_style_name(doc, style)
        mstyle = None
        try:
            mstyle = doc.mleader_styles.get(name)
        except Exception:                      # noqa: BLE001
            mstyle = None
        scale = float(getattr(mstyle.dxf, "scale", 1.0) or 1.0) if mstyle else 1.0
        dogleg = (float(getattr(mstyle.dxf, "dogleg_length", 8.0) or 8.0) * scale
                  if mstyle else 8.0)
        # landing_gap_size: "landing_gap" is no MLEADERSTYLE attribute, so
        # the gap was always 2.0 -- two metres in a drawing in metres
        gap = (float(mstyle.dxf.get("landing_gap_size", 2.0) or 2.0) * scale
               if mstyle else 2.0)
        if content == "B" and block_name:
            builder = space.add_multileader_block(style=name)
            builder.set_content(name=block_name)
        else:
            builder = space.add_multileader_mtext(style=name)
            builder.set_content(text if content == "M" else "",
                                style=text_style_name(doc))
        kind = {"S": ml.LeaderType.straight_lines, "P": ml.LeaderType.splines,
                "N": ml.LeaderType.none}.get(leader_type,
                                              ml.LeaderType.straight_lines)
        builder.set_leader_properties(leader_type=kind)
        if not landing_on:
            dogleg, gap = 0.0, 0.0
            builder.set_connection_properties(landing_gap=0.0, dogleg_length=0.0)
        side = (ml.ConnectionSide.left if pts[0][0] <= landing[0]
                else ml.ConnectionSide.right)
        builder.add_leader_line(side, [Vec2(p) for p in pts])
        shift = (dogleg + gap) if side == ml.ConnectionSide.left else -(dogleg + gap)
        builder.build(insert=Vec2(landing[0] + shift, landing[1]))
        entity = builder.multileader
        if content == "N" or (content == "M" and not text):
            # "None Specifies no content type": no text block at all -- the
            # builder always lays one out, empty
            entity.context.mtext = None
            entity.dxf.content_type = 2
        return entity

    return AddEntityCommand("MLEADER", make)
