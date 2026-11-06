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
