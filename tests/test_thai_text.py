# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Thai text shaping, font fallback and tone mark positioning tests.

Verifies that:
1. Thai fallback font is resolved when the current font lacks Thai glyphs.
2. Thai combining characters (upper/lower vowels, tone marks) have 0 advance width.
3. Tone marks are elevated to Level 2 when an upper vowel is present.
4. Ascender consonants (ป, ฝ, ฟ, ฬ) shift upper diacritics slightly to the left.
5. SARA AM normalization correctly separates the Nikhahit circle and tone mark.
6. Text length calculation excludes zero-width combining characters.
"""
from __future__ import annotations

import pytest
from ezdxf.fonts import fonts
from ezdxf.fonts.ttfonts import TTFontRenderer

from core import ezdxf_patches


@pytest.fixture(autouse=True)
def setup_patches():
    from ezdxf.addons.drawing import frontend as _frontend
    if not hasattr(_frontend, "is_complex_mtext"):
        _frontend.is_complex_mtext = lambda mtext: False
    ezdxf_patches.apply()


def test_thai_combining_characters_zero_advance_width():
    """Combining marks in Thai must not advance the text cursor."""
    f = fonts.make_font("tahoma.ttf", 10.0)
    # 'ท' alone vs 'ที่' (ท + ี + ่)
    w_base = f.glyph_cache.get_text_length("ท", 10.0)
    w_cluster = f.glyph_cache.get_text_length("ที่", 10.0)
    assert pytest.approx(w_base, rel=1e-4) == w_cluster


def test_thai_tone_mark_elevation():
    """A tone mark over an upper vowel must sit at Level 2 above the vowel."""
    f = fonts.make_font("tahoma.ttf", 10.0)
    paths = f.text_glyph_paths("ที่", 10.0)
    # paths: [ท, ี, ่]
    assert len(paths) == 3
    base_box = paths[0].bbox()
    vowel_box = paths[1].bbox()
    tone_box = paths[2].bbox()

    # Vowel is above base consonant
    assert vowel_box.extmin[1] > base_box.extmin[1]
    # Tone mark is elevated above vowel extmin
    assert tone_box.extmin[1] >= vowel_box.extmax[1] - 0.5


def test_thai_ascender_consonant_shift():
    """Upper vowel on ป must be shifted left to avoid colliding with the tall ascender."""
    f = fonts.make_font("tahoma.ttf", 10.0)
    paths_ba = f.text_glyph_paths("บี", 10.0)
    paths_pa = f.text_glyph_paths("ปี", 10.0)
    assert len(paths_ba) == 2
    assert len(paths_pa) == 2

    # Vowel on ป is shifted left relative to the cursor
    vowel_ba_x = paths_ba[1].bbox().extmin[0]
    vowel_pa_x = paths_pa[1].bbox().extmin[0]
    assert vowel_pa_x < vowel_ba_x


def test_thai_sara_am_normalization():
    """น้ำ (น + ้ + ำ) decomposes so the tone mark sits above the Nikhahit circle."""
    f = fonts.make_font("tahoma.ttf", 10.0)
    paths = f.text_glyph_paths("น้ำ", 10.0)
    # Should decompose into [น, ํ, ้, า]
    assert len(paths) == 4
    circle_box = paths[1].bbox()
    tone_box = paths[2].bbox()
    # Tone mark must be elevated above the circle
    assert tone_box.extmin[1] > circle_box.extmin[1]


def test_thai_fallback_font_on_arial():
    """Arial has no Thai glyphs; rendering Thai text must use Thai font fallback without error."""
    f = fonts.make_font("arial.ttf", 10.0)
    paths = f.text_glyph_paths("ห้องนอน 1", 10.0)
    assert len(paths) >= 7
    # Thai glyphs have valid bounding boxes
    for p in paths:
        assert p.bbox().extmax[0] >= p.bbox().extmin[0]


def test_thai_fallback_font_sentinel_cached(monkeypatch):
    """When no Thai font is found, the sentinel is cached to avoid repeated scanning."""
    monkeypatch.setattr(ezdxf_patches, "_THAI_FALLBACK_FONT", None)
    monkeypatch.setattr(fonts.font_manager, "find_best_match", lambda **kw: None)
    monkeypatch.setattr(fonts, "make_font", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("no font")))

    first = ezdxf_patches._get_thai_fallback_font()
    assert first is None
    assert ezdxf_patches._THAI_FALLBACK_FONT is ezdxf_patches._NOT_FOUND

    # Subsequent call returns None immediately via the sentinel
    call_count = 0

    def fail_if_called(**kw):
        nonlocal call_count
        call_count += 1
        return None

    monkeypatch.setattr(fonts.font_manager, "find_best_match", fail_if_called)
    second = ezdxf_patches._get_thai_fallback_font()
    assert second is None
    assert call_count == 0


def test_thai_real_text_path_glyph_positions():
    """Through the real drawing frontend, tone mark sits above the upper vowel

    and combining marks have zero advance width.
    """
    import ezdxf
    from ezdxf.addons.drawing.frontend import Frontend
    from ezdxf.addons.drawing.properties import RenderContext
    from ezdxf.addons.drawing.recorder import Recorder

    doc = ezdxf.new()
    msp = doc.modelspace()
    msp.add_text("ทก", dxfattribs={"height": 10.0, "insert": (0.0, 0.0)})
    msp.add_text("ที่ก", dxfattribs={"height": 10.0, "insert": (0.0, 0.0)})

    rec = Recorder()
    fe = Frontend(RenderContext(doc), rec)
    fe.draw_layout(msp)

    assert len(rec.records) >= 2
    paths_alone = rec.records[0].paths
    paths_clustered = rec.records[1].paths

    # 'ทก' -> [ท, ก]
    assert len(paths_alone) == 2
    # 'ที่ก' -> [ท, ี, ่, ก]
    assert len(paths_clustered) == 4

    base_box = paths_clustered[0].bbox()
    vowel_box = paths_clustered[1].bbox()
    tone_box = paths_clustered[2].bbox()
    k_clustered_box = paths_clustered[3].bbox()
    k_alone_box = paths_alone[1].bbox()

    # Upper vowel is above base consonant
    assert vowel_box.extmin[1] > base_box.extmin[1]
    # Tone mark is elevated above upper vowel
    assert tone_box.extmin[1] >= vowel_box.extmax[1] - 0.5

    # Combining characters have zero advance: 'ก' starts at the exact same X
    assert pytest.approx(k_alone_box.extmin[0], rel=1e-4) == k_clustered_box.extmin[0]


def test_thai_real_mtext_path_glyph_positions():
    """MTEXT rendered through the drawing frontend also shapes Thai syllables correctly."""
    import ezdxf
    from ezdxf.addons.drawing.frontend import Frontend
    from ezdxf.addons.drawing.properties import RenderContext
    from ezdxf.addons.drawing.recorder import Recorder

    doc = ezdxf.new()
    msp = doc.modelspace()
    msp.add_mtext("ทก", dxfattribs={"char_height": 10.0, "insert": (0.0, 0.0)})
    msp.add_mtext("ที่ก", dxfattribs={"char_height": 10.0, "insert": (0.0, 0.0)})

    rec = Recorder()
    fe = Frontend(RenderContext(doc), rec)
    fe.draw_layout(msp)

    assert len(rec.records) >= 2
    paths_alone = rec.records[0].paths
    paths_clustered = rec.records[1].paths

    assert len(paths_alone) == 2
    assert len(paths_clustered) == 4

    vowel_box = paths_clustered[1].bbox()
    tone_box = paths_clustered[2].bbox()
    k_clustered_box = paths_clustered[3].bbox()
    k_alone_box = paths_alone[1].bbox()

    assert tone_box.extmin[1] >= vowel_box.extmax[1] - 0.5
    assert pytest.approx(k_alone_box.extmin[0], rel=1e-4) == k_clustered_box.extmin[0]
