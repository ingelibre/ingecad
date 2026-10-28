# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Delete-selection and clipboard (copy/cut/paste) — headless via PasteTool."""
from __future__ import annotations

import ezdxf
import pytest

from core import actions
from core.commands import History
from core.document import Document
from tools.base import ToolContext
from tools.edit import PasteTool


class Harness:
    def __init__(self):
        self.document = Document.new()
        self.history = History(self.document)
        self.finished = False
        self._clip = None
        self.ctx = ToolContext(
            execute=self.history.execute,
            prompt=lambda *_a: None,
            echo=lambda *_a: None,
            finish=lambda: setattr(self, "finished", True),
            services=self,
        )

    @property
    def msp(self):
        return self.document.modelspace()

    def clipboard_data(self):
        return self._clip if self._clip else (None, None)


def test_paste_translates_by_base_to_target():
    h = Harness()
    a = h.msp.add_line((0, 0), (2, 0))
    b = h.msp.add_circle((1, 1), 1)
    # emulate a copy: store copies + base at the extents min (0,0)
    h._clip = ([a.copy(), b.copy()], (0, 0))
    tool = PasteTool(h.ctx)
    tool.start()
    tool.on_point((10, 5))         # insertion point
    lines = [e for e in h.msp.query("LINE")]
    circles = [e for e in h.msp.query("CIRCLE")]
    assert len(lines) == 2 and len(circles) == 2   # originals + pasted
    pasted_line = [ln for ln in lines if ln is not a][0]
    assert pasted_line.dxf.start.x == pytest.approx(10)
    assert pasted_line.dxf.start.y == pytest.approx(5)


def test_paste_undo_removes_copies():
    h = Harness()
    a = h.msp.add_line((0, 0), (2, 0))
    h._clip = ([a.copy()], (0, 0))
    tool = PasteTool(h.ctx)
    tool.start()
    tool.on_point((10, 0))
    assert len(h.msp.query("LINE")) == 2
    h.history.undo()
    assert len(h.msp.query("LINE")) == 1


def test_paste_reusable_twice():
    h = Harness()
    a = h.msp.add_line((0, 0), (1, 0))
    h._clip = ([a.copy()], (0, 0))
    for target in ((5, 0), (0, 5)):
        tool = PasteTool(h.ctx)
        tool.start()
        tool.on_point(target)
    assert len(h.msp.query("LINE")) == 3   # original + two pastes


def test_paste_empty_clipboard_finishes():
    h = Harness()
    tool = PasteTool(h.ctx)
    tool.start()
    assert h.finished
    assert len(h.msp.query("LINE")) == 0


def test_erase_command_removes_and_undo_restores():
    # Delete-selection routes through EraseCommand; verify it round-trips.
    h = Harness()
    a = h.msp.add_line((0, 0), (2, 0))
    h.history.execute(actions.EraseCommand([a]))
    assert len(h.msp.query("LINE")) == 0
    h.history.undo()
    assert len(h.msp.query("LINE")) == 1


def test_erase_unlinks_for_instant_overlay_filter():
    # The overlay filters by owner=None; erase must unlink, undo must relink.
    h = Harness()
    a = h.msp.add_line((0, 0), (2, 0))
    h.history.execute(actions.EraseCommand([a]))
    assert a.dxf.owner is None       # invisible to the overlay immediately
    h.history.undo()
    assert a.dxf.owner is not None   # visible again immediately


def test_undo_records_removed_handles_for_surgical_hide():
    # Commands whose undo destroys entities must record the handles so the
    # UI can hide the base-scene copies without waiting for a regen.
    h = Harness()
    add = actions.add_line((0, 0), (3, 3))
    h.history.execute(add)
    handle = add.entity.dxf.handle
    h.history.undo()
    assert add.removed_handles == [handle]

    clip = [h.msp.add_line((0, 0), (1, 0)).copy()]
    paste = actions.PasteCommand(clip, 5, 5)
    h.history.execute(paste)
    handles = [c.dxf.handle for c in paste.copies]
    h.history.undo()
    assert paste.removed_handles == handles

    c = h.msp.add_circle((5, 5), 2)
    rep = actions.ReplaceEntitiesCommand(
        "TRIM", [c], [lambda m: m.add_circle((5, 5), 1)])
    h.history.execute(rep)
    new_handles = [e.dxf.handle for e in rep.new_entities]
    h.history.undo()
    assert rep.removed_handles == new_handles


def _colleague(tmp_path):
    """A drawing whose content needs its own layer, block, text style and
    a dimension (with its anonymous *D block)."""
    doc = ezdxf.new("R2018", setup=True)
    doc.layers.add("MUROS", color=1)
    doc.styles.add("ROMANS", font="romans.shx")
    door = doc.blocks.new("PUERTA")
    door.add_arc((0, 0), 1, 0, 90)
    door.add_line((0, 0), (1, 0))
    msp = doc.modelspace()
    msp.add_blockref("PUERTA", (5, 5), dxfattribs={"layer": "MUROS"})
    msp.add_text("Hola", dxfattribs={"style": "ROMANS", "layer": "MUROS"})
    msp.add_linear_dim(base=(0, 3), p1=(0, 0), p2=(10, 0)).render()
    path = tmp_path / "colega.dxf"
    doc.saveas(path)
    return path


