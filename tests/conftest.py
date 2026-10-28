# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Shared fixtures: headless Qt for widget tests."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Widget tests run without a display, in CI and locally alike.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Keep QSettings writes (e.g. the language switch) out of the developer's
# real ~/.config — must be set before Qt is first imported.
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="ingecad-tests-")

# Tests import project packages from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _no_modal_close_prompt(monkeypatch):
    """A modal dialog in a headless test is a hang, not a question.

    The unsaved-changes prompt (MainWindow.closeEvent) would block every
    ``win.close()`` on a dirtied document. Default to Discard; the tests
    that exercise the prompt monkeypatch ``QMessageBox.warning`` again
    themselves, which overrides this fixture for that test.
    """
    mod = sys.modules.get("PySide6.QtWidgets")
    if mod is not None:
        monkeypatch.setattr(mod.QMessageBox, "warning",
                            lambda *a, **k: mod.QMessageBox.Discard)
    yield


@pytest.fixture(autouse=True)
def _status_toggles_start_at_defaults():
    """The status-bar toggles are remembered between sessions, so a test that
    presses F8 would leave ORTHO on for every window after it. Each test
    starts from the defaults; the ones about remembering set their own."""
    core = sys.modules.get("PySide6.QtCore")
    if core is not None:
        settings = core.QSettings()
        settings.remove("statusbar")
        settings.remove("display/grid")
        settings.remove("display/lineweight")
    yield


@pytest.fixture(autouse=True)
def _let_closed_windows_go():
    """A closed MainWindow deletes itself (WA_DeleteOnClose), but only when
    the event loop next turns -- and a test that closes its window last
    never turns it, while others never close theirs. Close what is left and
    turn the loop once after each test, so no window lives on into the next
    one: kept alive, they piled up (63 windows, 1 GB after 135 tests) and
    every later processEvents walked them all.
    """
    yield
    widgets = sys.modules.get("PySide6.QtWidgets")
    app = widgets.QApplication.instance() if widgets is not None else None
    if app is None:
        return
    window_module = sys.modules.get("views.main_window")
    if window_module is not None:
        # and the windows a test never closed: closed here, without the
        # unsaved-changes question (no test is asking it any more)
        for w in app.topLevelWidgets():
            if isinstance(w, window_module.MainWindow):
                w.maybe_save_changes = lambda: True
                w.close()
    app.processEvents()
    if window_module is not None:
        # What is still there was never shown (close() deletes only a shown
        # window; the application always shows its own) or was closed
        # outside a running event loop, where deleteLater waits for an
        # exec() that tests never start. Delete those now.
        import shiboken6

        for w in app.topLevelWidgets():
            if isinstance(w, window_module.MainWindow) and shiboken6.isValid(w):
                shiboken6.delete(w)


_EXIT_STATUS = [0]


def pytest_sessionfinish(session, exitstatus):
    _EXIT_STATUS[0] = int(exitstatus)


def pytest_unconfigure(config):
    """Skip interpreter teardown: report, flush, and leave.

    CI failed with "821 passed ... Aborted (core dumped)": every test green,
    then glibc's "double free or corruption" while interpreter shutdown
    destroyed the MainWindows the tests leave open. The crash needs pytest to
    happen: the byte-for-byte same operations and teardown in a bare script
    exit cleanly, and so does the real application -- opened a real plan,
    edited a block, closed, full teardown, exit 0 on offscreen and xcb alike.
    So this is a pytest-environment artifact, not a defect a user can reach.

    (Since 2026-10-09 closed windows are really deleted -- WA_DeleteOnClose
    and _let_closed_windows_go above -- so few are left at exit; the exit
    stays skipped, it costs nothing.)

    Two better-looking fixes were tried and measured worse. Reaping windows
    per test made the double free DETERMINISTIC (and broke the tidy tests'
    stale wrappers); joining threads per test let the leaked windows' regen
    timers fire full rebuilds on every processEvents -- the 7-minute suite
    stopped finishing inside 18. Skipping a teardown nobody needs is smaller
    than both. It lives in unconfigure, not sessionfinish: the terminal
    reporter prints its "N passed" line in a sessionfinish hookWRAPPER whose
    tail runs after every plain impl, so exiting there ate the summary.
    """
    import os
    import sys

    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(_EXIT_STATUS[0])
