# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""One IngeCAD: a drawing opened from the file manager while IngeCAD runs
becomes a tab of the running window.

Found by the author after 0.6.8 shipped: two drawings double-clicked in
the file manager opened in two windows, though IngeCAD has drawing tabs.
The real path: this test's window is the running IngeCAD, and a second
IngeCAD -- main.py, in a process of its own, as the file manager starts
it -- is given two drawings.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import ezdxf
import pytest

ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(sys.platform == "win32",
                                reason="a Unix socket in XDG_RUNTIME_DIR")


def _drawing(tmp_path, name):
    doc = ezdxf.new("R2018")
    doc.modelspace().add_circle((0, 0), 2)
    path = tmp_path / name
    doc.saveas(path)
    return path


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    """A private XDG_RUNTIME_DIR: the socket of a real IngeCAD the user
    has open must not take this test's drawings."""
    directory = tmp_path / "run"
    directory.mkdir()
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(directory))
    monkeypatch.delenv("FLATPAK_ID", raising=False)
    return directory


@pytest.fixture
def win(qapp):
    from views.main_window import MainWindow

    window = MainWindow()
    window.show()
    window.new_document()
    qapp.processEvents()
    yield window
    for session in window.document_sessions():
        session.document.dirty = False
    window.close()


def _names(win):
    return [s.document.name for s in win.document_sessions()]


def _settle(qapp, win, until, timeout=60.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        qapp.processEvents()
        if until() and win._open_thread is None and not win._pending_opens:
            break
        time.sleep(0.01)
    qapp.processEvents()


def test_a_second_ingecad_hands_its_drawings_to_the_running_one(
        qapp, win, runtime, tmp_path):
    import main
    from core import single_instance

    instance = single_instance.claim([])
    assert isinstance(instance, single_instance.InstanceServer)
    instance.set_target(main._open_handed_over)
    try:
        uno, dos = _drawing(tmp_path, "uno.dxf"), _drawing(tmp_path, "dos.dxf")
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        second = subprocess.Popen(
            [sys.executable, str(ROOT / "main.py"), str(uno), str(dos)],
            cwd=str(ROOT), env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _settle(qapp, win, lambda: second.poll() is not None
                and len(_names(win)) == 2)
        if second.poll() is None:
            second.kill()
        assert second.wait(5) == 0, "the second IngeCAD quits at once"
        assert _names(win) == ["uno.dxf", "dos.dxf"], "two tabs, one window"
    finally:
        instance.close()


def test_open_paths_queues_drawings_one_tab_each(qapp, win, tmp_path):
    paths = [_drawing(tmp_path, f"{n}.dxf") for n in ("a", "b", "c")]
    win.open_paths(paths)               # opens run one at a time
    _settle(qapp, win, lambda: len(_names(win)) == 3)
    assert _names(win) == ["a.dxf", "b.dxf", "c.dxf"]


def test_a_crashed_ingecads_socket_is_replaced(qapp, runtime):
    from core import single_instance

    dead = socket.socket(socket.AF_UNIX)
    dead.bind(single_instance.server_name())   # left behind, nobody listens
    dead.close()
    assert Path(single_instance.server_name()).exists()
    instance = single_instance.claim([])
    try:
        assert isinstance(instance, single_instance.InstanceServer)
    finally:
        instance.close()


def test_a_start_from_the_menu_gets_its_own_window(qapp, runtime):
    """Nothing to open while IngeCAD runs: a window of its own, as before
    -- not a program that quits without showing anything."""
    from core import single_instance

    first = single_instance.claim([])
    try:
        assert isinstance(first, single_instance.InstanceServer)
        second = single_instance.claim([])
        assert second is not None
        assert not isinstance(second, single_instance.InstanceServer)
    finally:
        first.close()