def _open(qapp, win, path):
    import time

    win.open_path(path)
    t0 = time.monotonic()
    while (win._open_thread is not None or win._regen_worker is not None) \
            and time.monotonic() - t0 < 30:
        qapp.processEvents()
    qapp.processEvents()
    # the "Loading file" window (#50) may have taken the activation
    from PySide6.QtTest import QTest

    win.activateWindow()
    QTest.qWaitForWindowActive(win, 5000)
    win.viewport.setFocus()
    qapp.processEvents()


def test_copy_in_one_drawing_and_paste_in_another_keeps_what_it_needs(qapp, tmp_path):
    # #75: copy/paste between files "truncated" the elements -- the pasted
    # copies named the first drawing's block, layer and styles, which the
    # second one did not have. Pressed for real: Ctrl+C, open, Ctrl+V.
    from PySide6.QtGui import QKeySequence
    from PySide6.QtTest import QTest

    from views.main_window import MainWindow

    mine = ezdxf.new("R2018")
    mine.modelspace().add_circle((0, 0), 1)
    mine.blocks.new("*D1")                       # a name the paste must not take
    mine.saveas(tmp_path / "mio.dxf")
    win = MainWindow()
    win.maybe_save_changes = lambda: True
    win.show()
    # Xvfb has no window manager: a keystroke to an inactive window is lost
    win.activateWindow()
    QTest.qWaitForWindowActive(win, 5000)
    try:
        _open(qapp, win, _colleague(tmp_path))
        win.tools.select_all()
        win.viewport.setFocus()
        QTest.keySequence(win.viewport, QKeySequence("Ctrl+C"))
        qapp.processEvents()
        assert win.tools.clipboard_originals(), "Ctrl+C did not reach the canvas"
        _open(qapp, win, tmp_path / "mio.dxf")
        win.viewport.setFocus()
        QTest.keySequence(win.viewport, QKeySequence("Ctrl+V"))
        qapp.processEvents()
        assert win.tools.tool is not None and win.tools.tool.name == "PASTECLIP", \
            "Ctrl+V did not reach the canvas"
        win.tools.on_text("100,0")
        qapp.processEvents()
        out = tmp_path / "pegado.dxf"
        win.document.save_as(out)
    finally:
        win.document.dirty = False
        win.close()
    back = ezdxf.readfile(out)
    pasted = {e.dxftype(): e for e in back.modelspace()}
    assert set(pasted) == {"CIRCLE", "INSERT", "TEXT", "DIMENSION"}
    assert "MUROS" in back.layers and "ROMANS" in back.styles
    assert len(back.blocks.get("PUERTA")) == 2
    # moved together, about 100 to the right (the base is the selection's
    # lower-left corner, a little left of the text)
    ins, text = pasted["INSERT"].dxf.insert, pasted["TEXT"].dxf.insert
    assert (ins.x - text.x, ins.y - text.y) == pytest.approx((5, 5))
    assert 100 < text.x < 101
    geometry = pasted["DIMENSION"].dxf.geometry
    assert geometry != "*D1" and len(back.blocks.get(geometry)) > 0
    assert not back.audit().has_errors


