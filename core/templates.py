# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Drawing templates — what "New drawing" actually means.

A template answers the question AutoCAD asks with its .dwt files and
BricsCAD asks on startup: *in what unit am I drawing?* Everything else
follows from that answer, and getting it wrong is expensive later — a plan
started in millimetres and dimensioned as if it were metres is a plan whose
text is a thousand times too small, discovered at plot time.

So a template sets the unit ($INSUNITS, $MEASUREMENT), how lengths read
($LUNITS/$LUPREC — see ``core.units``), and it sizes annotation so that
**text lands at 2.5 mm on paper at the template's plot scale**, which is
what ISO 128 asks for. Two knobs do that:

* the dimension styles' lengths are converted from millimetres into the
  drawing's unit, so ISO-25's 2.5 mm text is 2.5 in a mm drawing, 0.25 in a
  cm drawing and 0.0025 in a metres drawing;
* $DIMSCALE and $LTSCALE carry the plot scale, so that 0.0025 m of text
  plots as 2.5 mm at 1:100.

The plot scale is a starting point, not a cage: DIMSCALE, LTSCALE and the
seeded ``Acot-N`` styles are all reachable from the command line.
"""
from __future__ import annotations

from dataclasses import dataclass

from core import units as units_mod

# Text height on paper that every template aims for (ISO 128).
PAPER_TEXT_MM = 2.5


@dataclass(frozen=True)
class Template:
    """One entry of the New Drawing list."""

    key: str
    name: str
    description: str
    unit_in_mm: float       # how many millimetres one drawing unit is
    insunits: int           # $INSUNITS
    lunits: int             # $LUNITS
    luprec: int             # $LUPREC
    plot_scale: float       # the 1:N the annotation is sized for
    measurement: int = 1    # $MEASUREMENT: 1 metric, 0 imperial

    @property
    def units_per_mm(self) -> float:
        """Drawing units in one millimetre — the annotation conversion."""
        return 1.0 / self.unit_in_mm


BUILTIN_TEMPLATES: tuple[Template, ...] = (
    Template(
        key="mm",
        name="Metric — millimetres",
        description="Details and fabrication drawings, plotted 1:1.",
        unit_in_mm=1.0,
        insunits=4,
        lunits=units_mod.DECIMAL,
        luprec=2,
        plot_scale=1.0,
    ),
    Template(
        key="cm",
        name="Metric — centimetres",
        description="Sections and details, plotted 1:10.",
        unit_in_mm=10.0,
        insunits=5,
        lunits=units_mod.DECIMAL,
        luprec=2,
        plot_scale=10.0,
    ),
    Template(
        key="m",
        name="Metric — metres",
        description="Site and floor plans, plotted 1:100. The civil default.",
        unit_in_mm=1000.0,
        insunits=6,
        lunits=units_mod.DECIMAL,
        luprec=3,
        plot_scale=100.0,
    ),
    Template(
        key="in",
        name="Imperial — inches",
        description="Architectural feet and inches, plotted 1/4\" = 1'-0\".",
        unit_in_mm=25.4,
        insunits=1,
        lunits=units_mod.ARCHITECTURAL,
        luprec=4,          # sixteenths
        plot_scale=48.0,   # 1/4" = 1'-0"
        measurement=0,
    ),
)

DEFAULT_TEMPLATE = "m"


def by_key(key: str) -> Template:
    for template in BUILTIN_TEMPLATES:
        if template.key == key:
            return template
    return by_key(DEFAULT_TEMPLATE) if key != DEFAULT_TEMPLATE \
        else BUILTIN_TEMPLATES[0]


def apply_to(document, template: Template) -> None:
    """Stamp a template onto a document (header + styles). Idempotent."""
    from core import styles as styles_mod

    doc = document.doc
    units_mod.Units(
        lunits=template.lunits,
        luprec=template.luprec,
        aunits=units_mod.DEG,
        auprec=2,
        insunits=template.insunits,
    ).to_doc(doc)
    doc.header["$MEASUREMENT"] = int(template.measurement)
    # Annotation: sizes converted into the drawing's unit, scale on top.
    doc.header["$DIMSCALE"] = float(template.plot_scale)
    doc.header["$LTSCALE"] = float(template.units_per_mm * template.plot_scale)
    styles_mod.install_default_styles(
        document, unit_factor=template.units_per_mm, overwrite=True)
    # The CURRENT dimension style must carry the plot scale: the renderer
    # reads dimscale from the STYLE, not from the $DIMSCALE header, so a
    # metres drawing dimensioned with plain ISO-25 (dimscale 1) drew its
    # 0.0025-unit text at face value — invisible on a 20 m dimension.
    scale = float(template.plot_scale)
    if scale != 1.0:
        name = f"Acot-{int(scale) if scale.is_integer() else scale}"
        if name not in doc.dimstyles:
            attribs = dict(styles_mod.iso25_for(template.units_per_mm))
            attribs["dimscale"] = scale
            doc.dimstyles.new(name, dxfattribs=attribs)
        doc.header["$DIMSTYLE"] = name


def new_document(key: str = DEFAULT_TEMPLATE):
    """A fresh Document built on a template."""
    from core.document import Document

    template = by_key(key)
    document = Document.new()
    apply_to(document, template)
    document.dirty = False
    return document


def paper_text_height(template: Template) -> float:
    """Drawing units a 2.5 mm paper text occupies at the template's scale."""
    return PAPER_TEXT_MM * template.units_per_mm * template.plot_scale
