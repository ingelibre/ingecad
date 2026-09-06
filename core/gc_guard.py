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

The cure is small: every worker runs its body under :func:`paused`, which
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


def pauses() -> int:
    """How many workers hold the collector paused right now."""
    return _paused


@contextmanager
def paused():
    """Run a worker's body with automatic garbage collection off."""
    global _paused
    with _lock:
        _paused += 1
        if _paused == 1:
            gc.disable()
    try:
        yield
    finally:
        with _lock:
            _paused -= 1
            if _paused == 0:
                gc.enable()
