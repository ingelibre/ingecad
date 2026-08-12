# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The MTEXT run model: what is rich, what stays raw, and the safety gate."""
from __future__ import annotations

import pytest

from core.mtext_format import Paragraph, Run, parse_runs, serialize


def roundtrip(content: str, height: float = 2.5):
    runs = parse_runs(content, height)
    assert runs is not None, f"expected rich: {content!r}"
    return parse_runs(serialize(runs), height), runs


# -- the rich subset -----------------------------------------------------------

def test_plain_text_is_one_run_at_factor_one():
    paragraphs = parse_runs("hola mundo", 2.5)
    assert len(paragraphs) == 1
    assert paragraphs[0].runs == [Run(text="hola mundo")]


def test_paragraphs_split_on_backslash_p():
    paragraphs = parse_runs("linea 1\\Plinea 2", 2.5)
    assert [len(p.runs) for p in paragraphs] == [1, 1]
    assert paragraphs[1].runs[0].text == "linea 2"


def test_bold_font_colour_and_height_parse_into_runs():
    content = r"{\fArial|b1|i0;TITULO} {\C1;rojo} {\H0.5x;chico}"
    runs = parse_runs(content, 2.5)
    flat = runs[0].runs
    title = next(r for r in flat if r.text == "TITULO")
    assert title.bold and title.font == "Arial"
    rojo = next(r for r in flat if r.text == "rojo")
    assert rojo.aci == 1
    chico = next(r for r in flat if r.text == "chico")
    assert chico.height == pytest.approx(0.5)


def test_an_absolute_height_becomes_the_equivalent_factor():
    """\\H5; in a 2.5-high text is factor 2 — different bytes, same text."""
    runs = parse_runs(r"{\H5;grande} normal", 2.5)
    grande = runs[0].runs[0]
    assert grande.height == pytest.approx(2.0)
    again = parse_runs(serialize(runs), 2.5)
    assert again[0].runs[0].height == pytest.approx(2.0)


def test_escapes_round_trip():
    content = r"a\\b \{x\} y\~z"
    back, runs = roundtrip(content)
    assert runs[0].runs[0].text == "a\\b {x} y z"
    assert back is not None


def test_serialized_output_reparses_identically():
    content = r"\Lsub\l normal {\C3;verde \H2x;GRANDE}"
    back, runs = roundtrip(content)
    def snapshot(paragraphs):
        return [[(r.text, r.bold, r.underline, r.aci, round(r.height, 4))
                 for r in p.runs] for p in paragraphs]
    assert snapshot(back) == snapshot(runs)


def test_newlines_smuggled_into_a_run_become_real_paragraphs():
    """Pasted line separators must never reach the stream as raw newlines."""
    out = serialize([Paragraph(runs=[Run(text="a\nb c")])])
    assert "\n" not in out and " " not in out
    assert out.count("\\P") == 2


# -- what stays raw ------------------------------------------------------------

@pytest.mark.parametrize("content", [
    r"antes \S1/2; despues",          # stacked fraction
    r"fecha %<\AcVar Date>%",         # field
    r"\A1;centrado",                  # line alignment
    r"\Q15;oblicuo",                  # oblique
    r"\W0.8;ancho",                   # width factor
    r"\T1.5;tracking",                # tracking
])
def test_the_unrepresentable_codes_refuse_rich_mode(content):
    assert parse_runs(content, 2.5) is None


def test_the_safety_gate_fails_closed(monkeypatch):
    """If serializer and parser ever disagree, the answer is raw, not lies."""
    import core.mtext_format as M

    real = M.serialize
    monkeypatch.setattr(M, "serialize", lambda runs: real(runs) + "X")
    assert M.parse_runs(r"{\C1;rojo}", 2.5) is None


# -- paragraph properties (the ruler's substrate) ------------------------------

def test_paragraph_properties_are_rich_now_and_round_trip():
    content = r"\pxi2,l1,t4,c8;sangrado\Psigue igual"
    paragraphs = parse_runs(content, 2.5)
    assert paragraphs is not None
    props = paragraphs[0].resolved()
    assert props.indent == 2.0 and props.left == 1.0
    assert props.tab_stops == (4.0, "c8")
    # The second paragraph inherits, as the codes themselves do.
    assert paragraphs[1].resolved() == props
    again = parse_runs(serialize(paragraphs), 2.5)
    assert again is not None
    assert again[0].resolved() == props


def test_returning_to_default_properties_emits_a_reset():
    from core.mtext_format import DEFAULT_PROPS, Paragraph

    paragraphs = parse_runs(r"\pxl3;lista\P\pi0,l0,r0;normal", 2.5)
    assert paragraphs[1].resolved() == DEFAULT_PROPS
    out = serialize(paragraphs)
    assert "\\pxl3;" in out
    # Without a reset the second paragraph would inherit the margin.
    assert "\\pi0,l0,r0;" in out or "\\px" in out.split("\\P")[1]


def test_a_property_change_mid_paragraph_refuses_rich_mode():
    assert parse_runs(r"antes \pxl2;despues sin salto", 2.5) is None
