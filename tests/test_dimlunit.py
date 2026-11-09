# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A dimension's text follows its style's Unit format (DIMLUNIT, #122).

Architectural in the Dimension Style dialog changed nothing: ezdxf, which
draws the dimension text, reads DIMLUNIT and behaves as Decimal. The first
test is the one the issue's author sent.
"""
from __future__ import annotations

import ezdxf
import pytest

from core import ezdxf_patches

ezdxf_patches.apply()


def _text(dimlunit, dimdec, length=51.5):
    doc = ezdxf.new("R2010", setup=True)
    style = doc.dimstyles.get("EZDXF")
    style.dxf.dimlunit = dimlunit
    style.dxf.dimdec = dimdec
    style.dxf.dimzin = 0
    style.dxf.dimlfac = 1.0
    msp = doc.modelspace()
    dim = msp.add_linear_dim(base=(0, 5), p1=(0, 0), p2=(length, 0),
                             dimstyle="EZDXF")
    dim.render()
    return [e for e in doc.blocks.get(dim.dimension.dxf.geometry)
            if e.dxftype() == "MTEXT"][0].text


@pytest.mark.parametrize("lunit,dec,expected", [
    (2, 2, "51.50"),
    (4, 4, "4'-3 1/2\""),
    (5, 4, "51 1/2"),
    (3, 2, "4'-3.50\""),
    (1, 2, "5.15E+01"),
])
def test_dimension_text_follows_unit_format(lunit, dec, expected):
    assert _text(lunit, dec) == expected


@pytest.mark.parametrize("value,lunit,dec,zin,expected", [
    (48.0, 4, 4, 0, "4'"),               # zero inches dropped
    (48.0, 4, 4, 1, "4'-0\""),           # ...or kept
    (3.5, 4, 4, 0, "3 1/2\""),           # zero feet dropped
    (3.5, 4, 4, 1, "0'-3 1/2\""),
    (3.5, 4, 4, 3, "3 1/2\""),
    (23.97, 4, 4, 0, "2'"),              # 1/16 rounds up to whole feet
    (0.5, 5, 4, 0, "1/2"),
    (0.75, 5, 1, 0, "1"),                # 1/2 precision: 3/4 rounds up
    (-51.5, 4, 4, 0, "-4'-3 1/2\""),
    (143.999, 3, 2, 0, "12'"),
])
def test_feet_inches_fractions_and_zeros(value, lunit, dec, zin, expected):
    assert ezdxf_patches.length_unit_text(value, lunit, dec, zin) == expected


def test_decimal_is_left_to_the_decimal_path():
    assert ezdxf_patches.length_unit_text(51.5, 2, 2) is None


def test_a_dimension_drawn_in_the_app_follows_the_style(qapp, clean_settings):
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    win.new_document()
    doc = win.document.doc
    style = doc.dimstyles.get(doc.header.get("$DIMSTYLE", "Standard"))
    style.dxf.dimlunit = 4
    style.dxf.dimdec = 4
    style.dxf.dimzin = 0
    style.dxf.dimlfac = 1.0
    style.dxf.dimrnd = 0.0
    for text in ("DIMLINEAR", "0,0", "51.5,0", "20,10"):
        win._on_command_submitted(text)
    (dim,) = win.document.modelspace().query("DIMENSION")
    block = doc.blocks.get(dim.dxf.geometry)
    texts = [e.text for e in block if e.dxftype() == "MTEXT"]
    win.document.dirty = False
    win.close()
    assert texts and texts[0].endswith("4'-3 1/2\"")
