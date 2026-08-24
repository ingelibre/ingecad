# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Where a file dialog opens.

Marco hit this on the Flatpak the day 0.4.2 shipped: File ▸ Open answered
"No se pudo encontrar «/app/ingecad»" instead of showing a chooser. Every
dialog passed "" as its directory, Qt resolved that against the working
directory, and the launcher's working directory was inside the sandbox —
which the portal that actually draws the dialog cannot see.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings

from views import file_dialogs

SOURCE_DIRS = ("views", "tools", "core")


def test_start_dir_is_absolute_and_exists(tmp_path):
    where = Path(file_dialogs.start_dir())
    assert where.is_absolute()
    assert where.is_dir()


def test_start_dir_never_answers_inside_the_sandbox_prefix(monkeypatch):
    """/app is a real directory in the sandbox and a lie to the portal."""
    monkeypatch.setattr(file_dialogs.QSettings, "value",
                        lambda self, key, default=None: "/app/ingecad")
    assert not file_dialogs.start_dir().startswith("/app")


def test_the_document_portal_mount_is_not_a_folder_to_return_to():
    """A file picked outside --filesystem=home arrives at /run/user/N/doc/ID.

    That path opens fine and holds exactly one file, so remembering it as
    "where I was" would strand the next dialog in an empty, vanishing mount.
    """
    assert file_dialogs._usable("/run/user/1000/doc/a1b2c3") is None
    assert file_dialogs._usable("/run/user/1000/doc") is None
    # ...while the runtime directory around it is an ordinary folder. Without
    # this half the test would pass on a guard that rejected all of /run.
    runtime = Path("/run/user") / str(__import__("os").getuid())
    if runtime.is_dir():
        assert file_dialogs._usable(runtime) == runtime.resolve()


def test_preferred_wins_when_it_is_usable(tmp_path):
    assert file_dialogs.start_dir(tmp_path) == str(tmp_path.resolve())


def test_a_file_is_taken_as_its_folder(tmp_path):
    drawing = tmp_path / "plano.dwg"
    drawing.write_text("x")
    assert file_dialogs.start_dir(drawing) == str(tmp_path.resolve())


def test_a_vanished_preferred_falls_through(tmp_path):
    gone = tmp_path / "unplugged-stick" / "plano.dwg"
    where = Path(file_dialogs.start_dir(gone))
    assert where.is_dir() and where != gone


def test_remember_then_start_there(tmp_path, monkeypatch):
    store = {}
    monkeypatch.setattr(file_dialogs.QSettings, "setValue",
                        lambda self, k, v: store.__setitem__(k, v))
    monkeypatch.setattr(file_dialogs.QSettings, "value",
                        lambda self, k, default=None: store.get(k, default))
    drawing = tmp_path / "plano.dwg"
    drawing.write_text("x")
    file_dialogs.remember(drawing)
    assert store[file_dialogs.SETTING_LAST_DIR] == str(tmp_path.resolve())
    assert file_dialogs.start_dir() == str(tmp_path.resolve())


def test_remember_ignores_a_cancelled_dialog(monkeypatch):
    """An empty string is what getOpenFileName returns on Cancel."""
    calls = []
    monkeypatch.setattr(file_dialogs.QSettings, "setValue",
                        lambda self, k, v: calls.append((k, v)))
    file_dialogs.remember("")
    file_dialogs.remember(None)
    assert calls == []


def test_save_dialog_places_a_bare_name_in_a_real_folder(tmp_path, monkeypatch):
    """A bare "plano.pdf" is relative — the same trap as an empty string."""
    seen = {}

    def fake_save(parent, caption, directory, name_filter):
        seen["directory"] = directory
        return "", ""

    monkeypatch.setattr(file_dialogs.QFileDialog, "getSaveFileName", fake_save)
    file_dialogs.get_save_file(None, "Save PDF", "plano.pdf", "PDF (*.pdf)",
                               preferred=tmp_path)
    assert seen["directory"] == str(tmp_path.resolve() / "plano.pdf")
    assert Path(seen["directory"]).is_absolute()


def test_open_dialog_is_given_a_real_directory(tmp_path, monkeypatch):
    seen = {}

    def fake_open(parent, caption, directory, name_filter):
        seen["directory"] = directory
        return "", ""

    monkeypatch.setattr(file_dialogs.QFileDialog, "getOpenFileName", fake_open)
    file_dialogs.get_open_file(None, "Open Drawing", "Drawings (*.dwg)",
                               preferred=tmp_path)
    assert seen["directory"] == str(tmp_path.resolve())


# -- the guard --------------------------------------------------------------

_DIALOG_CALL = re.compile(r"QFileDialog\.get(Open|Save)FileName\s*\(")


def _sources():
    root = Path(__file__).resolve().parent.parent
    for folder in SOURCE_DIRS:
        for path in (root / folder).rglob("*.py"):
            yield path


def test_only_the_helper_calls_qfiledialog_directly():
    """Keep the fix from being undone one dialog at a time.

    Every new dialog must go through views.file_dialogs, which is what
    guarantees an absolute starting directory the host can actually show.
    """
    offenders = [str(p) for p in _sources()
                 if p.name != "file_dialogs.py" and _DIALOG_CALL.search(p.read_text())]
    assert offenders == [], (
        "call views.file_dialogs.get_open_file / get_save_file instead: "
        + ", ".join(offenders))


def test_the_guard_would_catch_a_regression(tmp_path):
    """A test that only ever passes proves nothing — check it can fail."""
    assert _DIALOG_CALL.search('x = QFileDialog.getOpenFileName(self, "t", "", "f")')
    assert _DIALOG_CALL.search("QFileDialog.getSaveFileName(\n  self,")
    assert not _DIALOG_CALL.search("file_dialogs.get_open_file(self, ...)")


def test_the_flatpak_launcher_does_not_work_inside_the_prefix():
    """The other half of the fix, and the one that made it user-visible."""
    root = Path(__file__).resolve().parent.parent
    launcher = root / "packaging" / "flatpak" / "flatpak-launcher.sh"
    if not launcher.exists():
        pytest.skip("flatpak packaging not present")
    text = launcher.read_text()
    assert "cd /app/ingecad" not in text
    assert 'cd "${HOME:-/}"' in text
