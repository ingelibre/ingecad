# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""What the Windows build (#28) needs from code that runs everywhere."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# The application's own code; tools/ holds developer harnesses (corpus
# sweeps, the ODA judge) that never ship.
APP_DIRS = ("core", "views", "formats", "render", "plugins")
# Linux-only by construction: the AppImage desktop integration.
EXEMPT = {"core/appimage.py"}
_SPAWN = re.compile(r"subprocess\.(run|Popen|call|check_call|check_output)\s*\(")


def test_every_program_the_app_runs_hides_its_console():
    """On Windows a console program started from the GUI flashes a black
    terminal window unless it is asked not to: every spawn passes
    quiet_process() (formats.dwg_bridge)."""
    offenders = []
    for folder in APP_DIRS:
        for path in (ROOT / folder).rglob("*.py"):
            rel = path.relative_to(ROOT).as_posix()
            if rel in EXEMPT:
                continue
            text = path.read_text(encoding="utf-8")
            for match in _SPAWN.finditer(text):
                call = text[match.start():text.find(")\n", match.start()) + 1]
                if "quiet_process()" not in call:
                    line = text.count("\n", 0, match.start()) + 1
                    offenders.append(f"{rel}:{line}")
    assert not offenders, offenders


def test_the_guard_would_catch_a_bare_spawn():
    text = 'subprocess.run(["dwg2dxf", "x.dwg"], check=False)\n'
    match = _SPAWN.search(text)
    assert match and "quiet_process()" not in text[match.start():]


def test_converters_are_found_by_their_windows_name(tmp_path, monkeypatch):
    from formats import dwg_bridge

    (tmp_path / "dwg2dxf.exe").write_bytes(b"MZ")
    from core import paths

    monkeypatch.setattr(dwg_bridge, "_VENDOR_BIN", tmp_path)
    monkeypatch.setattr(paths, "on_windows", lambda: True)
    assert dwg_bridge.find_dwg2dxf() == tmp_path / "dwg2dxf.exe"
    assert dwg_bridge.quiet_process() == {"creationflags": 0x08000000}   # CREATE_NO_WINDOW
    monkeypatch.setattr(paths, "on_windows", lambda: False)
    assert dwg_bridge.quiet_process() == {}


def test_one_place_answers_where_the_users_files_live(monkeypatch, tmp_path):
    """Recent drawings, acad.pgp, plot styles and plugins all ask core.paths
    -- four modules used to build ~/.config/IngeCAD each its own way (one
    ignored XDG_CONFIG_HOME) -- and on Windows the answer is %APPDATA%."""
    from core import aliases, paths, plotstyles, plugins, recent

    monkeypatch.setattr(paths, "on_windows", lambda: True)
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    base = tmp_path / "Roaming" / "IngeCAD"
    assert paths.user_config_dir() == base
    assert recent.config_dir() == base
    assert aliases.user_pgp_path() == base / "acad.pgp"
    assert plotstyles.folder() == base / "PlotStyles"
    assert plugins.user_plugins_dir() == base / "plugins"
    assert recent.cache_dir() == tmp_path / "Local" / "IngeCAD" / "cache"


def test_nothing_else_builds_the_config_folder_by_hand():
    offenders = []
    for folder in APP_DIRS:
        for path in (ROOT / folder).rglob("*.py"):
            rel = path.relative_to(ROOT).as_posix()
            if rel in EXEMPT or rel == "core/paths.py":
                continue
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                code = line.split("#", 1)[0]
                if '".config"' in code or "XDG_CONFIG_HOME" in code or '".cache"' in code:
                    offenders.append(f"{rel}:{n}")
    assert not offenders, offenders
