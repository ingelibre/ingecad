# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Automatic save and crash recovery.

Marco: "¿qué pasa si estoy haciendo un archivo y por un bug x se me cierra?
No sería bueno implementar algo como tiene AutoCAD en recuperación, claro
pero sin afectar el rendimiento porque guardar capaz lajees el programa."

Both halves are asserted here: that the work survives a crash, and that
saving it does not stop the drawing -- the write happens on a worker and
only starts after the drawing has been still, which is why the one moment
the app can wait almost never arrives.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import ezdxf
import pytest

from core import actions, autosave


@pytest.fixture()
def autosave_dir(tmp_path, monkeypatch):
    """Point SAVEFILEPATH at a temporary folder for the whole test."""
    directory = tmp_path / "autosave"
    directory.mkdir()
    monkeypatch.setattr(autosave, "save_file_path", lambda: directory)
    return directory


def _leave_autosave(directory: Path, drawing: str, pid: int,
                    entities: int = 7, age_s: float = 60.0) -> Path:
    """An .sv$ plus its sidecar, as a crashed session leaves them."""
    stem = f"{Path(drawing).stem}_{pid}"
    sv = directory / (stem + autosave.SUFFIX)
    sv.write_bytes(b"0\nSECTION\n")            # content is not what is tested
    info = directory / (stem + autosave.INFO_SUFFIX)
    info.write_text(json.dumps({
        "drawing": drawing, "saved_at": time.time() - age_s,
        "entities": entities, "pid": pid}), encoding="utf-8")
    return sv


# -- the setting ---------------------------------------------------------------

def test_savetime_defaults_to_autocads_ten_minutes(qapp, monkeypatch):
    from PySide6.QtCore import QSettings

    QSettings().remove("autosave/savetime")
    assert autosave.savetime() == 10
    assert autosave.set_savetime(3) == 3
    assert autosave.savetime() == 3
    assert autosave.set_savetime(0) == 0, "0 has to be allowed: it turns it off"
    assert autosave.set_savetime(9999) == autosave.MAX_SAVETIME
    QSettings().remove("autosave/savetime")


def test_the_recovery_folder_does_not_depend_on_the_application_name(qapp):
    """It used to come from AppLocalDataLocation, which appends whatever the
    app is called at that moment -- in a script with no name, the script's
    own filename. A recovery folder has to be in one place, always."""
    path = autosave.save_file_path()
    assert path.name == "autosave"
    assert path.parent.name == "IngeCAD", path


# -- what a crash leaves -------------------------------------------------------

def test_a_crashed_session_is_offered_back(autosave_dir):
    dead_pid = 999_999            # no such process
    _leave_autosave(autosave_dir, "/planos/Cerco perimetrico.dwg", dead_pid,
                    entities=1234)
    found = autosave.recoverable(autosave_dir)
    assert len(found) == 1
    entry = found[0]
    assert entry["drawing"] == Path("/planos/Cerco perimetrico.dwg")
    assert entry["entities"] == 1234
    assert entry["autosave"].exists()


def test_a_live_session_is_not_offered(autosave_dir):
    """Another IngeCAD window has that file open right now; it is not a
    crash, and offering it would invite two windows onto one drawing."""
    _leave_autosave(autosave_dir, "/planos/Vivo.dwg", os.getpid())
    assert autosave.recoverable(autosave_dir) == []


def test_the_newest_comes_first(autosave_dir):
    _leave_autosave(autosave_dir, "/planos/Viejo.dwg", 999_998, age_s=3600)
    _leave_autosave(autosave_dir, "/planos/Nuevo.dwg", 999_999, age_s=30)
    names = [e["drawing"].name for e in autosave.recoverable(autosave_dir)]
    assert names == ["Nuevo.dwg", "Viejo.dwg"]


def test_forgetting_an_entry_removes_both_files(autosave_dir):
    sv = _leave_autosave(autosave_dir, "/planos/Uno.dwg", 999_999)
    entry = autosave.recoverable(autosave_dir)[0]
    autosave.forget(entry)
    assert not sv.exists()
    assert not Path(str(sv) + ".json").exists()
    assert autosave.recoverable(autosave_dir) == []


# -- through the window --------------------------------------------------------

