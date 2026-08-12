# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""MTEXT inline formatting <-> editable runs, losslessly or not at all.

The in-place editor shows rich text (bold, colour, size…) only when the
MTEXT content can be REBUILT exactly from what the editor understands.
``parse_runs`` returns the paragraphs-of-runs representation, or None when
the content carries anything we cannot re-serialize — stacked fractions,
fields, alignment/oblique/tracking codes, paragraph properties. The editor
then falls back to raw-code mode, which is what keeps a colleague's
formatted note intact: rich mode is offered when it is safe, never guessed.

Safety is by construction, not by review: ``parse_runs`` re-serializes its
own answer and re-parses it, and returns None unless the two run lists are
identical. A gap between parser and serializer degrades to raw mode instead
of corrupting a drawing.

Heights are RELATIVE factors against the entity's char_height, so an
absolute ``\\H5;`` in a 2.5-high text round-trips as ``\\H2x;`` — different
bytes, same text on screen, which is the equality that matters here.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Optional

from ezdxf.tools.text import (MTextContext, MTextParser,
                              ParagraphProperties, TokenType)

# The default font family the parser reports when no \f code is active.
_DEFAULT_FAMILY = MTextContext().font_face.family


@dataclass
class Run:
    """One stretch of text with uniform character formatting."""

    text: str = ""
    bold: bool = False
    italic: bool = False
    underline: bool = False
    overline: bool = False
    strike: bool = False
    aci: Optional[int] = None          # None: no colour code (ByLayer look)
    rgb: Optional[tuple] = None        # true colour wins over aci when set
    height: float = 1.0                # factor of the entity's char_height
    font: Optional[str] = None         # None: the text style's own font

    def same_format(self, other: "Run") -> bool:
        return (self.bold, self.italic, self.underline, self.overline,
                self.strike, self.aci, self.rgb, round(self.height, 6),
                self.font) == \
               (other.bold, other.italic, other.underline, other.overline,
                other.strike, other.aci, other.rgb, round(other.height, 6),
                other.font)


DEFAULT_PROPS = ParagraphProperties()


@dataclass
class Paragraph:
    """One paragraph: its runs plus AutoCAD's paragraph properties.

    Indents and tab stops are MULTIPLES OF char_height (the ezdxf/DXF
    convention): left=2 in a 2.5-high text is 5 drawing units. ``indent``
    is the first line, relative to ``left`` — the same relationship Qt's
    textIndent has to the left margin, which is what makes the ruler
    mapping direct.
    """

    runs: list[Run] = field(default_factory=list)
    props: Optional[ParagraphProperties] = None    # None: inherit/default

    def resolved(self) -> ParagraphProperties:
        return self.props if self.props is not None else DEFAULT_PROPS


Paragraphs = list[Paragraph]


def _run_from_ctx(ctx, char_height: float) -> Run:
    face = ctx.font_face
    family = face.family if face.family != _DEFAULT_FAMILY else None
    return Run(
        bold=(face.weight or 400) >= 600,
        italic=(face.style or "").lower().startswith(("italic", "oblique")),
        underline=bool(ctx.underline),
        overline=bool(ctx.overline),
        strike=bool(ctx.strike_through),
        aci=None if ctx.aci == 7 and ctx.rgb is None else
            (None if ctx.rgb is not None else int(ctx.aci)),
        rgb=tuple(ctx.rgb) if ctx.rgb is not None else None,
        height=(ctx.cap_height / char_height) if char_height > 0 else 1.0,
        font=family,
    )


def _representable(ctx) -> bool:
    if int(ctx.align) != 0:                      # \A
        return False
    if abs(ctx.oblique) > 1e-9:                  # \Q
        return False
    if abs(ctx.width_factor - 1.0) > 1e-9:       # \W
        return False
    if abs(ctx.char_tracking_factor - 1.0) > 1e-9:   # \T
        return False
    return True


def _tokens_to_paragraphs(content: str, char_height: float):
    # Seed the parser with the entity's height so unformatted text comes out
    # at factor 1.0 and absolute \H codes resolve against the real height.
    base = MTextContext()
    base.cap_height = char_height if char_height > 0 else 1.0
    paragraphs: Paragraphs = [Paragraph()]
    for token in MTextParser(content, base):
        kind = token.type
        if kind in (TokenType.STACK, TokenType.NEW_COLUMN,
                    TokenType.WRAP_AT_DIMLINE):
            return None
        if not _representable(token.ctx):
            return None
        if kind == TokenType.NEW_PARAGRAPH:
            paragraphs.append(Paragraph())
            continue
        piece = {TokenType.WORD: token.data,
                 TokenType.SPACE: " ",
                 TokenType.NBSP: "\u00a0",
                 TokenType.TABULATOR: "\t"}.get(kind)
        if piece is None:
            continue
        paragraph = paragraphs[-1]
        if paragraph.props is None:
            # The first content token fixes the paragraph's properties.
            paragraph.props = token.ctx.paragraph
        elif token.ctx.paragraph != paragraph.props:
            # A property change MID paragraph has no home in this model.
            return None
        run = _run_from_ctx(token.ctx, char_height)
        line = paragraph.runs
        if line and line[-1].same_format(run):
            line[-1].text += piece
        else:
            run.text = piece
            line.append(run)
    # Empty paragraphs inherit backwards, like the codes themselves do.
    previous = DEFAULT_PROPS
    for paragraph in paragraphs:
        if paragraph.props is None:
            paragraph.props = previous
        previous = paragraph.props
    return paragraphs


