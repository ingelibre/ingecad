# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A text style's font family is matched exactly, not by prefix.

ezdxf picked the family by prefix: "Ubuntu" drew in "Ubuntu Mono", "Noto
Sans" in "Noto Sans Sora Sompeng" (GeoCad Yaguarete had to patch it).
The cache here is built by hand, so the test does not depend on the fonts
of the machine that runs it.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from ezdxf.fonts import fonts
from ezdxf.fonts.font_face import FontFace
from ezdxf.fonts.font_manager import CacheEntry

from core import ezdxf_patches


@pytest.fixture
def cache(monkeypatch):
    ezdxf_patches.apply()
    faces = [
        FontFace("UbuntuMono-R.ttf", "Ubuntu Mono", "Regular", 400, 5),
        FontFace("Ubuntu-R.ttf", "Ubuntu", "Regular", 400, 5),
        FontFace("Ubuntu-B.ttf", "Ubuntu", "Bold", 700, 5),
        FontFace("NotoSansSoraSompeng-Regular.ttf", "Noto Sans Sora Sompeng",
                 "Regular", 400, 5),
        FontFace("NotoSans-Regular.ttf", "Noto Sans", "Regular", 400, 5),
    ]
    entries = {f.filename.lower(): CacheEntry(Path("/fonts") / f.filename, f)
               for f in faces}
    store = fonts.font_manager._font_cache
    monkeypatch.setattr(store, "_cache", entries)
    yield


@pytest.mark.parametrize("family,weight,expected", [
    ("Ubuntu", 400, "Ubuntu-R.ttf"),
    ("Ubuntu", 700, "Ubuntu-B.ttf"),
    ("ubuntu", 400, "Ubuntu-R.ttf"),
    ("Noto Sans", 400, "NotoSans-Regular.ttf"),
    ("Ubuntu Mono", 400, "UbuntuMono-R.ttf"),
])
def test_the_family_asked_for_wins_over_a_longer_name(cache, family, weight,
                                                      expected):
    found = fonts.find_best_match(family=family, weight=weight)
    assert found is not None and found.filename == expected
