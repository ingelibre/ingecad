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
