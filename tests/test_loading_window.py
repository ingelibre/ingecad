# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The "Loading <name>…" window (issue #50): shown for a long open, regen or
save, with the phase and the elapsed time; Cancel abandons an open."""
from __future__ import annotations

import time

import ezdxf
import pytest


def _wait(qapp, win, timeout_s=30.0):
    t0 = time.monotonic()
    while win._open_thread is not None and time.monotonic() - t0 < timeout_s:
        qapp.processEvents()
    qapp.processEvents()


def _dxf(tmp_path, name="plan.dxf"):
    doc = ezdxf.new("R2018")
    doc.modelspace().add_line((0, 0), (100, 50))
    path = tmp_path / name
    doc.saveas(path)
    return path


def test_the_window_appears_with_the_file_name_and_phases_then_goes(qapp, tmp_path):
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    win._loading_min_ms = 0                    # a tiny file: show at once anyway
    try:
        phases = []
        original = win._loading_phase

        def spy(text):
            phases.append(text)
            original(text)

        win._loading_phase = spy
        win.open_path(_dxf(tmp_path))
        window = win._loading_window
        assert window.active and "plan.dxf" in window._title.text()
        assert window.testAttribute(window.WA_ShowWithoutActivating
                                    if hasattr(window, "WA_ShowWithoutActivating")
                                    else __import__("PySide6.QtCore").QtCore.Qt.WA_ShowWithoutActivating)
        _wait(qapp, win)
        assert win.document is not None and win.document.path is not None
        assert any("Reading" in p for p in phases) and any("Regenerating" in p for p in phases), phases
        assert not window.active and not window.isVisible(), "the window stayed"
    finally:
        win.close()


def test_a_small_file_never_flashes_the_window(qapp, tmp_path):
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    # the rule under test is "not before min_ms"; on a slow CI machine even
    # a tiny file can take longer than the default 400 ms, and then showing
    # the window is right -- so the threshold is set beyond any open here
    win._loading_min_ms = 60_000
    try:
        win.open_path(_dxf(tmp_path))
        shown = False
        t0 = time.monotonic()
        while win._open_thread is not None and time.monotonic() - t0 < 30:
            qapp.processEvents()
            shown = shown or win._loading_window.isVisible()
        assert not shown
    finally:
        win.close()


def test_cancel_abandons_the_open(qapp, tmp_path):
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    win._loading_min_ms = 0
    try:
        win.new_document()
        before = win.document
        said = []
        win.command_line.echo = lambda text, *a, **k: said.append(text)
        win.open_path(_dxf(tmp_path))
        win._loading_window._cancel.click()      # the user gives up
        assert not win._loading_window.active
        _wait(qapp, win)
        assert win.document is before, "the cancelled drawing replaced the current one"
        assert any("cancelled" in s for s in said), said
    finally:
        win.document.dirty = False
        win.close()


def test_the_loading_window_api_is_self_contained(qapp):
    from views.loading_window import LoadingWindow

    w = LoadingWindow()
    cancelled = []
    w.begin("Loading x…", on_cancel=lambda: cancelled.append(1), min_ms=0)
    assert w.isVisible() and w._cancel.isVisible()
    w.phase("Reading…")
    assert w._phase.text() == "Reading…"
    assert w.elapsed_s() >= 0.0
    w._cancel.click()
    assert cancelled == [1] and not w.active and not w.isVisible()
    w.begin("Regenerating…", min_ms=0)
    assert not w._cancel.isVisible(), "no Cancel when nothing can be cancelled"
    w.finish()
    assert not w.isVisible()
    w.deleteLater()


def test_the_open_phases_reach_the_window_on_the_gui_thread(qapp, tmp_path):
    """A lambda on the worker's `phase` ran in the OPEN thread (PySide calls a
    plain callable in the emitter's thread): the loading window's label was
    set off the GUI thread -- the CI's segfaults and bus errors here."""
    import threading

    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    try:
        win.new_document()
        where = []
        real = win._loading_phase
        win._loading_phase = lambda text: (
            where.append(threading.current_thread() is threading.main_thread()),
            real(text))
        win.open_path(_dxf(tmp_path))
        _wait(qapp, win)
        assert where, "no phase was reported"
        assert all(where), "a phase reached the window from the open thread"
    finally:
        win.document.dirty = False
        win.close()


def test_no_worker_signal_is_connected_to_a_plain_callable():
    """The rule behind the test above, for every worker: a lambda or partial
    on a worker's signal runs on the worker's thread."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    bad = re.compile(r"(worker|warmer|thread)\w*\.\w+\.connect\(\s*(lambda|partial|functools)")
    found = []
    for folder in ("core", "views", "formats", "render", "plugins", "tools"):
        for path in (root / folder).rglob("*.py"):
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if bad.search(line):
                    found.append(f"{path.relative_to(root)}:{n}: {line.strip()}")
    assert not found, "\n".join(found)


def test_no_worker_is_deleted_by_qt_while_python_holds_it():
    """`finished -> worker.deleteLater` had Qt delete the open worker on its
    own thread while the window dropped the Python reference: both destroyed
    it (SIGBUS in Shiboken::Object::destroy, caught by gdb on the CI). A
    worker the window keeps a reference to has one owner: Python."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    bad = re.compile(r"\.finished\.connect\(\s*\w*(worker|warmer)\w*\.deleteLater")
    found = []
    for folder in ("core", "views", "formats", "render", "plugins", "tools"):
        for path in (root / folder).rglob("*.py"):
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if bad.search(line):
                    found.append(f"{path.relative_to(root)}:{n}: {line.strip()}")
    assert not found, "\n".join(found)
