# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""AppImage desktop integration (Rafael's review, 2026-09-10: the AppImages
ran but brought no launcher, no icon), and the store's first impression:
the Flatpak's desktop id and the screenshots GNOME Software shows."""
from __future__ import annotations

import re
from pathlib import Path

from core import appimage


def test_not_an_appimage_without_the_runtime_variables(monkeypatch):
    monkeypatch.delenv("APPIMAGE", raising=False)
    assert appimage.appimage_path() is None


def test_integrate_writes_launcher_and_icon_pointing_at_the_file(tmp_path, monkeypatch):
    img = tmp_path / "IngeCAD-0.6.2-x86_64.AppImage"
    img.write_bytes(b"AI")
    appdir = tmp_path / "AppDir"
    appdir.mkdir()
    (appdir / "ingecad.png").write_bytes(b"\x89PNG")
    data = tmp_path / "data"
    monkeypatch.setenv("APPIMAGE", str(img))
    monkeypatch.setenv("APPDIR", str(appdir))
    monkeypatch.setenv("XDG_DATA_HOME", str(data))
    monkeypatch.setattr(appimage, "_refresh_caches", lambda: None)
    assert appimage.appimage_path() == img
    assert not appimage.is_integrated(img)
    f = appimage.integrate(img)
    assert f == data / "applications" / "ingecad.desktop"
    text = f.read_text()
    assert f'Exec="{img}" %f' in text and f"TryExec={img}" in text
    assert "Icon=ingecad" in text
    assert "image/vnd.dwg" in text and "image/vnd.dxf" in text
    assert (data / "icons/hicolor/256x256/apps/ingecad.png").read_bytes() == b"\x89PNG"
    assert appimage.is_integrated(img)
    # a moved AppImage reads as not integrated (the launcher would be stale)
    assert not appimage.is_integrated(tmp_path / "elsewhere.AppImage")
    appimage.remove()
    assert not f.exists()
    assert not (data / "icons/hicolor/256x256/apps/ingecad.png").exists()


def test_the_help_menu_offers_integration_only_as_an_appimage(qapp, tmp_path, monkeypatch):
    from views.main_window import MainWindow

    monkeypatch.delenv("APPIMAGE", raising=False)
    win = MainWindow()
    try:
        labels = [a.text() for a in win._menu_bar.actions()
                  for a in (a.menu().actions() if a.menu() else [])]
        assert not any("applications menu" in t for t in labels)
    finally:
        win.close()
    img = tmp_path / "IngeCAD.AppImage"
    img.write_bytes(b"AI")
    monkeypatch.setenv("APPIMAGE", str(img))
    win = MainWindow()
    try:
        labels = [a.text() for a in win._menu_bar.actions()
                  for a in (a.menu().actions() if a.menu() else [])]
        assert any(t.startswith("Add to the applications menu") for t in labels)
        assert any(t.startswith("Remove from the applications menu") for t in labels)
    finally:
        win.close()


def test_the_store_page_has_screenshots_served_over_https():
    """GNOME Software showed "No screenshots": the metainfo had none."""
    root = Path(__file__).resolve().parents[1]
    text = (root / "packaging/flatpak/org.ingecad.IngeCAD.metainfo.xml").read_text()
    images = re.findall(r"<image>([^<]+)</image>", text)
    assert len(images) >= 5
    assert all(u.startswith("https://ingecad.org/images/screenshots/") for u in images)
    assert '<screenshot type="default">' in text
    # every screenshot captioned in both languages
    assert text.count("<caption>") == len(images)
    assert text.count('<caption xml:lang="es">') == len(images)


def test_the_window_claims_the_flatpak_app_id_inside_the_sandbox():
    """Inside the Flatpak the desktop entry is the app id; a window claiming
    "ingecad" matched nothing, so the dock showed a generic icon and GNOME
    Software's Open button never saw the app appear."""
    root = Path(__file__).resolve().parents[1]
    text = (root / "main.py").read_text()
    assert 'setDesktopFileName(os.environ.get("FLATPAK_ID") or "ingecad")' in text
