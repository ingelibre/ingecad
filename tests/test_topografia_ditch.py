# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Topography, the ditch in cut (fossé en déblai): a trapezoidal ditch at
the foot of each cut slope, drawn in the sections and measured in the
volumes; none in fill; DITCH sets it and it is remembered."""
from __future__ import annotations

import pytest

from core.commands import History
from core.document import Document
from plugins.topografia import profile
from tools.base import ToolContext


def _flat_ground(z: float = 102.0):
    return [(o * 0.5, z) for o in range(-60, 61)]


def test_a_ditch_lies_at_the_foot_of_each_cut_slope():
    t = profile.Template(width=7.0, cut_hv=1.0, fill_hv=1.5, ditch_depth=0.6, ditch_bottom=0.5,
                         ditch_inner_hv=1.0)
    d = profile.design_section(_flat_ground(), 100.0, t)
    expected = [(-7.2, 102.0), (-4.6, 99.4), (-4.1, 99.4), (-3.5, 100.0),
                (3.5, 100.0), (4.1, 99.4), (4.6, 99.4), (7.2, 102.0)]
    assert [c for p in d for c in p] == pytest.approx([c for p in expected for c in p])


def test_the_ditch_adds_its_own_cut():
    ground = _flat_ground()
    plain = profile.areas(ground, profile.design_section(ground, 100.0, profile.Template(7.0, 1.0, 1.5)))
    t = profile.Template(7.0, 1.0, 1.5, ditch_depth=0.6, ditch_bottom=0.5, ditch_inner_hv=1.0)
    with_ditch = profile.areas(ground, profile.design_section(ground, 100.0, t))
    # each side: the ditch (0.6 deep, 0.6 + 0.5 wide at its foot) and the
    # slope starting 0.6 lower: a trapezoid in place of the 2 m triangle
    side_plain = 7.0 * 2.0 / 2.0 + 2.0 * 2.0 / 2.0                  # platform half + slope
    side_ditch = 3.5 * 2.0 + 0.6 * (2.0 + 2.6) / 2.0 + 0.5 * 2.6 + 2.6 * 2.6 / 2.0
    assert plain[0] == pytest.approx(2 * side_plain)
    assert with_ditch[0] == pytest.approx(2 * side_ditch)


def test_no_ditch_in_fill():
    t = profile.Template(7.0, 1.0, 1.5, ditch_depth=0.6)
    d = profile.design_section(_flat_ground(98.0), 100.0, t)
    assert len(d) == 4 and min(z for _o, z in d) == pytest.approx(98.0)


class _Services:
    def __init__(self, document):
        self.document = document


def test_ditch_tool_sets_and_clears_the_ditch(monkeypatch):
    from plugins.topografia.tools import DitchTool

    saved = {}
    monkeypatch.setattr(profile, "save_ditch", lambda d, b, h: saved.update(d=d, b=b, h=h))
    monkeypatch.setattr(profile, "template_from_settings", lambda: profile.Template())
    document = Document.new()
    history = History(document)
    echoed, prompts, done = [], [], []
    ctx = ToolContext(execute=history.execute, prompt=prompts.append, echo=echoed.append,
                      finish=lambda: done.append(True), undo_last=history.undo,
                      services=_Services(document))
    tool = DitchTool(ctx)
    tool.start()
    assert prompts[-1] == "Ditch depth in cut (0 = none) <0>:"
    tool.on_option("0.5")
    assert prompts[-1] == "Ditch bottom width <0.5>:"
    tool.on_option("0.4")
    assert prompts[-1] == "Ditch side towards the road H:V <1>:"
    tool.on_option("3")
    assert done and saved == {"d": 0.5, "b": 0.4, "h": 3.0}
    assert echoed[-1] == "Ditch in cut: depth 0.5 m, bottom 0.4 m, side 3:1."
    done.clear()
    tool = DitchTool(ctx)
    tool.start()
    tool.on_enter()                                   # depth 0: no ditch
    assert done and saved["d"] == 0.0 and echoed[-1] == "No ditch in the cross-sections."
