# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Thai text shaping, font fallback and tone mark positioning tests.

Verifies that:
1. Thai fallback font is resolved when the current font lacks Thai glyphs (TTF and SHX).
2. Thai combining characters (upper/lower vowels, tone marks) have 0 advance width.
3. Tone marks are elevated to Level 2 (with positive vertical clearance) when an upper vowel is present.
4. Ascender consonants (ป, ฝ, ฟ, ฬ) shift upper diacritics slightly to the left.
5. Descender consonants (ฎ, ฏ) shift lower vowels downward to avoid collisions.
6. SARA AM normalization correctly separates the Nikhahit circle and tone mark (both orders).
7. The tail of Mai Tho (้) aligns with the rightmost edge of the base consonant underneath.
8. Over Sara Am (Nikhahit circle ํ), Mai Tho is centered over the circle.
9. Text length calculation excludes zero-width combining characters.
10. Both TEXT and MTEXT entities shape Thai syllables through the real drawing frontend.
"""
from __future__ import annotations

import pytest
from ezdxf.fonts import fonts
from ezdxf.fonts.ttfonts import TTFontRenderer

from ezdxf.addons.drawing import frontend as _frontend
if not hasattr(_frontend, "is_complex_mtext"):
    _frontend.is_complex_mtext = lambda mtext: False

from core import ezdxf_patches


@pytest.fixture(autouse=True)
def setup_patches():
    ezdxf_patches.apply()


def _has_thai_font() -> bool:
    ezdxf_patches.apply()
    fb = ezdxf_patches._get_thai_fallback_font()
    if fb is not None:
        return True
    try:
        f = fonts.make_font("tahoma.ttf", 1.0)
        return getattr(f, "glyph_cache", None) is not None and 0x0E01 in f.glyph_cache.cmap
    except Exception:
        return False


needs_thai_font = pytest.mark.skipif(
    not _has_thai_font(),
    reason="No Thai font installed on this system",
)


def _thai_font(height: float = 10.0):
    fb = ezdxf_patches._get_thai_fallback_font()
    if fb is not None:
        return fonts.make_font(fb.name, height)
    return fonts.make_font("tahoma.ttf", height)


@needs_thai_font
def test_thai_combining_characters_zero_advance_width():
    """Combining marks in Thai must not advance the text cursor."""
    f = _thai_font(10.0)
    # 'ท' alone vs 'ที่' (ท + ี + ่)
    w_base = f.glyph_cache.get_text_length("ท", 10.0)
    w_cluster = f.glyph_cache.get_text_length("ที่", 10.0)
    assert pytest.approx(w_base, rel=1e-4) == w_cluster


@needs_thai_font
def test_thai_tone_mark_elevation():
    """A tone mark over an upper vowel must sit at Level 2 above the vowel with positive clearance."""
    f = _thai_font(10.0)
    paths = f.text_glyph_paths("ที่", 10.0)
    # paths: [ท, ี, ่]
    assert len(paths) == 3
    base_box = paths[0].bbox()
    vowel_box = paths[1].bbox()
    tone_box = paths[2].bbox()

    # Vowel is above base consonant
    assert vowel_box.extmin[1] > base_box.extmin[1]
    # Tone mark is elevated above vowel extmax with positive clearance (no collision)
    assert tone_box.extmin[1] > vowel_box.extmax[1]


@needs_thai_font
def test_thai_tone_mark_elevation_all_vowels():
    """Tone marks and diacritics must have positive vertical clearance across all upper vowels."""
    f = _thai_font(10.0)
    test_cases = [
        ("ที่", 1, 2),     # สระอี + ไม้เอก
        ("ชี้", 1, 2),     # สระอี + ไม้โท
        ("ซื้อ", 1, 2),    # สระอือ + ไม้โท
        ("หนึ่ง", 2, 3),   # สระอึ + ไม้เอก
        ("กิ่ง", 1, 2),    # สระอิ + ไม้เอก
        ("สิทธิ์", 4, 5),  # สระอิ + การันต์
        ("ชั้น", 1, 2),    # ไม้หันอากาศ + ไม้โท
    ]
    for word, vowel_idx, tone_idx in test_cases:
        paths = f.text_glyph_paths(word, 10.0)
        vowel_top = paths[vowel_idx].bbox().extmax[1]
        tone_bottom = paths[tone_idx].bbox().extmin[1]
        assert tone_bottom > vowel_top, f"{word}: tone bottom {tone_bottom} <= vowel top {vowel_top}"


@needs_thai_font
def test_thai_ascender_consonant_shift():
    """Upper vowel on ป must be shifted left to avoid colliding with the tall ascender."""
    f = _thai_font(10.0)
    paths_ba = f.text_glyph_paths("บี", 10.0)
    paths_pa = f.text_glyph_paths("ปี", 10.0)
    assert len(paths_ba) == 2
    assert len(paths_pa) == 2

    # Vowel on ป is shifted left relative to the cursor
    vowel_ba_x = paths_ba[1].bbox().extmin[0]
    vowel_pa_x = paths_pa[1].bbox().extmin[0]
    assert vowel_pa_x < vowel_ba_x


@needs_thai_font
def test_thai_descender_consonants_lower_vowels():
    """Lower vowels (ุ, ู) on descender consonants (ฎ, ฏ) must be shifted downward."""
    f = _thai_font(10.0)
    paths_du = f.text_glyph_paths("ดุ", 10.0)
    paths_da = f.text_glyph_paths("ฎุ", 10.0)
    assert len(paths_du) == 2
    assert len(paths_da) == 2

    vowel_du_y = paths_du[1].bbox().extmin[1]
    vowel_da_y = paths_da[1].bbox().extmin[1]
    assert vowel_da_y < vowel_du_y


@needs_thai_font
def test_thai_sara_am_normalization():
    """น้ำ (น + ้ + ำ) decomposes so the tone mark sits above the Nikhahit circle."""
    f = _thai_font(10.0)
    paths = f.text_glyph_paths("น้ำ", 10.0)
    # Should decompose into [น, ํ, ้, า]
    assert len(paths) == 4
    circle_box = paths[1].bbox()
    tone_box = paths[2].bbox()
    # Tone mark must be elevated above the circle
    assert tone_box.extmin[1] > circle_box.extmin[1]


@needs_thai_font
def test_thai_sara_am_reversed_input_normalization():
    """Reversed typing (น + ำ + ้) normalizes to [น, ํ, ้, า] with tone elevated."""
    f = _thai_font(10.0)
    paths = f.text_glyph_paths("น\u0e33\u0e49", 10.0)
    assert len(paths) == 4
    circle_box = paths[1].bbox()
    tone_box = paths[2].bbox()
    assert tone_box.extmin[1] > circle_box.extmin[1]


@needs_thai_font
def test_thai_mai_tho_right_alignment():
    """The tail (rightmost edge) of Mai Tho must align with the rightmost edge of the base consonant."""
    f = _thai_font(10.0)
    for w in ("บ้าน", "ไม้", "ห้อง", "ฝ้า", "ช้าง", "พื้น"):
        paths = f.text_glyph_paths(w, 10.0)
        base_idx = 0 if w[0] not in ("ไ", "เ", "แ") else 1
        tho_idx = next(i for i, ch in enumerate(w) if ch == "\u0e49")
        base_box = paths[base_idx].bbox()
        tho_box = paths[tho_idx].bbox()
        assert pytest.approx(tho_box.extmax[0], abs=0.05) == base_box.extmax[0]


@needs_thai_font
def test_thai_mai_tho_centered_over_sara_am():
    """Over Sara Am (Nikhahit circle), Mai Tho must be centered over the circle."""
    f = _thai_font(10.0)
    for w in ("น้ำ", "ช้ำ", "ถ้ำ", "น\u0e33\u0e49"):
        paths = f.text_glyph_paths(w, 10.0)
        # Decomposed [base, ํ, ้, า]
        assert len(paths) == 4
        circle_box = paths[1].bbox()
        tho_box = paths[2].bbox()
        circle_c = (circle_box.extmin[0] + circle_box.extmax[0]) / 2.0
        tho_c = (tho_box.extmin[0] + tho_box.extmax[0]) / 2.0
        assert pytest.approx(tho_c, abs=0.05) == circle_c


@needs_thai_font
def test_thai_fallback_font_on_arial():
    """Arial has no Thai glyphs; rendering Thai text must use Thai font fallback without error."""
    f = fonts.make_font("arial.ttf", 10.0)
    paths = f.text_glyph_paths("ห้องนอน 1", 10.0)
    assert len(paths) >= 7
    # Thai glyphs have valid bounding boxes
    for p in paths:
        assert p.bbox().extmax[0] >= p.bbox().extmin[0]


@needs_thai_font
def test_thai_fallback_font_on_shx():
    """SHX font without Thai glyphs falls back to Thai system font via UnifiedTextRenderer."""
    from ezdxf.addons.drawing.unified_text_renderer import UnifiedTextRenderer

    utr = UnifiedTextRenderer()
    shx_face = fonts.FontFace(filename="txt.shx")
    paths = utr.get_text_glyph_paths("สวัสดี", shx_face, 10.0)
    assert len(paths) >= 5
    for p in paths:
        assert p.bbox().extmax[0] >= p.bbox().extmin[0]
    line_w = utr.get_text_line_width("สวัสดี", shx_face, 10.0)
    assert line_w > 0.0


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


@needs_thai_font
def test_thai_text_length_excludes_combining_marks():
    """Length calculation accurately accounts for zero advance width combining marks."""
    f = _thai_font(10.0)
    # The cluster 'ที่' should have the same advance width as 'ท' alone
    len_base = f.glyph_cache.get_text_length("ท", 10.0)
    len_cluster = f.glyph_cache.get_text_length("ที่", 10.0)
    assert pytest.approx(len_base, rel=1e-4) == len_cluster

    # Full sentence length calculation
    sentence = "ห้องนอน 1 พื้นที่ 24.5 ตร.ม."
    total_len = f.glyph_cache.get_text_length(sentence, 10.0)
    assert total_len > 0.0


@needs_thai_font
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
    # Tone mark is elevated above upper vowel with positive clearance
    assert tone_box.extmin[1] > vowel_box.extmax[1]

    # Combining characters have zero advance: 'ก' starts at the exact same X
    assert pytest.approx(k_alone_box.extmin[0], rel=1e-4) == k_clustered_box.extmin[0]


@needs_thai_font
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

    assert tone_box.extmin[1] > vowel_box.extmax[1]
    assert pytest.approx(k_alone_box.extmin[0], rel=1e-4) == k_clustered_box.extmin[0]