def _window(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.resize(700, 500)
    win.show()
    win.new_document()
    qapp.processEvents()
    return win


def test_the_drawing_is_written_and_says_what_it_is_a_copy_of(qapp,
                                                              autosave_dir):
    win = _window(qapp)
    try:
        win.document.path = Path("/planos/Detalle.dxf")
        win.tools._execute(actions.add_line((0, 0), (10, 10)))
        win._last_mutation = 0.0            # as if the user had paused
        assert win._autosave_idle(), "a still, dirty drawing is savable"

        win._autosave_tick()
        deadline = time.time() + 30
        while win._autosave_worker is not None and time.time() < deadline:
            qapp.processEvents()

        sv, info = autosave.autosave_paths(win.document.path)
        assert sv.exists(), "no automatic save was written"
        assert ezdxf.readfile(str(sv)).modelspace(), "the copy has no drawing"
        data = json.loads(info.read_text(encoding="utf-8"))
        assert data["drawing"] == "/planos/Detalle.dxf"
        assert data["pid"] == os.getpid()
        assert data["entities"] > 0
    finally:
        win.close()


def test_it_waits_for_a_pause_instead_of_interrupting(qapp, autosave_dir):
    """The gate can make the app wait for the tail of a write. It almost
    never has to, because a save only starts once the drawing has been
    still -- measured on a real plan, an edit landing at the start of a
    write waits 2.3 s, and that is the case this rule removes."""
    win = _window(qapp)
    try:
        win.document.path = Path("/planos/Detalle.dxf")
        win.tools._execute(actions.add_line((0, 0), (1, 1)))   # just now
        assert not win._autosave_idle(), "it saved in the middle of drawing"
        win._last_mutation = time.monotonic() - win.AUTOSAVE_QUIET_S - 1
        assert win._autosave_idle()
    finally:
        win.close()


def test_a_command_in_progress_postpones_the_save(qapp, autosave_dir):
    win = _window(qapp)
    try:
        win.document.path = Path("/planos/Detalle.dxf")
        win.tools._execute(actions.add_line((0, 0), (1, 1)))
        win._last_mutation = 0.0
        win.tools.start_tool("LINE")
        try:
            assert win.tools.active()
            assert not win._autosave_idle(), "saved mid-command"
        finally:
            win.tools.cancel()
        assert win._autosave_idle()
    finally:
        win.close()


def test_a_clean_drawing_is_not_copied_again(qapp, autosave_dir):
    win = _window(qapp)
    try:
        win.document.path = Path("/planos/Detalle.dxf")
        win._last_mutation = 0.0
        assert not win.document.dirty
        assert not win._autosave_idle(), "nothing changed: nothing to save"
    finally:
        win.close()


def test_a_real_save_clears_the_recovery_copy(qapp, autosave_dir, tmp_path):
    """"It is reset and restarted by a manual QSAVE, SAVE, or SAVEAS."""
    win = _window(qapp)
    try:
        target = tmp_path / "Detalle.dxf"
        win.document.path = target
        win.tools._execute(actions.add_line((0, 0), (10, 10)))
        win._last_mutation = 0.0
        win._autosave_tick()
        deadline = time.time() + 30
        while win._autosave_worker is not None and time.time() < deadline:
            qapp.processEvents()
        sv, info = autosave.autosave_paths(target)
        assert sv.exists()

        assert win.save_document() is True
        assert not sv.exists(), "the recovery copy outlived a real save"
        assert not info.exists()
    finally:
        win.close()


def test_closing_the_window_leaves_nothing_to_recover(qapp, autosave_dir):
    """What the recovery list holds is, by definition, what a crash left."""
    win = _window(qapp)
    win.document.path = Path("/planos/Detalle.dxf")
    win.tools._execute(actions.add_line((0, 0), (10, 10)))
    win._last_mutation = 0.0
    win._autosave_tick()
    deadline = time.time() + 30
    while win._autosave_worker is not None and time.time() < deadline:
        qapp.processEvents()
    sv, _info = autosave.autosave_paths(win.document.path)
    assert sv.exists()

    win.close()
    qapp.processEvents()
    assert not sv.exists()


def test_the_recovery_dialog_lists_what_was_left(qapp, autosave_dir):
    from views.recovery_dialog import DrawingRecoveryDialog

    _leave_autosave(autosave_dir, "/planos/Cerco.dwg", 999_999, entities=42)
    entries = autosave.recoverable(autosave_dir)
    dialog = DrawingRecoveryDialog(None, entries)
    try:
        assert dialog.table.rowCount() == 1
        assert dialog.table.item(0, 0).text() == "Cerco.dwg"
        assert dialog.table.item(0, 2).text() == "42"
        assert dialog.chosen() is None, "nothing is opened until asked"
    finally:
        dialog.deleteLater()
