# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A plugin's own tools for the assistant, in IngeCAD and through MCP
(``PluginSpec.ai_tools``, plugin contract level 3).

The catalogue was fixed: an assistant could draw lines and circles but
knew nothing of what a plugin keeps -- the walls of a plan, the points of
a survey. A plugin now adds tools of its own; they come and go with it,
are called like the core's and, through MCP, are listed by the open
window.
"""
from __future__ import annotations

import shutil
import tempfile
import threading
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from core import actions
from core.ai import mcp_server
from core.ai import tools as ai
from core.plugins import API_VERSION, AiTool, LoadedPlugin, PluginSpec

PLUGIN = "muestra"


def _count_lines(ctx):
    return {"lines": len(ctx.document.modelspace().query("LINE"))}


def _add_line(ctx, length):
    if length <= 0:
        raise ai.ToolError("length must be positive")
    ctx.execute(actions.add_line((0, 0), (float(length), 0)))
    ctx.execute(actions.add_line((0, 1), (float(length), 1)))
    return {"added": 2}


def _ask_before_clearing(ctx, args):
    return "Erase every line?"


def _clear(ctx):
    lines = list(ctx.document.modelspace().query("LINE"))
    ctx.execute(actions.EraseCommand(lines))
    return {"erased": len(lines)}


SPEC = PluginSpec(
    id=PLUGIN, name="Sample", api_version=3,
    ai_tools=(
        AiTool("muestra_count_lines", "How many lines the drawing has.",
               _count_lines),
        AiTool("muestra_add_lines", "Two horizontal lines of a length.",
               _add_line, {"length": {"type": "number"}}, ("length",),
               mutates=True),
        AiTool("muestra_clear", "Erase every line.", _clear, mutates=True,
               confirm_text=_ask_before_clearing),
    ))


@pytest.fixture
def win(qapp, clean_settings):
    from views.main_window import MainWindow

    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    w.new_document()
    yield w
    w.plugins.deactivate(PLUGIN)
    w.plugins.loaded.pop(PLUGIN, None)
    w.document.dirty = False
    w.close()


def _activate(win, spec=SPEC):
    win.plugins.loaded[spec.id] = LoadedPlugin(spec.id, Path("."), False,
                                               spec=spec)
    return win.plugins.activate(spec.id)


def _names():
    return {t["name"] for t in ai.tool_list()}


def test_the_contract_is_at_level_three():
    assert API_VERSION >= 3


def test_the_tools_come_and_go_with_the_plugin(win):
    before = dict(ai.TOOLS)
    assert _activate(win)
    assert {"muestra_count_lines", "muestra_add_lines", "muestra_clear"} <= _names()
    win.plugins.deactivate(PLUGIN)
    assert ai.TOOLS == before                   # no trace left


def test_a_tool_is_called_like_the_core_ones_in_one_undo_step(win):
    assert _activate(win)
    depth = len(win.history._undo)
    with ai.Turn(win):
        done = ai.call(win, "muestra_add_lines", {"length": 4})
    assert done["added"] == 2 and done["revision"] == win.document.revision
    assert ai.call(win, "muestra_count_lines")["lines"] == 2
    assert len(win.history._undo) == depth + 1
    assert "length must be positive" in ai.call(
        win, "muestra_add_lines", {"length": -1})["error"]


def test_a_mutating_tool_checks_the_revision_and_asks_first(win):
    assert _activate(win)
    stale = win.document.revision
    ai.call(win, "muestra_add_lines", {"length": 4})
    refused = ai.call(win, "muestra_add_lines",
                      {"length": 4, "expected_revision": stale})
    assert "changed since revision" in refused["error"]
    schema = next(t for t in ai.tool_list()
                  if t["name"] == "muestra_add_lines")["parameters"]
    assert "expected_revision" in schema["properties"]
    declined = ai.call(win, "muestra_clear", {}, confirm=lambda q: False)
    assert "declined: Erase every line?" in declined["error"]
    assert ai.call(win, "muestra_count_lines")["lines"] == 2
    assert ai.call(win, "muestra_clear", {}, confirm=lambda q: True)["erased"] == 2


@pytest.mark.parametrize("name", ["count_lines", "Muestra_x", "muestra-x",
                                  "draw_line"])
def test_a_badly_named_tool_does_not_activate_the_plugin(win, name):
    before = dict(ai.TOOLS)
    spec = PluginSpec(id=PLUGIN, name="Sample",
                      ai_tools=(AiTool("muestra_ok", "fine", _count_lines),
                                AiTool(name, "bad", _count_lines)))
    assert not _activate(win, spec)
    assert ai.TOOLS == before


def test_two_windows_share_the_catalogue_until_the_last_lets_go(win):
    from views.main_window import MainWindow

    other = MainWindow()
    other.new_document()
    try:
        assert _activate(win) and _activate(other)
        win.plugins.deactivate(PLUGIN)
        assert "muestra_count_lines" in _names()
        other.plugins.deactivate(PLUGIN)
        assert "muestra_count_lines" not in _names()
    finally:
        other.plugins.loaded.pop(PLUGIN, None)
        other.document.dirty = False
        other.close()


@pytest.fixture
def bridge_env(monkeypatch):
    folder = Path(tempfile.mkdtemp(prefix="icmcp", dir="/tmp"))
    monkeypatch.setenv("INGECAD_MCP_SOCKET", str(folder / "s"))
    monkeypatch.setenv("INGECAD_MCP_TOKEN", str(folder / "t"))
    yield folder
    shutil.rmtree(folder, ignore_errors=True)


def test_mcp_lists_the_open_windows_plugin_tools(win, bridge_env):
    QSettings().setValue("ai/mcp", True)
    win._on_command_submitted("MCPSTART")
    assert win._mcp_bridge is not None
    assert _activate(win)
    server = mcp_server.Server(mcp_server.BridgeClient())
    answers = {}

    def ask(mid, method, params=None):
        message = {"jsonrpc": "2.0", "id": mid, "method": method,
                   "params": params or {}}
        thread = threading.Thread(
            target=lambda: answers.__setitem__(mid, server.handle(message)),
            daemon=True)
        thread.start()
        end = time.monotonic() + 30
        while mid not in answers:              # the window answers on its loop
            assert time.monotonic() < end, "timed out"
            QApplication.processEvents()
            time.sleep(0.005)
        return answers[mid]["result"]

    listed = {t["name"] for t in ask(1, "tools/list")["tools"]}
    assert {"draw_line", "muestra_add_lines"} <= listed
    done = ask(2, "tools/call", {"name": "muestra_add_lines",
                                 "arguments": {"length": 3}})
    assert done["isError"] is False
    assert len(win.document.modelspace().query("LINE")) == 2
    server.client.close()
    win._on_command_submitted("MCPSTOP")
