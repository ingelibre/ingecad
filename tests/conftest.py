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
