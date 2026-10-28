# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Keep Python's cyclic garbage collector off the worker threads.

CPython runs a collection in whatever thread allocates the object that
crosses the threshold -- the cache warmer, the regen worker, the autosave
thread. When the garbage it finds holds Qt objects made on the GUI thread
(icons, pixmaps, actions caught in a reference cycle), their destructors
run on that worker thread, and Qt forbids destroying GUI objects off the
GUI thread. Measured: one SIGSEGV in five full runs of the suite, and a
reproducer that crashes on its first round (collections forced on every
allocation, icon cycles made on the GUI thread while the warmer walks the
drawing).

The cure is small: every worker is started by :func:`start` and runs its
body under :func:`paused`, which
switches the automatic collector off for as long as any worker is alive
and back on when the last one finishes. The GUI thread's allocations
trigger no collection meanwhile (a bounded pause, seconds at most), and
the collections that do happen all happen on the GUI thread, where Qt
objects may die. Nothing leaks: the collector is only paused, and a
worker that raises restores it on the way out.
"""
from __future__ import annotations

import gc
import threading
from contextlib import contextmanager

_lock = threading.Lock()
_paused = 0
#: Pauses taken by :func:`start` for a worker that has not reached its
#: ``paused()`` yet: the worker takes one over instead of adding its own.
_reserved = 0


def pauses() -> int:
    """How many workers hold the collector paused right now."""
    return _paused


def start(thread) -> None:
    """Start a worker thread with the collector ALREADY paused for it.

    Paused only from inside the worker, the thread's first allocations --
    its bootstrap, the frame of run() before the ``with`` -- still ran
    with the collector on, and one that crossed the threshold collected
    right there, on the worker (the CI caught it: a collection on the
    worker thread before its pause). Taken here, on the GUI thread, the
    pause covers the worker from its first instruction; its own
    ``paused()`` then takes this one over.
    """
    global _paused, _reserved
    with _lock:
        _paused += 1
        _reserved += 1
        if _paused == 1:
            gc.disable()
    thread.start()


@contextmanager
def paused():
    """Run a worker's body with automatic garbage collection off."""
    global _paused, _reserved
    with _lock:
        if _reserved:
            _reserved -= 1                   # the pause start() took for us
        else:
            _paused += 1
            if _paused == 1:
                gc.disable()
    try:
        yield
    finally:
        with _lock:
            _paused -= 1
            last = _paused == 0
        if last:
            _enable_on_gui_thread()


def _enable_now() -> None:
    """Switch the collector back on -- unless a worker started meanwhile."""
    with _lock:
        if _paused == 0:
            gc.enable()


def _enable_on_gui_thread() -> None:
    """The last worker is done: turn the collector back on FROM THE GUI
    THREAD. Enabled from the worker itself, the collection the GUI's
    allocations had piled up meanwhile ran right there, in the worker's own
    exit (measured: thresholds lowered, every worker type collected on its
    way out -- regen, cache warmer, live viewport, file open), the very
    thing this module exists to prevent. Without a running application
    (scripts, headless tests) there is no GUI thread to hand it to."""
    try:
        from PySide6.QtCore import QCoreApplication, QThread, QTimer
    except ImportError:                       # no Qt at all
        _enable_now()
        return
    app = QCoreApplication.instance()
    if app is None or QThread.currentThread() is app.thread():
        _enable_now()
        return
    # queued into the GUI thread's event loop (a zero-delay single shot
    # with a context object runs in that object's thread)
    QTimer.singleShot(0, app, _enable_now)
