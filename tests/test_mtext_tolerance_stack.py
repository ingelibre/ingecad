# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A tolerance stack ``\\S+a^-b;`` reads +a over -b, not "+ak b".

ezdxf decoded every ``^x`` as a control character, so ``^-`` became "k"
(a tester's eighth review, UNE-EN ISO 129-1). Caret notation is ``^@`` to
``^_``; inside a stack ``^`` divides the two lines.
"""
from __future__ import annotations

import ezdxf
from ezdxf.tools.text import MTextParser, caret_decode

from core import ezdxf_patches

ezdxf_patches.apply()


def _stack(content):
    return [t.data for t in MTextParser(content) if t.type.name == "STACK"]


def test_the_tolerance_stack_splits_at_the_caret():
    assert _stack(r"25\S+0,1^-0,2;") == [("+0,1", "-0,2", "^")]


def test_what_ezdxf_writes_still_reads():
    assert _stack(r"\SA^ B;") == [("A", "B", "^")]
    assert _stack(r"\S1/2;") == [("1", "2", "/")]


def test_control_characters_still_decode():
    assert caret_decode("a^Jb^Ic") == "a\nb\tc"


def test_the_drawn_dimension_text_has_no_k():
    from ezdxf.addons.drawing import Frontend, RenderContext
    from ezdxf.addons.drawing.recorder import Recorder

    doc = ezdxf.new("R2010", setup=True)
    msp = doc.modelspace()
    msp.add_mtext(r"25\S+0,1^-0,2;", dxfattribs={"char_height": 2.5})
    recorder = Recorder()
    Frontend(RenderContext(doc), recorder).draw_layout(msp)
    texts = [r.text for r in recorder.player().records
             if hasattr(r, "text") and isinstance(getattr(r, "text"), str)]
    plain = msp.query("MTEXT")[0].plain_text()
    assert "k" not in plain and "k" not in "".join(texts)
