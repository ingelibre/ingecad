# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Templates, the recent list, thumbnails and the startup window."""
from __future__ import annotations

from pathlib import Path

import pytest

from core import recent as recent_mod
from core import templates as templates_mod
from core import units as units_mod


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path, monkeypatch):
    """Never touch the developer's real recent list or thumbnail cache."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    yield


# -- templates -----------------------------------------------------------------

def test_every_template_puts_text_at_two_and_a_half_millimetres_on_paper():
    """The one invariant that matters: annotation is the same size on paper
    whatever unit the drawing is in. Getting this wrong is how a metric
    drawing ends up with text a thousand times too small."""
    for template in templates_mod.BUILTIN_TEMPLATES:
        document = templates_mod.new_document(template.key)
        dimtxt = document.doc.dimstyles.get("ISO-25").dxf.dimtxt
        on_paper = dimtxt * template.unit_in_mm
        assert on_paper == pytest.approx(templates_mod.PAPER_TEXT_MM), template.key


def test_a_template_sets_the_unit_the_drawing_declares():
    document = templates_mod.new_document("m")
    units = units_mod.Units.from_doc(document.doc)
    assert units.insunits == 6 and units.unit_name == "Meters"
    assert document.doc.header["$MEASUREMENT"] == 1

    imperial = templates_mod.new_document("in")
    units = units_mod.Units.from_doc(imperial.doc)
    assert units.insunits == 1
    assert units.lunits == units_mod.ARCHITECTURAL
    assert imperial.doc.header["$MEASUREMENT"] == 0
    # And lengths read as feet and inches.
    assert units.length(15.5) == "1'-3 1/2\""


def test_the_scale_family_follows_the_unit_but_keeps_its_own_scale():
    document = templates_mod.new_document("m")
    acot = document.doc.dimstyles.get("Acot-100").dxf
    iso = document.doc.dimstyles.get("ISO-25").dxf
    assert acot.dimtxt == pytest.approx(iso.dimtxt)   # same unit
    assert acot.dimscale == pytest.approx(100.0)      # its own plot scale


def test_a_metre_drawing_gets_a_linetype_scale_that_shows_dashes():
    """LTSCALE 1 in a metres drawing makes every dashed line look solid."""
    metres = templates_mod.new_document("m")
    millimetres = templates_mod.new_document("mm")
    assert metres.doc.header["$LTSCALE"] == pytest.approx(0.1)
    assert millimetres.doc.header["$LTSCALE"] == pytest.approx(1.0)


def test_an_unknown_template_key_falls_back_instead_of_failing():
    assert templates_mod.by_key("nonsense").key == templates_mod.DEFAULT_TEMPLATE


# -- recent list ---------------------------------------------------------------

def test_recent_keeps_the_newest_first_and_never_duplicates(tmp_path):
    a = tmp_path / "a.dxf"
    b = tmp_path / "b.dxf"
    for path in (a, b):
        path.write_text("x")
    recent_mod.add(a)
    recent_mod.add(b)
    recent_mod.add(a)
    assert [p.name for p in recent_mod.load()] == ["a.dxf", "b.dxf"]


def test_recent_hides_files_that_are_gone_but_does_not_forget_them(tmp_path):
    """A plan on an unplugged memory stick should come back with the stick."""
    path = tmp_path / "usb.dxf"
    path.write_text("x")
    recent_mod.add(path)
    path.unlink()
    assert recent_mod.load() == []
    path.write_text("x")
    assert [p.name for p in recent_mod.load()] == ["usb.dxf"]


def test_recent_is_capped(tmp_path):
    for i in range(recent_mod.MAX_RECENT + 5):
        path = tmp_path / f"p{i}.dxf"
        path.write_text("x")
        recent_mod.add(path)
    assert len(recent_mod.load()) == recent_mod.MAX_RECENT


def test_clearing_empties_the_list(tmp_path):
    path = tmp_path / "a.dxf"
    path.write_text("x")
    recent_mod.add(path)
    recent_mod.clear()
    assert recent_mod.load() == []


def test_the_thumbnail_key_changes_when_the_drawing_changes(tmp_path):
    import os
    import time

    path = tmp_path / "a.dxf"
    path.write_text("x")
    first = recent_mod.thumbnail_path(path)
    time.sleep(0.01)
    os.utime(path, (time.time() + 10, time.time() + 10))
    assert recent_mod.thumbnail_path(path) != first


# -- thumbnails ----------------------------------------------------------------

def test_a_dxf_thumbnail_is_rendered_and_cached(qapp, tmp_path):
    import ezdxf

    from formats import thumbnails

    doc = ezdxf.new("R2018")
    msp = doc.modelspace()
    for i in range(10):
        msp.add_line((0, i), (10, i))
    path = tmp_path / "plan.dxf"
    doc.saveas(path)

    assert thumbnails.cached(path) is None
    made = thumbnails.generate(path, size=(64, 40))
    assert made is not None and made.exists()
    assert thumbnails.cached(path) == made

    from PySide6.QtGui import QImage

    image = QImage(str(made))
    assert not image.isNull() and image.width() == 64
    # It drew something: not a uniform field of background colour.
    colours = {image.pixel(x, y) for x in range(0, 64, 3)
               for y in range(0, 40, 3)}
    assert len(colours) > 1


def test_an_empty_drawing_has_no_thumbnail_rather_than_a_blank_one(qapp, tmp_path):
    import ezdxf

    from formats import thumbnails

    path = tmp_path / "empty.dxf"
    ezdxf.new("R2018").saveas(path)
    assert thumbnails.generate(path, size=(64, 40)) is None


def test_a_missing_file_yields_no_thumbnail(qapp, tmp_path):
    from formats import thumbnails

    assert thumbnails.generate(tmp_path / "nope.dxf") is None


# -- startup window ------------------------------------------------------------

def test_the_startup_window_lists_every_template(qapp):
    from views.startup_dialog import StartupDialog

    dialog = StartupDialog()
    try:
        keys = [dialog.templates.item(i).data(0x0100)
                for i in range(dialog.templates.count())]
        assert keys == [t.key for t in templates_mod.BUILTIN_TEMPLATES]
        assert dialog.selected_template() == templates_mod.DEFAULT_TEMPLATE
    finally:
        dialog.close()


def test_double_clicking_a_template_returns_it_and_is_remembered(qapp):
    from PySide6.QtCore import QSettings

    from views.startup_dialog import SETTING_TEMPLATE, StartupDialog

    dialog = StartupDialog()
    try:
        row = [t.key for t in templates_mod.BUILTIN_TEMPLATES].index("mm")
        dialog._start_template(dialog.templates.item(row))
        assert dialog.choice() == ("new", "mm")
        assert str(QSettings().value(SETTING_TEMPLATE)) == "mm"
    finally:
        dialog.close()


def test_a_recent_drawing_shows_up_in_the_startup_window(qapp, tmp_path):
    import ezdxf

    from views.startup_dialog import StartupDialog

    path = tmp_path / "lote.dxf"
    ezdxf.new("R2018").saveas(path)
    recent_mod.add(path)

    dialog = StartupDialog()
    try:
        names = [dialog.recent.item(i).text()
                 for i in range(dialog.recent.count())]
        assert "lote.dxf" in names
        dialog._open_recent(dialog.recent.item(0))
        action, value = dialog.choice()
        assert action == "open" and Path(value).name == "lote.dxf"
    finally:
        dialog.close()


def test_turning_the_startup_window_off_is_remembered(qapp):
    from views.startup_dialog import StartupDialog, should_show

    dialog = StartupDialog()
    try:
        assert should_show() is True
        dialog.show_again.setChecked(False)
        dialog._save_settings()
        assert should_show() is False
    finally:
        dialog.close()


def test_opening_a_drawing_records_it_and_fills_the_menu(qapp, tmp_path):
    """The recent list is what the startup window and File > Recent read."""
    import time

    import ezdxf

    from views.main_window import MainWindow

    doc = ezdxf.new("R2018")
    doc.modelspace().add_line((0, 0), (10, 10))
    path = tmp_path / "plan.dxf"
    doc.saveas(path)

    win = MainWindow()
    try:
        win.open_path(path)
        deadline = time.monotonic() + 15.0
        while win.document is None and time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(0.01)
        assert win.document is not None
        assert [p.name for p in recent_mod.load()] == ["plan.dxf"]
        labels = [a.text() for a in win._recent_menu.actions()]
        assert "plan.dxf" in labels
    finally:
        win.close()


def test_a_drawing_opened_as_a_template_keeps_no_file_of_its_own(qapp, tmp_path):
    import time

    import ezdxf

    from views.main_window import MainWindow

    doc = ezdxf.new("R2018")
    doc.modelspace().add_circle((0, 0), 5)
    path = tmp_path / "base.dxf"
    doc.saveas(path)

    win = MainWindow()
    try:
        win.new_from_drawing(path)
        deadline = time.monotonic() + 15.0
        while win.document is None and time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(0.01)
        assert win.document is not None
        # Content came across, origin did not: Save must ask for a name.
        assert len(list(win.document.modelspace())) == 1
        assert win.document.path is None
        assert recent_mod.load() == []
    finally:
        win.close()
