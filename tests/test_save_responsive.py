# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Ctrl+S on a big plan does not freeze the window.

The release bench (tools/release_bench.py, 2026-09-27) caught it: Save as
DWG on Plaza Yanque froze the window for ~10 s, already in v0.6.4. 7.7 s of
that is LibreDWG's conversion and the check that reads it back -- file
work that never touches the drawing -- so it runs on a worker while the
window keeps painting. Keyboard and mouse are held meanwhile, as AutoCAD
holds them while it saves, so nothing edits, opens or closes the drawing
halfway through.

The file half is slowed down here so there is time to watch.
"""
from __future__ import annotations

import time

import pytest
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest

from core import actions
from core.document import Document

SLOW = 1.2          # seconds the file half is made to take


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    from formats.dwg_bridge import find_dwg2dxf, find_dxf2dwg
    from views.main_window import MainWindow

    if find_dxf2dwg() is None or find_dwg2dxf() is None:
        pytest.skip("LibreDWG converters not built")
    real = Document.prepare_save

    def slow_prepare(self, path, version="r2000"):
        finish = real(self, path, version)

        def slow_finish():
            time.sleep(SLOW)
            return finish()
        return slow_finish

    monkeypatch.setattr(Document, "prepare_save", slow_prepare)
    win = MainWindow()
    win.new_document("m")
    win.show()
    win.activateWindow()
    QTest.qWaitForWindowActive(win, 5000)
    win.history.execute(actions.add_line((0, 0), (10, 5)))
    win.document.path = tmp_path / "plano.dwg"
    win.viewport.setFocus()
    yield win
    win.document.dirty = False
    win.close()


def _during_save(qapp, fn, at=0.4):
    QTimer.singleShot(int(at * 1000), fn)


def test_ctrl_s_keeps_the_window_alive_and_holds_input(qapp, window):
    ticks = []
    timer = QTimer()
    timer.setInterval(20)
    timer.timeout.connect(lambda: ticks.append(time.monotonic()))
    timer.start()
    typed = []

    def type_during_save():
        # a key, a shortcut and a close, all halfway through the save, sent
        # as the system sends them: to the native window, where Qt's own
        # modality decides (a key sent straight to a widget skips it)
        handle = window.windowHandle()
        QTest.keyClick(handle, Qt.Key_L)
        QTest.keySequence(handle, QKeySequence("Ctrl+Z"))   # would undo the line
        typed.append(window.command_line.input.text())
        typed.append(len(window.document.modelspace()))
        window.close()
        typed.append(window.isVisible())

    _during_save(qapp, type_during_save)
    started = time.monotonic()
    QTest.keySequence(window, QKeySequence("Ctrl+S"))
    elapsed = time.monotonic() - started
    timer.stop()

    assert elapsed >= SLOW                                # it did wait for the save
    assert (window.document.path.stat().st_size > 0 and not window.document.dirty)
    during = [t for t in ticks if started < t < started + elapsed]
    gaps = [b - a for a, b in zip(during, during[1:])]
    assert len(during) > SLOW / 0.02 / 2                  # the loop kept turning
    assert max(gaps) < 0.5, f"the window froze {max(gaps):.2f} s"
    assert typed == ["", 1, True], "input reached the window mid-save"
    # and once saved, the keyboard is the canvas's again
    from PySide6.QtWidgets import QApplication
    QTest.qWait(50)
    assert QApplication.focusWidget() is window.viewport
    QTest.keyClick(window.windowHandle(), Qt.Key_L)
    assert window.command_line.input.text().upper() == "L"


def test_a_failed_save_says_so_and_leaves_the_drawing_unsaved(qapp, window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    def broken(self, path, version="r2000"):
        def finish():
            raise OSError("disk full")
        return finish

    monkeypatch.setattr(Document, "prepare_save", broken)
    shown = []
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *a, **k: shown.append(a[2])))
    assert window.save_document() is False
    assert window.document.dirty
    assert shown and "disk full" in shown[0]
    assert window._save_worker is None                    # ready for the next one


def test_no_automatic_save_starts_while_ctrl_s_is_saving(qapp, window):
    """Both write the same drawing; ezdxf updates its header as it saves."""
    seen = []

    def check():
        window._last_mutation = 0.0     # long quiet: only the save stands in the way
        seen.append(window._autosave_idle())

    _during_save(qapp, check)
    QTest.keySequence(window, QKeySequence("Ctrl+S"))
    assert seen == [False]
