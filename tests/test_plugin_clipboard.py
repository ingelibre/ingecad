# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A plugin may take what a paste finds on the clipboard, and add formats
of its own to a copy (on_paste, on_copy; level 2).

A third-party plugin wrapped the controller's paste to place a picture
copied from another program, and read the clipboard module's internals
to add its own format to IngeCAD's copies.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest
from PySide6.QtCore import QMimeData
from PySide6.QtGui import QGuiApplication

from core import actions
from core.plugins import LoadedPlugin, PluginSpec

PLUGIN = "ejemplo_portapapeles"
FORMAT = "application/x-ejemplo-count"


@pytest.fixture
def win(qapp, clean_settings):
    from views.main_window import MainWindow

    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    w.new_document()
    QGuiApplication.clipboard().clear()
    yield w
    w.tools.cancel()
    w.plugins.deactivate(PLUGIN)
    w.plugins.loaded.pop(PLUGIN, None)
    QGuiApplication.clipboard().clear()
    w.document.dirty = False
    w.close()


def _activate(win, **hooks):
    spec = PluginSpec(id=PLUGIN, name="Clip", **hooks)
    win.plugins.loaded[spec.id] = LoadedPlugin(spec.id, Path("."), False,
                                               spec=spec)
    assert win.plugins.activate(spec.id)


def _survey_paste(ctx, mime):
    """``SURVEY x,y`` text pasted from a spreadsheet: a point there."""
    text = mime.text() if mime.hasText() else ""
    if not text.startswith("SURVEY "):
        return False
    x, y = (float(v) for v in text.split()[1].split(","))
    ctx.host.tools._execute(actions.add_point((x, y)))
    return True


def _clip_text(text):
    mime = QMimeData()
    mime.setText(text)
    QGuiApplication.clipboard().setMimeData(mime)


def _history(win):
    return win.command_line.history.toPlainText()


def test_ctrl_v_with_foreign_contents_goes_to_the_plugin(win):
    _clip_text("SURVEY 3,4")
    win._cmd_paste()                                  # control first
    assert "Clipboard is empty." in _history(win)
    _activate(win, on_paste=_survey_paste)
    win._cmd_paste()
    (point,) = win.document.modelspace().query("POINT")
    assert tuple(point.dxf.location)[:2] == (3, 4)
    assert win.tools.tool is None


def test_typed_pasteclip_asks_the_plugin_too(win):
    _activate(win, on_paste=_survey_paste)
    _clip_text("SURVEY 5,6")
    win._on_command_submitted("PASTECLIP")
    assert len(win.document.modelspace().query("POINT")) == 1


def test_what_the_plugin_leaves_is_the_core_s_paste(win):
    _activate(win, on_paste=_survey_paste)
    win.tools._execute(actions.add_line((0, 0), (10, 0)))
    win.tools.select_all()
    win._cmd_copy()
    _clip_text("not ours")
    win._cmd_paste()
    assert win.tools.tool is not None and win.tools.tool.name == "PASTECLIP"


def test_a_copy_carries_the_plugin_s_format(win, qapp):
    def add_count(ctx, entities, mime):
        mime.setData(FORMAT, str(len(entities)).encode())

    _activate(win, on_copy=add_count)
    win.tools._execute(actions.add_line((0, 0), (10, 0)))
    win.tools._execute(actions.add_circle((0, 0), 2))
    win.tools.select_all()
    win._cmd_copy()
    board = QGuiApplication.clipboard()
    t0 = time.monotonic()
    while (board.mimeData() is None
           or not board.mimeData().hasFormat(FORMAT)) \
            and time.monotonic() - t0 < 10:
        qapp.processEvents()
    assert bytes(board.mimeData().data(FORMAT)) == b"2"