def _normalize(paragraphs: Paragraphs) -> list:
    """A comparable snapshot: merged runs, empty runs dropped."""
    out = []
    for paragraph in paragraphs:
        merged = []
        for run in paragraph.runs:
            if not run.text:
                continue
            if merged and merged[-1].same_format(run):
                merged[-1] = replace(merged[-1],
                                     text=merged[-1].text + run.text)
            else:
                merged.append(replace(run))
        out.append((paragraph.resolved(),
                    [(r.text, r.bold, r.italic, r.underline, r.overline,
                      r.strike, r.aci, r.rgb, round(r.height, 4), r.font)
                     for r in merged]))
    return out


def parse_runs(content: str, char_height: float) -> Optional[Paragraphs]:
    """Paragraphs of runs, or None when rich editing would be lossy."""
    if "%<" in content:
        # Fields: the parser splits them into words and eats their codes, so
        # they cannot even be detected reliably after parsing. Bail first.
        return None
    try:
        paragraphs = _tokens_to_paragraphs(content, char_height)
    except Exception:
        return None
    if paragraphs is None:
        return None
    # The safety gate: our own serialization must parse back identically.
    try:
        again = _tokens_to_paragraphs(serialize(paragraphs), char_height)
    except Exception:
        return None
    if again is None or _normalize(again) != _normalize(paragraphs):
        return None
    return paragraphs


def _escape(text: str) -> str:
    escaped = (text.replace("\\", "\\\\").replace("{", "\\{")
               .replace("}", "\\}").replace("\u00a0", "\\~"))
    # Pasted line/paragraph separators become real MTEXT paragraphs — a raw
    # newline character inside the stream is not a thing MTEXT has.
    for separator in ("\r\n", "\n", "\u2028", "\u2029"):
        escaped = escaped.replace(separator, "\\P")
    return escaped


def _height_code(factor: float) -> str:
    return f"\\H{round(factor, 6):g}x;"


def _props_code(props) -> str:
    """A \\px code that FULLY specifies the paragraph state.

    ParagraphProperties.tostring() omits components at their default value —
    but the codes persist across paragraphs, so an omitted ``i0`` means
    "keep the -2 from the last paragraph", not zero. Every component is
    spelled out here, and a bare ``t`` clears the tab list (verified against
    the parser). Alignment is emitted only when set; a paragraph that
    RETURNS to default alignment after a non-default one has no reset code
    we know, and the safety gate sends that case to raw mode.
    """
    def number(value: float) -> str:
        return f"{round(float(value), 6):g}"

    parts = [f"i{number(props.indent)}", f"l{number(props.left)}",
             f"r{number(props.right)}"]
    if int(props.align):
        parts.append("q" + "lrcjd"[int(props.align) - 1])
    tabs = ",".join(
        (str(t)[0] + number(float(str(t)[1:]))) if str(t)[0] in "cr"
        else number(float(t))
        for t in props.tab_stops)
    parts.append("t" + tabs if tabs else "t")
    return "\\px" + ",".join(parts) + ";"


def serialize(paragraphs: Paragraphs) -> str:
    """Runs -> MTEXT stream. Formatting is brace-scoped so it self-restores.

    Paragraph properties are NOT brace-scoped in MTEXT: a ``\\px`` code holds
    until the next one, so a paragraph that returns to defaults after a
    formatted one needs an explicit reset.
    """
    parts = []
    previous_props = DEFAULT_PROPS
    for paragraph in paragraphs:
        line_parts = []
        props = paragraph.resolved()
        if props != previous_props:
            line_parts.append(_props_code(props))
        previous_props = props
        for run in paragraph.runs:
            if not run.text:
                continue
            codes = []
            if run.font or run.bold or run.italic:
                family = run.font or "Arial"
                codes.append(f"\\f{family}|b{int(run.bold)}|i{int(run.italic)};")
            if run.rgb is not None:
                r, g, b = run.rgb
                codes.append(f"\\c{(b << 16) | (g << 8) | r};")
            elif run.aci is not None:
                codes.append(f"\\C{int(run.aci)};")
            if abs(run.height - 1.0) > 1e-9:
                codes.append(_height_code(run.height))
            if run.underline:
                codes.append("\\L")
            if run.overline:
                codes.append("\\O")
            if run.strike:
                codes.append("\\K")
            body = _escape(run.text)
            if codes:
                line_parts.append("{" + "".join(codes) + body + "}")
            else:
                line_parts.append(body)
        parts.append("".join(line_parts))
    return "\\P".join(parts)
