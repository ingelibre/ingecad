# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Options ▸ Display ▸ Display resolution: line smoothing and VIEWRES.

Marco, after the responsiveness work: "veo que disminuyó un poco la calidad
de las líneas... ¿no habría alguna opción para configurar la calidad de los
gráficos sin perder rendimiento?".

The rendering had not in fact changed -- rendering the same view twice from
the SAME build differs by more pixels (1.72%) than old-vs-new does (1.09%),
so the variation is process noise, not a regression. But the underlying
complaint was real and pre-existing: nothing was ever antialiased (measured:
0.1% of the ink was a blended edge pixel), and a 40 cm circle was drawn with
eight segments. Both now have a control, under AutoCAD's own names.
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import QSettings

from render import backend


@pytest.fixture
def clean_viewres():
    settings = QSettings()
    previous = settings.value(backend.SETTING_VIEWRES, None)
    yield settings
    if previous is None:
        settings.remove(backend.SETTING_VIEWRES)
    else:
        settings.setValue(backend.SETTING_VIEWRES, previous)


# -- VIEWRES (p. 2049) ---------------------------------------------------------
def test_viewres_defaults_to_autocads_own_default(clean_viewres):
    clean_viewres.remove(backend.SETTING_VIEWRES)
    assert backend.viewres() == 1000
    assert backend.curve_quality() == pytest.approx(1.0)


@pytest.mark.parametrize("value,factor", [(100, 10.0), (1000, 1.0),
                                          (4000, 0.25), (20000, 0.05)])
def test_a_higher_viewres_means_a_finer_tolerance(clean_viewres, value, factor):
    clean_viewres.setValue(backend.SETTING_VIEWRES, value)
    assert backend.curve_quality() == pytest.approx(factor)


@pytest.mark.parametrize("bad", ["", "abc", 0, -5, 99999, None])
def test_a_nonsense_viewres_falls_back_instead_of_breaking_the_render(
        clean_viewres, bad):
    clean_viewres.setValue(backend.SETTING_VIEWRES, bad)
    assert backend.viewres() == 1000


def test_viewres_actually_changes_the_curve_of_a_circle(clean_viewres):
    """The end that matters: more vectors on the screen, not just a number."""
    from core.document import Document

    doc = Document.new()
    doc.modelspace().add_circle((0, 0), 0.4)
    doc.modelspace().add_line((-50, -50), (50, 50))    # gives the drawing a size

    def vertices():
        scene = backend.build_scene(doc, "Model")
        return len(scene.lines.data)

    clean_viewres.setValue(backend.SETTING_VIEWRES, 100)
    coarse = vertices()
    clean_viewres.setValue(backend.SETTING_VIEWRES, 8000)
    fine = vertices()
    assert fine > coarse * 2, \
        f"raising VIEWRES 80x barely changed the circle ({coarse} -> {fine})"


# -- line smoothing ------------------------------------------------------------
@pytest.mark.parametrize("samples", [0, 4, 8])
def test_the_line_smoothing_setting_reaches_the_surface_format(samples):
    """It has to survive the trip into ``_configure_surface_format``, which
    runs before QApplication exists."""
    from PySide6.QtGui import QSurfaceFormat

    import main as ingecad_main

    settings = QSettings()
    previous = settings.value("display/msaa", None)
    try:
        settings.setValue("display/msaa", samples)
        ingecad_main._configure_surface_format()
        assert QSurfaceFormat.defaultFormat().samples() == samples
    finally:
        if previous is None:
            settings.remove("display/msaa")
        else:
            settings.setValue("display/msaa", previous)
        ingecad_main._configure_surface_format()


def test_the_display_settings_are_read_under_the_application_name():
    """The bug this test exists for: the surface format is fixed BEFORE
    QApplication is built, and it reads QSettings -- so with the
    organization and application names set afterwards, it read an empty
    config in "Unknown Organization" and every display choice was silently
    ignored. VSYNC had been broken this way since it shipped.

    ``main()`` must therefore name the application before configuring the
    format; the names are static setters for exactly this case.
    """
    import inspect

    import main as ingecad_main

    source = inspect.getsource(ingecad_main.main)
    names = source.index("setApplicationName")
    fmt = source.index("_configure_surface_format()")
    assert names < fmt, \
        "the application is named after the surface format reads QSettings"
