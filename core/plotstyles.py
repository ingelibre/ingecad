# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Plot style tables: colour-dependent .ctb pens for PLOT and PUBLISH (#41).

AutoCAD keeps its tables in a Plot Styles folder and a layout names the one
it plots with (``current_style_sheet``, the Page Setup's "Plot style table
(pen assignments)"). Here the folder is ``~/.config/IngeCAD/PlotStyles``:
the user drops a colleague's .ctb there, and the four tables everyone has
are written into it once, built with ezdxf's own writer, so they can be
inspected or edited like any other -- ``acad.ctb`` (object colours),
``monochrome.ctb`` (all black), ``Grayscale.ctb`` and ``Screening 50%.ctb``.

Reading and applying is ezdxf's :mod:`ezdxf.addons.acadctb` plus the render
context in :mod:`formats.pdf_out`. Named tables (.stb) parse but apply as
"Normal": an entity's named style rides a PLOTSTYLE handle this reader does
not follow yet, so an .stb plots like no table at all -- said so in PLOT.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

BUILTIN = ("acad.ctb", "monochrome.ctb", "Grayscale.ctb", "Screening 50%.ctb")


def folder() -> Path:
    from core.paths import user_config_dir

    return user_config_dir() / "PlotStyles"


def ensure_builtin(where: Optional[Path] = None) -> Path:
    """Write the four standard tables into the folder if they are missing."""
    from ezdxf.addons import acadctb

    where = where or folder()
    where.mkdir(parents=True, exist_ok=True)
    for name in BUILTIN:
        target = where / name
        if target.exists():
            continue
        ctb = acadctb.new_ctb()
        ctb.description = {
            "acad.ctb": "Object colours, object lineweights",
            "monochrome.ctb": "Every colour plots black",
            "Grayscale.ctb": "Colours plot as shades of grey",
            "Screening 50%.ctb": "Object colours at 50% screening",
        }[name]
        for aci in range(1, 256):
            style = ctb[aci]
            if name == "monochrome.ctb":
                style.color = (0, 0, 0)
            elif name == "Grayscale.ctb":
                style.grayscale = True
            elif name == "Screening 50%.ctb":
                style.screen = 50
        _save(ctb, target)
    return where


def _save(table, target: Path) -> None:
    """Write a .ctb ezdxf's own reader can open: its writer packs the
    three header counters as native 8-byte longs (24 bytes), while the
    format -- and its reader -- expect three 4-byte ones after the 48-byte
    magic, the zlib stream starting at byte 60."""
    import io
    import struct
    import zlib

    text = io.StringIO()
    table.write_content(text)
    text.write(chr(0))
    body = zlib.compress(text.getvalue().encode())
    with open(target, "wb") as stream:
        stream.write(b"PIAFILEVERSION_2.0,CTBVER1,compress\r\npmzlibcodec")
        stream.write(struct.pack("<III", zlib.adler32(body),
                                 len(text.getvalue()), len(body)))
        stream.write(body)


def available(where: Optional[Path] = None) -> list[str]:
    """Table file names to offer: the standard four plus whatever the user
    dropped in the folder (.ctb and .stb), sorted, acad.ctb first."""
    where = ensure_builtin(where)
    names = {p.name for p in where.iterdir()
             if p.suffix.lower() in (".ctb", ".stb")}
    names.update(BUILTIN)
    ordered = sorted(names, key=lambda n: (n != "acad.ctb", n.lower()))
    return ordered


def resolve(name: str, where: Optional[Path] = None) -> Optional[Path]:
    """The file for a table name the layout or the user gave, or None.

    A bare name is looked up in the folder (case-insensitively: a DWG from
    Windows says ``MONOCHROME.CTB``); an absolute path is taken as is.
    """
    if not name:
        return None
    candidate = Path(name)
    if candidate.is_absolute():
        return candidate if candidate.is_file() else None
    where = ensure_builtin(where)
    direct = where / candidate.name
    if direct.is_file():
        return direct
    wanted = candidate.name.lower()
    for p in where.iterdir():
        if p.name.lower() == wanted:
            return p
    return None


class PlotStyleTable:
    """A loaded table plus what ezdxf's loader forgets: which colours were
    "use object colour" (its loader overwrites them with the palette)."""

    def __init__(self, path: Path) -> None:
        from ezdxf.addons import acadctb

        self.path = Path(path)
        self.table = acadctb.load(str(self.path))
        self.named = self.path.suffix.lower() == ".stb"
        self.object_color: set[int] = set()
        if not self.named:
            for aci in range(1, 256):
                if self.table[aci].has_object_color():
                    self.object_color.add(aci)

    def style(self, aci: int):
        if self.named or not (0 < aci < 256):
            return None
        return self.table[aci]

    def pen_color(self, aci: int, rgb: tuple[int, int, int]) -> tuple[int, int, int]:
        """The plotted RGB of an entity whose colour index is ``aci`` and
        whose object colour is ``rgb``: the table's explicit colour or the
        object's own, then grayscale and screening."""
        style = self.style(aci)
        if style is None:
            return rgb
        colour = rgb if aci in self.object_color else (style.color or rgb)
        if style.grayscale:
            grey = int(round(0.299 * colour[0] + 0.587 * colour[1] + 0.114 * colour[2]))
            colour = (grey, grey, grey)
        screen = style.screen
        if 0 <= screen < 100:
            f = screen / 100.0
            colour = tuple(int(round(c * f + 255 * (1 - f))) for c in colour)
        return colour


def load(name_or_path: str, where: Optional[Path] = None) -> Optional[PlotStyleTable]:
    path = resolve(name_or_path, where)
    if path is None:
        return None
    try:
        return PlotStyleTable(path)
    except Exception:            # noqa: BLE001 - a broken table plots like none
        return None
