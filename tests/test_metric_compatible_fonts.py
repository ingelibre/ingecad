# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Arial on a Linux without Arial is Liberation Sans, and a new drawing's
Standard text style is Arial, as acadiso.dwt's.

The drawing stores a font's name. Without the font ezdxf fell back to
DejaVu Sans Condensed -- wider and heavier -- so a title block filled in
AutoCAD came out bold-looking and overflowing (Rafael's PDFs). Linux's own
answer is the Liberation family, drawn on the Microsoft fonts' exact widths.
"""
from __future__ import annotations

import ezdxf
import pytest

from core import ezdxf_patches


@pytest.fixture
def no_microsoft_fonts(monkeypatch):
    """The font cache of a clean Linux: no Arial, Times or Courier New."""
    from ezdxf.fonts import fonts

    ezdxf_patches.apply()
    manager = fonts.font_manager
    cache = manager._font_cache
    clean = {k: v for k, v in cache._cache.items()
             if not k.startswith(("arial", "times", "cour"))}
    monkeypatch.setattr(cache, "_cache", clean)
    monkeypatch.setattr(manager, "_match_cache", {})
    glyphs = {k: v for k, v in fonts.TrueTypeFont._glyph_caches.items()
              if not k.startswith(("arial", "times", "cour"))}
    monkeypatch.setattr(fonts.TrueTypeFont, "_glyph_caches", glyphs)
    loaded = {k: v for k, v in manager._loaded_ttf_fonts.items()
              if not str(k).lower().startswith(("arial", "times", "cour"))}
    monkeypatch.setattr(manager, "_loaded_ttf_fonts", loaded)
    if not manager.has_font("LiberationSans-Regular.ttf"):
        pytest.skip("Liberation fonts are not installed here")
    ezdxf_patches.add_metric_compatible_synonyms(manager)
    return manager


TEXT = "Dibujado  Comprob.  Escala 1:50  Sustituido por  Número"


@pytest.fixture(scope="module")
def real_widths():
    """Widths with the REAL Microsoft fonts, measured before they vanish."""
    from ezdxf.fonts import fonts

    ezdxf_patches.apply()
    widths = {}
    for name in ("arial.ttf", "arialbd.ttf", "times.ttf", "cour.ttf"):
        if fonts.font_manager.has_font(name) and \
                not ezdxf_patches.is_twin_standing_in(fonts.font_manager, name):
            widths[name] = fonts.make_font(name, 2.5).text_width(TEXT)
    return widths


@pytest.mark.parametrize("asked,twin", [
    ("arial.ttf", "LiberationSans-Regular.ttf"),
    ("arialbd.ttf", "LiberationSans-Bold.ttf"),
    ("times.ttf", "LiberationSerif-Regular.ttf"),
    ("cour.ttf", "LiberationMono-Regular.ttf"),
])
def test_a_text_style_font_is_drawn_by_its_twin_at_the_original_width(
        real_widths, no_microsoft_fonts, asked, twin):
    from ezdxf.fonts import fonts

    entry = no_microsoft_fonts._font_cache[asked]
    assert entry.file_path.name == twin
    assert entry.font_face.filename == asked, "the asked name is kept"
    width = fonts.make_font(asked, 2.5).text_width(TEXT)
    if asked in real_widths:
        assert width == pytest.approx(real_widths[asked], rel=0.003), (
            f"{asked} via {twin}: {width:.2f} against {real_widths[asked]:.2f}")


def test_an_mtext_font_family_resolves_to_its_metric_twin(no_microsoft_fonts):
    from ezdxf.fonts import fonts

    face = fonts.find_best_match(family="Arial")
    assert face is not None and face.family == "Liberation Sans", face
    assert face.filename == "arial.ttf", "the family answer is not scaled"
    bold = fonts.find_best_match(family="Arial", weight=700)
    assert bold is not None and bold.filename == "arialbd.ttf"


def test_an_installed_arial_answers_for_itself():
    from ezdxf.fonts import fonts

    ezdxf_patches.apply()
    if not fonts.font_manager.has_font("arial.ttf"):
        pytest.skip("Arial is not installed here")
    assert fonts.font_manager.get_font_face("arial.ttf").filename.lower() \
        == "arial.ttf"


def test_a_new_drawings_standard_style_is_arial(tmp_path):
    from core.document import Document

    document = Document.new()
    standard = document.doc.styles.get("Standard")
    assert standard.dxf.font == "arial.ttf"
    assert standard.get_extended_font_data()[0] == "Arial"
    document.doc.saveas(tmp_path / "new.dxf")
    again = ezdxf.readfile(tmp_path / "new.dxf").styles.get("Standard")
    assert again.dxf.font == "arial.ttf"
