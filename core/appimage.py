# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Desktop integration for the AppImage build.

An AppImage is a single file: it runs from anywhere but shows up nowhere --
no launcher in the applications menu, no icon on the file, .dwg/.dxf not
associated (Rafael's review, 2026-09-10: «las AppImages arrancan bien pero
no traen integración de escritorio»). Tools like AppImageLauncher or Gear
Lever do that job when they are installed; this module does it from inside
the app, on request or on the first run, by writing a ``.desktop`` file and
the icon into the user's XDG data directories, pointing at the AppImage's
own path. Everything is undone by :func:`remove`. Ported from IngeTrazo's
``core/appimage.py`` (2026-09-14), where it answered the same review.

The AppImage runtime exports ``APPIMAGE`` (the file's path) and ``APPDIR``;
their absence means we are not running as one and nothing here applies.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

DESKTOP_NAME = "ingecad.desktop"
ICON_NAME = "ingecad.png"


def appimage_path() -> Optional[Path]:
    """The running AppImage's file, or ``None`` when not running as one."""
    raw = os.environ.get("APPIMAGE", "")
    if not raw:
        return None
    p = Path(raw)
    return p if p.is_file() else None


def data_home() -> Path:
    raw = os.environ.get("XDG_DATA_HOME", "")
    return Path(raw) if raw else Path.home() / ".local" / "share"


def desktop_file() -> Path:
    return data_home() / "applications" / DESKTOP_NAME


def icon_file() -> Path:
    return data_home() / "icons" / "hicolor" / "256x256" / "apps" / ICON_NAME


def is_integrated(appimage: Optional[Path] = None) -> bool:
    """True when our launcher exists and points at this AppImage (a moved
    or renamed file reads as not integrated, so the offer comes back)."""
    f = desktop_file()
    if not f.is_file():
        return False
    if appimage is None:
        return True
    try:
        text = f.read_text(encoding="utf-8")
    except OSError:
        return False
    return str(appimage) in text


def _desktop_entry(appimage: Path) -> str:
    exe = str(appimage).replace('"', '\\"')
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=IngeCAD\n"
        "GenericName=2D CAD\n"
        "GenericName[es]=CAD 2D\n"
        "Comment=View and edit DWG/DXF drawings\n"
        "Comment[es]=Ver y editar planos DWG/DXF\n"
        f'Exec="{exe}" %f\n'
        f'TryExec={exe}\n'
        "Icon=ingecad\n"
        "Terminal=false\n"
        "Categories=Graphics;Engineering;2DGraphics;\n"
        "MimeType=image/vnd.dwg;image/vnd.dxf;\n"
        "StartupWMClass=ingecad\n"
        "X-AppImage-Integrated=true\n"
    )


def integrate(appimage: Path, icon_source: Optional[Path] = None) -> Path:
    """Write the launcher and the icon; returns the ``.desktop`` path.
    ``icon_source`` defaults to the AppDir's root icon."""
    if icon_source is None:
        appdir = os.environ.get("APPDIR", "")
        cand = Path(appdir) / ICON_NAME if appdir else None
        icon_source = cand if cand is not None and cand.is_file() else None
    f = desktop_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(_desktop_entry(appimage), encoding="utf-8")
    try:
        f.chmod(0o755)
    except OSError:
        pass
    if icon_source is not None and icon_source.is_file():
        ic = icon_file()
        ic.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(icon_source, ic)
    _refresh_caches()
    return f


def remove() -> None:
    """Take the launcher and icon away (Help ▸ Remove from the menu)."""
    for p in (desktop_file(), icon_file()):
        try:
            p.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass
    _refresh_caches()


def _refresh_caches() -> None:
    """Best effort: tell the desktop about the new entry and icon."""
    for cmd in (["update-desktop-database", str(desktop_file().parent)],
                ["gtk-update-icon-cache", "-q", "-t", "-f",
                 str(data_home() / "icons" / "hicolor")]):
        try:
            subprocess.run(cmd, check=False, timeout=10,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            pass
