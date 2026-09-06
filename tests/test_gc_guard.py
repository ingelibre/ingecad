# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The garbage collector stays off the worker threads.

The bug (one SIGSEGV in five full runs, then a reproducer that crashed on
its first round): CPython collects cycles in whatever thread crosses the
allocation threshold, the cache warmer did, and the garbage it found held
icons made on the GUI thread -- Qt destroyed them off the GUI thread and
the process died. Every worker now runs under ``gc_guard.paused()``."""
from __future__ import annotations

import gc
import threading
import time

import pytest

from core import gc_guard


def test_paused_switches_the_collector_off_while_any_worker_runs():
    assert gc.isenabled() and gc_guard.pauses() == 0
    with gc_guard.paused():
        assert not gc.isenabled() and gc_guard.pauses() == 1
        with gc_guard.paused():                          # a second worker: still off
            assert not gc.isenabled() and gc_guard.pauses() == 2
        assert not gc.isenabled() and gc_guard.pauses() == 1     # the first is still alive
    assert gc.isenabled() and gc_guard.pauses() == 0
    with pytest.raises(RuntimeError):
        with gc_guard.paused():
            raise RuntimeError("a worker that fails")
    assert gc.isenabled() and gc_guard.pauses() == 0     # restored on the way out


class _Finalized:
    seen: list = []

    def __init__(self, tag):
        self.tag = tag
        self.me = self                                   # a cycle: only the collector frees it

    def __del__(self):
        _Finalized.seen.append(self.tag)


def test_a_worker_never_triggers_a_collection_but_the_main_thread_still_does():
    old = gc.get_threshold()
    gc.set_threshold(10, 1, 1)                           # a collection every few allocations
    gc.collect()
    _Finalized.seen.clear()
    try:
        _Finalized("made on the main thread")           # cyclic garbage waiting for a collection
        collected_in_worker = []

        def worker():
            with gc_guard.paused():
                for _ in range(20000):
                    [object() for _ in range(3)]         # allocations that would cross the threshold
                collected_in_worker.append(list(_Finalized.seen))

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
        assert collected_in_worker == [[]]               # nothing was finalized inside the worker
        assert gc.isenabled()
        gc.collect()                                     # the main thread collects, as it should
        assert _Finalized.seen == ["made on the main thread"]
    finally:
        gc.set_threshold(*old)
        _Finalized.seen.clear()


def test_every_worker_thread_of_the_app_runs_under_the_guard():
    """The five QThreads: their run() is the guard, their body is _run()."""
    import inspect

    from views import main_window, startup_dialog, tool_controller

    workers = [tool_controller._CacheWarmer, tool_controller._GhostWorker,
               main_window.RegenWorker, main_window._AutoSaveWorker,
               startup_dialog._ThumbnailWorker]
    for cls in workers:
        source = inspect.getsource(cls.run)
        assert "gc_guard.paused()" in source and "self._run()" in source, cls.__name__
        assert callable(getattr(cls, "_run", None)), cls.__name__


def test_the_warmer_survives_forced_collections_beside_icon_garbage(qapp):
    """The reproducer, shortened: collections forced on every allocation,
    icon cycles made on the GUI thread while the warmer walks. Before the
    guard this crashed the process on its first round."""
    from PySide6.QtGui import QColor, QIcon, QPixmap

    from core import actions
    from views.color_dialog import swatch_icon
    from views.main_window import MainWindow

    old = gc.get_threshold()
    win = MainWindow()
    try:
        win.new_document("m")
        for i in range(120):
            win.tools._execute(actions.add_circle((i * 3.0, (i % 7) * 2.0), 1.0))
        gc.set_threshold(5, 1, 1)
        for _round in range(2):
            win.tools.attach_document(win.document)      # starts the warmer thread
            t0 = time.perf_counter()
            while time.perf_counter() - t0 < 0.4:
                junk = []
                for k in range(30):
                    pix = QPixmap(8, 8)
                    pix.fill(QColor(k, k, k))
                    cell = [swatch_icon(k % 250 + 1), pix, QIcon(pix)]
                    cell.append(cell)
                    junk.append(cell)
                del junk
                qapp.processEvents()
        assert gc_guard.pauses() >= 0
    finally:
        gc.set_threshold(*old)
        win.document.dirty = False
        win.close()