def test_copy_in_one_window_and_paste_in_another(qapp, tmp_path):
    # #75 again, with 0.6.6 on Windows: two drawings open = two IngeCAD
    # windows, each its own program, and Ctrl+V in the second one said
    # "Clipboard is empty." The copy now rides the system clipboard as a
    # DXF. Two windows here never share their in-memory clipboards, as two
    # processes would not.
    from PySide6.QtGui import QKeySequence
    from PySide6.QtTest import QTest

    from views.main_window import MainWindow

    mine = ezdxf.new("R2018")
    mine.modelspace().add_circle((0, 0), 1)
    mine.saveas(tmp_path / "mio.dxf")
    first, second = MainWindow(), MainWindow()
    for win in (first, second):
        win.maybe_save_changes = lambda: True
        win.show()
    try:
        _open(qapp, first, _colleague(tmp_path))
        _open(qapp, second, tmp_path / "mio.dxf")
        first.activateWindow()
        QTest.qWaitForWindowActive(first, 5000)
        first.tools.select_all()
        first.viewport.setFocus()
        QTest.keySequence(first.viewport, QKeySequence("Ctrl+C"))
        qapp.processEvents()
        assert second.tools._clipboard is None, "the windows share memory"
        from views import clipboard
        import time
        t0 = time.monotonic()
        while (clipboard.current_id() != first.tools._clip_id
               and time.monotonic() - t0 < 10):
            qapp.processEvents()
        assert clipboard.current_id() == first.tools._clip_id, \
            "the copy never reached the system clipboard"
        second.activateWindow()
        QTest.qWaitForWindowActive(second, 5000)
        second.viewport.setFocus()
        QTest.keySequence(second.viewport, QKeySequence("Ctrl+V"))
        qapp.processEvents()
        assert second.tools.tool is not None and second.tools.tool.name == "PASTECLIP", \
            "Clipboard is empty."
        second.tools.on_text("100,0")
        qapp.processEvents()
        out = tmp_path / "pegado.dxf"
        second.document.save_as(out)
        # pasted again from memory in the window that copied
        first.activateWindow()
        QTest.qWaitForWindowActive(first, 5000)
        first.viewport.setFocus()
        QTest.keySequence(first.viewport, QKeySequence("Ctrl+V"))
        qapp.processEvents()
        assert first.tools.tool is not None and first.tools.tool.name == "PASTECLIP"
        assert first.tools.clipboard_data()[0] is first.tools._clipboard[0]
        first.tools.cancel()
    finally:
        for win in (first, second):
            win.document.dirty = False
            win.close()
    back = ezdxf.readfile(out)
    kinds = sorted(e.dxftype() for e in back.modelspace())
    assert kinds == ["CIRCLE", "DIMENSION", "INSERT", "TEXT"]
    assert "MUROS" in back.layers and "ROMANS" in back.styles
    assert len(back.blocks.get("PUERTA")) == 2
    pasted = {e.dxftype(): e for e in back.modelspace() if e.dxftype() != "CIRCLE"}
    ins, text = pasted["INSERT"].dxf.insert, pasted["TEXT"].dxf.insert
    assert (ins.x - text.x, ins.y - text.y) == pytest.approx((5, 5))
    assert 100 < text.x < 101
    assert len(back.blocks.get(pasted["DIMENSION"].dxf.geometry)) > 0
    assert not back.audit().has_errors


def test_a_cut_is_a_snapshot_on_the_system_clipboard(qapp):
    """Ctrl+X erases the originals; the other window still gets them."""
    from views import clipboard

    document = Document.new()
    line = document.modelspace().add_line((0, 0), (3, 4), dxfattribs={"layer": "0"})
    clip_id = clipboard.publish([line], (1.0, 2.0))
    assert clip_id and clipboard.current_id() == clip_id
    document.modelspace().delete_entity(line)
    sources, base = clipboard.read_dxf(clipboard.current_dxf())
    assert base == (1.0, 2.0)
    assert [e.dxftype() for e in sources] == ["LINE"]
    assert sources[0].dxf.end == (3, 4, 0)


def test_a_big_copy_reaches_the_system_clipboard_when_the_window_is_left(qapp):
    """Release bench against v0.6.6: Ctrl+C froze 1.5 s on a 10 000-object
    plan building the clipboard drawing. A big copy now stays in memory
    (pasting here works at once) and goes out when the user leaves the
    window for another one -- where the other IngeCAD will paste it."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication

    from core import actions
    from views import clipboard
    from views.main_window import MainWindow

    first, second = MainWindow(), MainWindow()
    for win in (first, second):
        win.show()
        win.new_document()
    try:
        tools = first.tools
        n = tools.CLIPBOARD_NOW_LIMIT + 50
        for i in range(n):
            tools._execute(actions.add_line((0, i), (5, i)))
        clipboard.publish([second.document.modelspace().add_line((0, 0), (1, 1))],
                          (0, 0))               # something else on the clipboard
        before = clipboard.current_id()
        tools.select_all()
        assert tools.copy_selection()
        import time
        t0 = time.monotonic()
        while tools._clip_writers and time.monotonic() - t0 < 20:
            qapp.processEvents()             # any write in flight lands
        qapp.processEvents()
        assert clipboard.current_id() == before, "a big copy went out at once"
        assert tools.clipboard_data()[0] is tools._clipboard[0], "paste here uses memory"
        QGuiApplication.instance().applicationStateChanged.emit(Qt.ApplicationInactive)
        t0 = time.monotonic()
        while clipboard.current_id() != tools._clip_id and time.monotonic() - t0 < 20:
            qapp.processEvents()
        assert tools._clip_id and clipboard.current_id() == tools._clip_id
        sources, _base = second.tools.clipboard_data()
        assert len(sources) == n
    finally:
        for win in (first, second):
            win.document.dirty = False
            win.close()


def test_copy_ids_differ_between_processes_with_the_same_pid():
    """Inside the Flatpak every IngeCAD is pid 2 of its sandbox: a copy id
    made of the pid and a counter was the same in two windows."""
    import subprocess
    import sys

    code = ("import sys; sys.path.insert(0, %r); from views import clipboard; "
            "print(clipboard._PROCESS)") % str(__import__("pathlib").Path(__file__).resolve().parents[1])
    ids = {subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          env={**__import__("os").environ, "QT_QPA_PLATFORM": "offscreen"}
                          ).stdout.strip() for _ in range(2)}
    assert len(ids) == 2 and all(ids)
