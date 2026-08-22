# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""End to end: the word the Spanish prompt offers is a word that works.

Issue #4 was not that the resolver was missing -- it was that the interface
offered "Suprimir" and then rejected it. So these drive the real tools and
the real LAYOUT flow, in Spanish, typing what a Spanish user reads on screen.

Every case is checked three ways: the localized word, the English key (which
must never stop working, whatever the language), and AutoCAD's ``_`` global
form.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import i18n  # noqa: E402
from tools.base import ToolContext  # noqa: E402
from tools.draw import CircleTool  # noqa: E402
from tools.modify import ChamferTool  # noqa: E402


@pytest.fixture
def spanish():
    i18n.set_language("es")
    yield
    i18n.set_language("en")


def _ctx():
    shown: list[str] = []
    ctx = ToolContext(execute=lambda command: None, prompt=shown.append,
                      echo=lambda text: None, finish=lambda: None)
    return ctx, shown


@pytest.mark.parametrize("typed", ["2P", "2p", "_2P"])
def test_circle_two_point_mode(spanish, typed) -> None:
    """2P survives folding: its key is 2P, not P, or it would clash with 3P."""
    ctx, shown = _ctx()
    tool = CircleTool(ctx)
    tool.start()
    assert "[3P/2P/Ttr" in shown[0] or "3P" in shown[0]
    assert tool.on_option(typed) is True
    assert tool._mode == "2P"


@pytest.mark.parametrize("typed", ["Distancia", "distancia", "D", "_D", "_DISTANCE"])
def test_chamfer_distance_option(spanish, typed) -> None:
    """The Spanish prompt reads [Distancia(D)/Recortar(T)]; both must answer."""
    ctx, shown = _ctx()
    tool = ChamferTool(ctx)
    tool.start()
    assert "Distancia(D)" in shown[-1], shown[-1]
    assert tool.on_option(typed) is True
    assert tool._await == "d1"


def test_the_prompt_offers_only_words_that_work(spanish) -> None:
    """Read the Spanish prompt off the screen, type each option, all consumed."""
    from core.i18n import keywords

    ctx, shown = _ctx()
    tool = ChamferTool(ctx)
    tool.start()
    source = tool._prompt_source
    for option in keywords.options(source):
        fresh = ChamferTool(ctx)
        fresh.start()
        word = option.localized.split("(")[0].strip() or option.english
        assert fresh.on_option(word) is True, f"{word!r} was offered and refused"


@pytest.mark.parametrize("typed", ["Suprimir", "suprimir", "D", "_D", "_DELETE"])
def test_layout_takes_the_word_it_prints(typed, spanish) -> None:
    """The exact report: LAYOUT promised "Suprimir" and only took "D"."""
    import ezdxf

    from core import layouts as layout_ops
    from core.commands import History
    from core.document import Document

    document = Document(ezdxf.new(setup=True))
    document.doc.layouts.new("Sheet")
    echoes: list[str] = []
    prompt = layout_ops.layout_command(
        document, History(document),
        switch=lambda name: None, echo=echoes.append,
        refresh=lambda: None, current=lambda: "Sheet", args=())

    assert "Suprimir(D)" in prompt.text          # what the user reads
    follow_up = prompt.on_input(typed)           # what the user types
    assert follow_up is not None, f"{typed!r} was offered and refused"
    assert "suprimir" in follow_up.text.lower() or "elimin" in follow_up.text.lower(), \
        follow_up.text


def test_layout_still_refuses_a_word_it_never_offered(spanish) -> None:
    import ezdxf

    from core import layouts as layout_ops
    from core.commands import History
    from core.document import Document

    document = Document(ezdxf.new(setup=True))
    echoes: list[str] = []
    prompt = layout_ops.layout_command(
        document, History(document),
        switch=lambda name: None, echo=echoes.append,
        refresh=lambda: None, current=lambda: "Model", args=())
    assert prompt.on_input("Borrar") is None     # not a LAYOUT keyword
    assert echoes and "Borrar" in echoes[-1]


def test_an_option_is_not_eaten_by_an_earlier_prompt(spanish) -> None:
    """A prompt with no options clears them: "D" is then just text."""
    ctx, _ = _ctx()
    tool = ChamferTool(ctx)
    tool.start()
    assert tool.option("Distancia") == "D"
    tool.prompt("Specify first chamfer distance <{d}>:", d="0")
    assert tool.option("Distancia") == ""
