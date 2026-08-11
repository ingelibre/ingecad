# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Thumbnails for the recent-drawings list.

Two sources, cheapest first:

1. **The DWG's own preview.** A DWG written by AutoCAD carries the image it
   shows in its file browser, and LibreDWG's ``dwgbmp`` lifts it out without
   parsing the drawing — milliseconds even on a 7 MB plan. This is what
   AutoCAD and BricsCAD show, so our list looks like theirs for the same file.
2. **Rendering it ourselves**, for DXF and for the DWGs that carry no
   preview. This one costs a full parse, so it belongs off the UI thread.

Results are cached under the user's cache directory, keyed by path and
modification time (``core.recent.thumbnail_path``).
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from core import recent

THUMB_SIZE = (256, 160)
# The canvas colour, so a thumbnail reads like the drawing does on screen.
BACKGROUND = (30, 33, 38)


def cached(path) -> Path | None:
    """The thumbnail already on disk for this exact version of the file."""
    thumb = recent.thumbnail_path(path)
    return thumb if thumb.exists() else None


def generate(path, size=THUMB_SIZE) -> Path | None:
    """Make (and cache) a thumbnail. Returns None when nothing can be shown."""
    path = Path(path)
    if not path.exists():
        return None
    target = recent.thumbnail_path(path)
    if target.exists():
        return target
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    image = _from_dwg_preview(path, size) or _render(path, size)
    if image is None:
        return None
    return target if image.save(str(target), "PNG") else None


def _from_dwg_preview(path: Path, size):
    """Extract the preview a DWG already carries, via LibreDWG's dwgbmp."""
    if path.suffix.lower() != ".dwg":
        return None
    from formats.dwg_bridge import converter_path

    tool = converter_path("dwgbmp")
    if tool is None:
        return None
    # dwgbmp writes next to its input and picks the extension from the
    # embedded format (PNG, BMP or WMF), so give it a private copy of the
    # file name in a scratch directory and take whatever it produces.
    with tempfile.TemporaryDirectory(prefix="ingecad-thumb-") as tmp:
        work = Path(tmp) / path.name
        try:
            work.symlink_to(path.resolve())
        except OSError:
            return None
        try:
            subprocess.run([str(tool), work.name], cwd=tmp, timeout=20,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           check=False)
        except (OSError, subprocess.SubprocessError):
            return None
        for produced in sorted(Path(tmp).iterdir()):
            if produced.name == path.name:
                continue
            image = _load_scaled(produced, size)
            if image is not None:
                return image
    return None


def _frame(document, scene):
    """Which world rectangle to draw.

    The scene's own bounding rect is right for a healthy drawing — it is
    exactly what was drawn. It is wrong on a file with a corrupt vertex at
    1e21, which stretches it until the plan collapses into a corner (the
    failure Zoom Extents had, for the same reason). So the scene rect is used
    unless it is impossibly large, and only then does the drawing's declared
    $EXTMIN/$EXTMAX rescue the frame.

    Measured the other way round first: preferring the declared extents made
    a real DXF worse, because its $EXTMAX covered a survey area twelve times
    the size of anything actually in model space.
    """
    from PySide6.QtCore import QRectF

    from formats.pdf_out import scene_extents
    from render.backend import _declared_extents

    rect = scene_extents(scene)
    span = max(abs(rect.width()), abs(rect.height()))
    sane = rect.isValid() and span < 1e12
    if sane:
        return rect
    declared = _declared_extents(document)
    if declared is not None:
        x0, y0, x1, y1 = declared
        if x1 > x0 and y1 > y0 and max(x1 - x0, y1 - y0) < 1e12:
            return QRectF(x0, y0, x1 - x0, y1 - y0)
    return rect


def _load_scaled(file: Path, size):
    from PySide6.QtGui import QImage

    image = QImage(str(file))
    if image.isNull():
        return None          # WMF, or a preview we cannot decode
    from PySide6.QtCore import Qt

    return image.scaled(size[0], size[1], Qt.KeepAspectRatio,
                        Qt.SmoothTransformation)


def _render(path: Path, size):
    """Draw the model space ourselves — the fallback, and the DXF path."""
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QImage, QPainter

    from core.document import Document
    from formats.pdf_out import build_graphics_scene, scene_extents

    try:
        if path.suffix.lower() == ".dwg":
            from formats.dwg_bridge import load_dwg

            document = load_dwg(str(path))
        else:
            document = Document.load(path)
        scene = build_graphics_scene(document)
    except Exception:
        return None
    source = _frame(document, scene)
    if source is None or source.isEmpty():
        return None

    image = QImage(size[0], size[1], QImage.Format_RGB32)
    image.fill(QColor(*BACKGROUND))
    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.Antialiasing, True)
        # A hair of margin so the outermost line is not clipped by the frame.
        margin = 0.02 * max(source.width(), source.height())
        source = source.adjusted(-margin, -margin, margin, margin)
        scene.render(painter, QRectF(0, 0, size[0], size[1]), source,
                     Qt.KeepAspectRatio)
    finally:
        painter.end()
    return image
