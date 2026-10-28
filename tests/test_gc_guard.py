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
import re
import time
from pathlib import Path

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
    """Deterministic on purpose: the garbage is made AFTER the worker has
    paused the collector (the first version made it before, and on Python
    3.12 the main thread's own allocations collected it before the worker
    ever ran -- a green test on 3.14, a red one on the CI)."""
    old = gc.get_threshold()
    gc.set_threshold(10, 1, 1)                           # a collection every few allocations
    gc.collect()
    _Finalized.seen.clear()
    paused = threading.Event()
    go = threading.Event()
    collected_in_worker = []
    try:
        def worker():
            with gc_guard.paused():
                paused.set()
                go.wait(5.0)
                for _ in range(20000):
                    [object() for _ in range(3)]         # allocations that would cross the threshold
                collected_in_worker.append(list(_Finalized.seen))

        thread = threading.Thread(target=worker)
        thread.start()
        assert paused.wait(5.0)
        assert not gc.isenabled()
        _Finalized("made on the main thread")            # cyclic garbage, waiting for a collection
        go.set()
        thread.join()
        assert collected_in_worker == [[]]               # nothing was finalized inside the worker
        # back on from the GUI thread: queued into its event loop when an
        # application runs (re-enabled in the worker, its own exit collected)
        from PySide6.QtCore import QCoreApplication

        if QCoreApplication.instance() is not None:
            QCoreApplication.processEvents()
        assert gc.isenabled()
        gc.collect()                                     # the main thread collects, as it should
        assert _Finalized.seen == ["made on the main thread"]
    finally:
        go.set()
        gc.set_threshold(*old)
        _Finalized.seen.clear()


def test_every_worker_thread_of_the_app_runs_under_the_guard():
    """Every QThread subclass and every QObject moved to a thread runs its
    body under the guard. Found in the source, not
    listed by hand -- the hand list said "the five QThreads" and missed the
    file-open worker (a QObject moved to its thread), whose collections ran
    off the GUI thread."""
    import importlib
    import inspect
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    subclass = re.compile(r"^class (\w+)\(QThread\):", re.M)
    moved = re.compile(r"(\w+) = (\w+)\([^\n]*\)\n\s*\1\.moveToThread\(")
    found = []
    for folder in ("core", "views", "formats", "render"):
        for path in (root / folder).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            names = subclass.findall(text) + [m.group(2) for m in moved.finditer(text)]
            if not names:
                continue
            module = importlib.import_module(
                ".".join(path.relative_to(root).with_suffix("").parts))
            for name in names:
                found.append((module.__name__, getattr(module, name)))
    names = {cls.__name__ for _m, cls in found}
    assert {"RegenWorker", "_AutoSaveWorker", "_OpenWorker", "_CacheWarmer"} <= names
    for module, cls in found:
        source = inspect.getsource(cls.run)
        assert "with gc_guard.paused():" in source, f"{module}.{cls.__name__}"


def test_the_last_worker_hands_the_collector_back_to_the_gui_thread(qapp):
    """Re-enabled from the worker, the collection the GUI thread's
    allocations had piled up ran right there, in the worker's own exit."""
    old = gc.get_threshold()
    gc.set_threshold(10, 1, 1)
    gc.collect()
    _Finalized.seen.clear()
    where = []

    def watch(phase, info):
        if phase == "start":
            where.append(threading.current_thread() is threading.main_thread())

    gc.callbacks.append(watch)
    try:
        def worker():
            with gc_guard.paused():
                _Finalized("made while paused")
            kept = []                                 # the worker's exit allocates,
            for _ in range(2000):                     # and keeps: the count climbs
                kept.append([object()])

        thread = threading.Thread(target=worker)
        gc_guard.start(thread)
        thread.join()
        assert not gc.isenabled() or gc_guard.pauses() == 0
        assert False not in where, "a collection ran on the worker thread"
        qapp.processEvents()                         # the queued re-enable lands
        assert gc.isenabled()
        gc.collect()
        assert _Finalized.seen == ["made while paused"]
    finally:
        gc.callbacks.remove(watch)
        gc.set_threshold(*old)
        _Finalized.seen.clear()


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


def test_a_worker_is_covered_from_its_first_allocation(qapp):
    """The other end of a worker's life: paused only from inside, its first
    allocations -- before the ``with`` -- ran with the collector on, and the
    CI caught a collection on the worker there. gc_guard.start() pauses it
    from the GUI thread before the thread exists."""
    old = gc.get_threshold()
    gc.set_threshold(10, 1, 1)
    gc.collect()
    where = []

    def watch(phase, info):
        if phase == "start":
            where.append(threading.current_thread() is threading.main_thread())

    gc.callbacks.append(watch)
    try:
        def worker():
            kept = [[object()] for _ in range(2000)]   # before its pause
            with gc_guard.paused():
                kept.append([object()])

        thread = threading.Thread(target=worker)
        gc_guard.start(thread)
        thread.join()
        assert False not in where, "a collection ran on the worker thread"
        qapp.processEvents()
        assert gc.isenabled() and gc_guard.pauses() == 0
    finally:
        gc.callbacks.remove(watch)
        gc.set_threshold(*old)


def test_every_worker_is_started_through_the_guard():
    """A bare .start() on a worker leaves its first allocations uncovered."""
    root = Path(__file__).resolve().parent.parent
    bare = re.compile(r"\b(\w*(?:worker|warmer|thread)\w*)\.start\(\)", re.I)
    found = []
    for folder in ("core", "views", "formats", "render", "plugins"):
        for path in (root / folder).rglob("*.py"):
            if path.name == "gc_guard.py":
                continue                       # the one place that may
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if bare.search(line):
                    found.append(f"{path.relative_to(root)}:{n}: {line.strip()}")
    assert not found, "start these with gc_guard.start():\n" + "\n".join(found)
