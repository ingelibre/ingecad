# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Layers audit: the -LAYER command flow, new layer semantics, Plot flag."""
from __future__ import annotations

import pytest

from core import layers as layer_ops
from core.commands import History
from core.document import Document


class Flow:
    """Drives a Prompt chain like the command line would."""

    def __init__(self, args=()):
        self.document = Document.new()
        self.history = History(self.document)
        self.echoes: list[str] = []
        self.prompt = layer_ops.layer_command(
            self.document, self.history, echo=self.echoes.append,
            refresh=lambda: None, args=args)

    def answer(self, *texts):
        for text in texts:
            assert self.prompt is not None, "flow already ended"
            self.prompt = self.prompt.on_input(text)
        return self.prompt

    @property
    def doc(self):
        return self.document.doc


def test_make_creates_and_sets_current():
    f = Flow()
    f.answer("M", "MUROS")
    assert "MUROS" in f.doc.layers
    assert layer_ops.current_layer_name(f.document) == "MUROS"
    f.answer("")                     # Enter exits the loop
    assert f.prompt is None


def test_set_refuses_frozen_and_turns_on_off_layer():
    f = Flow()
    f.answer("N", "A,B")             # comma list creates several (official)
    assert "A" in f.doc.layers and "B" in f.doc.layers
    f.answer("F", "A")               # freeze A
    f.answer("S", "A")
    assert layer_ops.current_layer_name(f.document) == "0"   # refused
    assert any("frozen" in e.lower() for e in f.echoes)
    f.answer("OFF", "B")
    assert not f.doc.layers.get("B").is_on()
    f.answer("S", "B")               # Set turns an off layer back on
    assert f.doc.layers.get("B").is_on()
    assert layer_ops.current_layer_name(f.document) == "B"


def test_wildcards_and_freeze_current_guard():
    f = Flow()
    f.answer("N", "MURO-1,MURO-2,EJES")
    f.answer("F", "MURO*")           # wildcard freezes both walls
    assert f.doc.layers.get("MURO-1").is_frozen()
    assert f.doc.layers.get("MURO-2").is_frozen()
    assert not f.doc.layers.get("EJES").is_frozen()
    f.answer("F", "0")               # current layer cannot be frozen
    assert not f.doc.layers.get("0").is_frozen()
    assert any("current" in e.lower() for e in f.echoes)
    # ONE undo reverts the whole wildcard freeze (composite)
    f.history.undo()
    assert not f.doc.layers.get("MURO-1").is_frozen()


def test_color_negative_turns_off_and_lweight_snaps():
    f = Flow()
    f.answer("N", "COTAS")
    f.answer("C", "-red", "COTAS")   # negative color = assign + turn off
    layer = f.doc.layers.get("COTAS")
    assert abs(layer.dxf.color) == 1
    assert not layer.is_on()
    f.answer("LW", "0.32", "COTAS")  # invalid -> nearest fixed (0.30)
    assert layer.dxf.lineweight == 30


def test_plot_description_and_rename():
    f = Flow()
    f.answer("N", "TEMP")
    f.answer("P", "N", "TEMP")       # No plot
    assert f.doc.layers.get("TEMP").dxf.plot == 0
    f.answer("D", "no imprimir", "TEMP")
    assert f.doc.layers.get("TEMP").description == "no imprimir"
    f.answer("R", "TEMP", "AUX")
    assert "AUX" in f.doc.layers and "TEMP" not in f.doc.layers


def test_args_are_consumed_like_autocad():
    # "-LA OFF EJES" typed in one line answers the prompts.
    f = Flow()
    f.answer("N", "EJES", "")
    prompt = layer_ops.layer_command(
        f.document, f.history, echo=lambda *_: None,
        refresh=lambda: None, args=("OFF", "EJES"))
    assert not f.doc.layers.get("EJES").is_on()
    assert prompt is not None        # back at the option loop


def test_question_mark_lists_layers():
    f = Flow()
    f.answer("N", "MUROS", "?")
    assert any("MUROS" in e for e in f.echoes)


# -- layer table semantics -----------------------------------------------------

def test_layers_in_use_sees_blocks_and_paperspace():
    doc = Document.new()
    doc.doc.layers.add("EN-BLOQUE")
    doc.doc.layers.add("EN-PAPEL")
    doc.doc.layers.add("VACIA")
    blk = doc.doc.blocks.new("B1")
    blk.add_line((0, 0), (1, 0), dxfattribs={"layer": "EN-BLOQUE"})
    ps = doc.doc.layouts.get("Layout1")
    ps.add_line((0, 0), (1, 0), dxfattribs={"layer": "EN-PAPEL"})
    used = layer_ops.layers_in_use(doc)
    assert "EN-BLOQUE" in used and "EN-PAPEL" in used
    assert "VACIA" not in used


def test_new_layer_inherits_properties():
    doc = Document.new()
    history = History(doc)
    history.execute(layer_ops.NewLayerCommand(
        "HIJA", color=1, linetype="Continuous", lineweight=50))
    layer = doc.doc.layers.get("HIJA")
    assert layer.dxf.color == 1 and layer.dxf.lineweight == 50


def test_plot_flag_skipped_by_export_render(qapp):
    from formats.pdf_out import build_graphics_scene

    doc = Document.new()
    doc.doc.layers.add("NOPLOT")
    doc.doc.layers.get("NOPLOT").dxf.plot = 0
    msp = doc.modelspace()
    msp.add_line((0, 0), (10, 0))                       # layer 0, plots
    msp.add_line((0, 5), (10, 5), dxfattribs={"layer": "NOPLOT"})
    scene = build_graphics_scene(doc, "Model")
    # only the plottable line produces items
    ys = {round(item.boundingRect().center().y()) for item in scene.items()}
    assert 0 in ys and 5 not in ys


# -- command line semantics ----------------------------------------------------

def test_dim_text_prompt_wants_raw_text():
    from tools.base import ToolContext
    from tools.dimension import DimLinearTool

    ctx = ToolContext(execute=lambda c: None, prompt=lambda *_: None,
                      echo=lambda *_: None, finish=lambda: None)
    tool = DimLinearTool(ctx)
    tool.start()
    tool.on_point((0, 0))
    tool.on_point((10, 0))
    assert not tool.wants_raw_text()
    assert tool.on_option("T")
    assert tool.wants_raw_text()      # Space must be literal here
    assert tool.on_option("<> m")     # the space survived into one token
    assert not tool.wants_raw_text()


def test_recent_commands_dedup(qapp):
    from views.command_line import CommandLine

    cl = CommandLine()
    for text in ("L", "L", "C", "Z E", "L"):
        cl.input._history.append(text)
    assert cl.recent_commands() == ["L", "Z", "C"]
