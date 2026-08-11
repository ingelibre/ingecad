# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Smoke tests: the app constructs headless and the i18n engine resolves."""
from __future__ import annotations

import pytest

from core import i18n


def test_tr_falls_back_to_english_source():
    i18n.set_language("en")
    assert i18n.tr("File") == "File"
    assert i18n.tr("No such key 123") == "No such key 123"


def test_tr_spanish_catalog_loads():
    i18n.set_language("es")
    try:
        assert i18n.tr("File") == "Archivo"
        out = i18n.tr("Cannot open {name}: {error}", name="plano.dxf", error="x")
        assert out == "No se puede abrir plano.dxf: x"
    finally:
        i18n.set_language("en")


def test_main_window_constructs_offscreen(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    qapp.processEvents()
    assert win.viewport is win.centralWidget()
    # The view transform tracked the widget size.
    assert win.viewport.view.width > 100
    assert win.viewport.view.height > 100
    # Cursor readout wiring.
    win.viewport.cursorMoved.emit(12.3456, -7.8901)
    qapp.processEvents()
    assert "12.3456" in win._coords_label.text()
    win.close()


def test_language_switch_retranslates_menus(qapp):
    from views.main_window import MainWindow

    i18n.set_language("en")
    win = MainWindow()
    try:
        menus = [a.text() for a in win._menu_bar.actions()]
        assert "File" in menus and "Tools" in menus

        win._set_language("es")
        menus = [a.text() for a in win._menu_bar.actions()]
        assert "Archivo" in menus and "Herramientas" in menus
        assert win.windowTitle() == "IngeCAD — Sin nombre"
    finally:
        i18n.set_language("en")
        win.close()


def test_open_path_loads_async(qapp, tmp_path):
    import time
    from pathlib import Path

    import ezdxf

    from views.main_window import MainWindow

    doc = ezdxf.new("R2018")
    doc.modelspace().add_line((0, 0), (10, 10))
    path = tmp_path / "plan.dxf"
    doc.saveas(path)

    win = MainWindow()
    win.open_path(Path(path))
    deadline = time.monotonic() + 15.0
    while win.document is None and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    assert win.document is not None
    assert win.windowTitle() == "IngeCAD — plan.dxf"
    assert win.viewport._scene is not None and not win.viewport._scene.is_empty
    win.close()


def test_frontend_config_caps_hatch_density():
    from render.backend import HATCHING_TIMEOUT, frontend_config

    cfg = frontend_config(0.2)
    assert cfg.max_flattening_distance == 0.2
    assert cfg.min_hatch_line_distance == pytest.approx(0.2 / 64.0)
    assert cfg.hatching_timeout == HATCHING_TIMEOUT


def test_typed_alias_wins_over_inline_completion(qapp):
    # "l" + Enter must run LINE via the alias — the inline suggestion (a
    # trailing selection like "lAYER") must not hijack the submit.
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    qapp.processEvents()
    submitted = []
    win.command_line.submitted.connect(submitted.append)

    QTest.keyClicks(win.command_line.input, "l")
    qapp.processEvents()
    QTest.keyClick(win.command_line.input, Qt.Key_Return)
    assert submitted and submitted[-1].strip().lower() == "l"
    assert win.tools.active() and win.tools.tool.name == "LINE"
    win.tools.cancel()
    win.close()


def test_pan_command_enters_hand_mode(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    qapp.processEvents()
    win.dispatcher.submit("p")               # P = PAN alias
    assert win.viewport._pan_mode
    win._on_prompt_cancelled()               # Esc exits
    assert not win.viewport._pan_mode
    win.close()


def test_toolbar_buttons_start_commands(qapp):
    # Draw and Modify toolbars fire the same commands as typing them.
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    qapp.processEvents()
    draw_names = [a.toolTip() for a in win._draw_toolbar.actions()]
    assert any("LINE" in t for t in draw_names)
    modify_names = [a.toolTip() for a in win._modify_toolbar.actions()]
    assert any("TRIM" in t for t in modify_names)

    win._invoke_command("LINE")
    assert win.tools.active() and win.tools.tool.name == "LINE"
    # a second toolbar command cancels the first and starts the new one
    win._invoke_command("CIRCLE")
    assert win.tools.active() and win.tools.tool.name == "CIRCLE"
    win.tools.cancel()
    win.close()


def test_trim_full_flow_through_controller(qapp):
    # Regression: wants_selection was silently reset by the dataclass
    # __init__, so TRIM never entered its selection phase and Enter killed
    # the tool. This drives the REAL app flow: TR -> Enter (all edges) ->
    # click the span to remove.
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    qapp.processEvents()
    win.dispatcher.submit("l")
    win.tools.on_click(0, 0)
    win.tools.on_click(100, 0)
    win.tools.on_text("")
    win.dispatcher.submit("l")
    win.tools.on_click(50, -20)
    win.tools.on_click(50, 20)
    win.tools.on_text("")

    win.dispatcher.submit("tr")
    assert win.tools._selecting_for is not None    # selection phase active
    win.tools.on_text("")                          # Enter: all edges
    assert win.tools.active()                      # tool survives
    win.tools.on_hover(75, 0.2, 2.0)
    win.tools.on_click(75, 0.2)
    spans = sorted(
        (round(l.dxf.start.x, 1), round(l.dxf.end.x, 1))
        for l in win.document.modelspace().query("LINE")
        if abs(l.dxf.start.y) < 0.1 and abs(l.dxf.end.y) < 0.1
    )
    assert spans == [(0.0, 50.0)]
    win.tools.cancel()
    win.close()


def test_edges_stay_highlighted_during_trim(qapp):
    # Preselect circles -> TR: AutoCAD keeps the cutting edges highlighted
    # to guide the picks; the highlight clears when the command ends.
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    qapp.processEvents()
    win.dispatcher.submit("c")
    win.tools.on_click(0, 0)
    win.tools.on_text("10")
    win.dispatcher.submit("c")
    win.tools.on_click(12, 0)
    win.tools.on_text("10")

    win.tools.on_hover(0, 10, 2.0)
    win.tools.on_click(0, 10)       # pick circle 1 (idle selection)
    win.tools.on_click(12, -10)     # pick circle 2
    assert len(win.tools.selection) == 2
    win.dispatcher.submit("tr")
    assert win.tools.active()
    assert len(win.tools.selection) == 2      # edges stay lit during TRIM
    win.tools.on_click(10.5, 0)               # trim c1's right arc
    assert len(win.tools.selection) == 2      # survivor arc replaces c1
    # the trimmed edge keeps cutting: trim c2's left arc against the arc
    win.tools.on_click(1.5, 0)
    assert len(win.document.modelspace().query("ARC")) == 2
    assert len(win.document.modelspace().query("CIRCLE")) == 0
    win.tools.on_text("")                     # Enter ends
    assert not win.tools.selection            # highlight off after command
    win.close()


def test_trim_by_crossing_window(qapp):
    # TRIM targets can be captured with a window/crossing rectangle: two
    # parallel lines crossing a cutter, one crossing rect trims both spans.
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    qapp.processEvents()
    for y in (0.0, 5.0):
        win.dispatcher.submit("l")
        win.tools.on_click(0, y)
        win.tools.on_click(100, y)
        win.tools.on_text("")
    win.dispatcher.submit("l")          # vertical cutter at x=50
    win.tools.on_click(50, -10)
    win.tools.on_click(50, 15)
    win.tools.on_text("")

    win.dispatcher.submit("tr")
    win.tools.on_text("")               # all edges
    win.tools.on_hover(75, 2.5, 2.0)
    # crossing rect (right-to-left) over the right spans of both lines
    win.tools.start_window(90.0, 7.0)
    win.tools.on_click(60.0, -2.0)      # release to the LEFT: crossing
    spans = sorted(
        (round(l.dxf.start.x, 1), round(l.dxf.end.x, 1), round(l.dxf.start.y, 1))
        for l in win.document.modelspace().query("LINE")
        if l.dxf.start.y == l.dxf.end.y
    )
    assert spans == [(0.0, 50.0, 0.0), (0.0, 50.0, 5.0)]
    win.tools.cancel()
    win.close()


def test_extend_by_rect_both_directions(qapp):
    # EXTEND targets by rectangle: quick-mode semantics, BOTH drag
    # directions act as crossing (whatever the rect touches extends).
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    qapp.processEvents()
    for y in (0.0, 5.0):
        win.dispatcher.submit("l")
        win.tools.on_click(0, y)
        win.tools.on_click(40, y)
        win.tools.on_text("")
    win.dispatcher.submit("l")
    win.tools.on_click(100, -10)
    win.tools.on_click(100, 15)
    win.tools.on_text("")

    win.dispatcher.submit("ex")
    win.tools.on_text("")
    win.tools.on_hover(38, 2.5, 2.0)
    win.tools.start_window(30.0, -2.0)
    win.tools.on_click(45.0, 7.0)       # LEFT-to-RIGHT drag: still crossing
    ends = sorted(round(l.dxf.end.x, 1)
                  for l in win.document.modelspace().query("LINE")
                  if l.dxf.start.y == l.dxf.end.y)
    assert ends == [100.0, 100.0]
    win.tools.cancel()
    win.close()


def test_zoom_extents_frames_placeholder_bounds(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    qapp.processEvents()
    win.viewport.zoom_extents()
    v = win.viewport.view
    for wx, wy in [(-50.0, -50.0), (50.0, 50.0)]:
        sx, sy = v.world_to_screen(wx, wy)
        assert 0 <= sx <= v.width and 0 <= sy <= v.height
    win.close()


def test_polyline_midgrip_moves_segment(qapp):
    # AutoCAD/BricsCAD: the midpoint (triangle) grip MOVES the whole segment,
    # it never inserts a vertex — vertex count stays constant no matter how
    # many frames the live follow runs.
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    qapp.processEvents()
    win.dispatcher.submit("pl")
    for p in ((0, 0), (10, 0), (10, 10)):
        win.tools.on_click(*p)
    win.tools.on_text("")           # Enter ends PLINE
    win.regen_in_memory()

    pl = win.document.modelspace().query("LWPOLYLINE")[0]
    win.tools.selection = {pl.dxf.handle}
    grips = win.tools.grip_points()
    # the midpoint of segment 0 (between (0,0) and (10,0)) at (5,0)
    mid = next(g for g in grips if g[2] == "mid" and abs(g[0] - 5) < 0.1)
    win.tools.begin_grip_drag(mid)
    for tgt in ((5, -4), (5, -6), (6, -8)):         # live follow, many frames
        win.tools.update_grip_drag(*tgt)
    win.tools.finish_grip_drag(6, -8)
    pts = list(win.document.modelspace().query("LWPOLYLINE")[0].get_points("xy"))
    assert len(pts) == 3                            # NO vertex inserted
    # segment 0's endpoints both moved down; the third vertex stayed
    assert round(pts[0][1], 1) == -8.0 and round(pts[1][1], 1) == -8.0
    assert (round(pts[2][0]), round(pts[2][1])) == (10, 10)
    win.close()


def test_progress_replaces_the_coordinates_instead_of_overlapping(qapp):
    """The status bar must never hold two texts in the same pixels.

    A drawing opened from the command line (double-clicked .dwg) used to post
    "Opening X..." as a status bar message before the window was shown.
    QStatusBar hides the widgets under a message only if they are visible when
    it arrives, so the readout came back on show() and the two texts were
    painted on top of each other, both illegible.
    """
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    qapp.processEvents()

    win._set_busy("Opening sedapar.dwg...")
    assert win._coords_label.text() == "Opening sedapar.dwg..."
    # A cursor move must not overwrite the progress line.
    win.viewport.cursorMoved.emit(1.0, 2.0)
    qapp.processEvents()
    assert win._coords_label.text() == "Opening sedapar.dwg..."
    # No competing status bar message while busy.
    assert win.statusBar().currentMessage() == ""

    win._set_busy("")
    win.viewport.cursorMoved.emit(1.0, 2.0)
    qapp.processEvents()
    assert win._coords_label.text() == "1.0000, 2.0000"


def test_argv_drawing_opens_after_the_window_is_shown():
    """main() must show the window before opening argv[1], not after.

    The wait for a big drawing has to be visible, and posting a status
    message before show() is what put two texts in the coordinate slot.
    """
    import inspect

    import main as entry

    src = inspect.getsource(entry.main)
    assert src.index("window.show()") < src.index("window.open_path(doc)")


def test_the_coordinate_slot_is_never_taken_by_a_notice():
    """Notices go to the command line; the status bar keeps the readout.

    QStatusBar hides the coordinate label for as long as a temporary message
    shows, so a five-second "Saved x" costs five seconds of the readout. The
    only writer of that slot is _set_busy.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    offenders = []
    for name in ("views/main_window.py", "views/print_dialog.py"):
        for n, line in enumerate(
                (root / name).read_text(encoding="utf-8").splitlines(), 1):
            if "showMessage" in line and not line.lstrip().startswith("#"):
                offenders.append(f"{name}:{n}")
    assert offenders == [], f"use command_line.echo instead: {offenders}"


def test_app_root_follows_the_bundle(monkeypatch):
    """Frozen builds read their data from sys._MEIPASS, not from __file__.

    A PyInstaller bundle synthesises __file__ for modules inside the archive, so
    every path derived from it points at somewhere that does not exist — the
    shaders, the translations and the DWG converters all silently go missing,
    and the app starts anyway and fails on the first drawing.
    """
    from pathlib import Path

    from core import paths

    repo = paths.app_root()
    assert (repo / "resources" / "shaders" / "line.vert").is_file()
    assert paths.is_frozen() is False

    monkeypatch.setattr(paths.sys, "_MEIPASS", "/nowhere/bundle", raising=False)
    assert paths.app_root() == Path("/nowhere/bundle")


def test_self_check_passes_on_this_checkout():
    """main.py --check is what CI asserts on after building the AppImage.

    ``vendor/`` is gitignored, so a fresh clone legitimately has no DWG
    converters until ``tools/libredwg-patches/build-vendor.sh`` runs. There
    the check is expected to report exactly those two as missing and nothing
    else — the rest of the path resolution must still be perfect.
    """
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [sys.executable, str(root / "main.py"), "--check"],
        capture_output=True, text=True, cwd=root, timeout=120,
    )
    out = proc.stdout
    assert "MISSING" not in out.replace("dwg2dxf       : MISSING", "")\
                              .replace("dxf2dwg       : MISSING", ""), out
    if "vendor/libredwg" not in out:            # converters not built yet
        assert proc.returncode == 1, out
        assert "NOT OK — missing: dwg2dxf, dxf2dwg" in out, out
        return
    assert proc.returncode == 0, out + proc.stderr
    assert "OK" in out
    # The converters must be the ones IngeCAD ships, not whatever is on PATH.
    assert "(bundled)" in out, out


def test_menu_entries_carry_icons(qapp):
    """File/Edit/View/Insert/Format entries show icons (Marco's request)."""
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        expected = {
            "File": ["New", "Open...", "Save As...", "Page Setup...",
                     "Plot..."],
            "Edit": ["Undo", "Redo", "Cut", "Copy", "Paste", "Delete",
                     "Erase", "Move"],
            "View": ["Zoom Extents", "Zoom Window", "Pan", "Regenerate",
                     "Layers panel"],
            "Insert": ["Block...", "Create Block..."],
            "Format": ["Layers...", "Linetype...", "Text Style...",
                       "Dimension Style..."],
        }
        # NOTE: never keep QMenu wrappers across statements — shiboken
        # invalidates duplicated wrappers (the C++ menus stay alive, held
        # by win._menus). Fetch actions in a single expression instead.
        def menu_actions(title):
            for a in win._menu_bar.actions():
                if a.text() == title:
                    return {x.text(): x for x in a.menu().actions()}
            return {}

        for menu_name, labels in expected.items():
            actions = menu_actions(menu_name)
            for label in labels:
                assert label in actions, f"{menu_name} > {label} missing"
                assert not actions[label].icon().isNull(), \
                    f"{menu_name} > {label} has no icon"
    finally:
        win.close()


def test_ctrl_z_and_ctrl_y_really_undo_and_redo(qapp):
    """Sends the actual keystrokes, not the slots.

    Ctrl+Y used to be bound TWICE — once as QKeySequence.Redo (which is
    Ctrl+Y on Linux) and once as a separate QShortcut — and Qt fires
    neither handler for an ambiguous shortcut, so AutoCAD's redo key did
    nothing while every "is it bound?" check passed.
    """
    from PySide6.QtGui import QKeySequence
    from PySide6.QtTest import QTest

    from views.main_window import MainWindow

    win = MainWindow()
    win.new_document()
    win.show()
    qapp.processEvents()
    try:
        count = lambda: len(list(win.document.modelspace()))
        win.dispatcher.submit("LINE")
        win.tools.tool.on_point((0, 0))
        win.tools.tool.on_point((10, 0))
        win.tools.tool.on_point((10, 10))
        win.tools.tool.on_enter()
        assert count() == 2

        win.viewport.setFocus()
        qapp.processEvents()
        QTest.keySequence(win, QKeySequence(QKeySequence.Undo))
        qapp.processEvents()
        assert count() == 1, "Ctrl+Z did not undo"

        QTest.keySequence(win, QKeySequence("Ctrl+Y"))
        qapp.processEvents()
        assert count() == 2, "Ctrl+Y did not redo (ambiguous shortcut?)"

        # The platform's own redo key must keep working where it differs.
        QTest.keySequence(win, QKeySequence(QKeySequence.Undo))
        qapp.processEvents()
        QTest.keySequence(win, QKeySequence(QKeySequence.Redo))
        qapp.processEvents()
        assert count() == 2
    finally:
        win.close()
