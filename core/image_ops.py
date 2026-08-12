# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""IMAGEADJUST and TRANSPARENCY: the write side of image display.

The render already honors brightness/contrast/fade and the transparency
flag (ezdxf's frontend applies them to the pixels at load); these commands
only write the DXF values — with exact undo — and demand the regen that
makes them visible (the incremental overlay cannot re-shade pixels).

Reference: IMAGEADJUST p. 927 (all three 0-100, defaults 50/50/0; fade 100
blends fully into the background) and TRANSPARENCY p. 1964 (background
pixels of bitonal images ON/OFF; ezdxf keys the same flag to the alpha
channel of any image).
"""
from __future__ import annotations

from core.commands import Command
from core.i18n import tr

_ADJUST_ATTRS = ("brightness", "contrast", "fade")


class ImageAdjustCommand(Command):
    needs_regen = True

    def __init__(self, entities: list, brightness=None, contrast=None,
                 fade=None) -> None:
        self.name = tr("image adjust")
        self.entities = [e for e in entities if e.dxftype() == "IMAGE"]
        self._new = {"brightness": brightness, "contrast": contrast,
                     "fade": fade}
        self._old: list[dict] | None = None

    def do(self, document) -> None:
        self._old = []
        for entity in self.entities:
            self._old.append({a: int(entity.dxf.get(a, 50 if a != "fade" else 0))
                              for a in _ADJUST_ATTRS})
            for attr, value in self._new.items():
                if value is not None:
                    setattr(entity.dxf, attr, int(max(0, min(100, value))))
        document.dirty = True

    def undo(self, document) -> None:
        for entity, old in zip(self.entities, self._old or []):
            for attr, value in old.items():
                setattr(entity.dxf, attr, value)
        document.dirty = True


class ImageTransparencyCommand(Command):
    needs_regen = True

    def __init__(self, entities: list, on: bool) -> None:
        self.name = tr("image transparency")
        self.entities = [e for e in entities if e.dxftype() == "IMAGE"]
        self._on = bool(on)
        self._old: list[int] | None = None

    def do(self, document) -> None:
        from ezdxf.entities.image import Image

        self._old = [int(e.dxf.flags) for e in self.entities]
        for entity in self.entities:
            if self._on:
                entity.dxf.flags = entity.dxf.flags | Image.USE_TRANSPARENCY
            else:
                entity.dxf.flags = entity.dxf.flags & ~Image.USE_TRANSPARENCY
        document.dirty = True

    def undo(self, document) -> None:
        for entity, flags in zip(self.entities, self._old or []):
            entity.dxf.flags = flags
        document.dirty = True
