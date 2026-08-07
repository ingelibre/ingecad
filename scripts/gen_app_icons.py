# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Rasterize resources/ingecad.svg into the committed app icons.

    python scripts/gen_app_icons.py

Outputs (all committed, because a clone must be installable without Inkscape):
  * resources/icons/ingecad_<size>.png   ← Linux icon theme + AppImage + web
  * resources/icons/ingecad.ico          ← Windows

The SVG is the single source of truth. After editing it, run this and then
``scripts/gen_doc_icons.py``, which composites ``ingecad_256.png`` as the badge
on the .dwg/.dxf document icons — so the order matters.

Needs Inkscape (SVG render) and ImageMagick (.ico) on PATH. Inkscape and not
librsvg because it is what ``scripts/install-desktop.sh`` prefers, and using two
different rasterizers for the same artwork invites off-by-one differences.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SVG = ROOT / "resources" / "ingecad.svg"
ICONS = ROOT / "resources" / "icons"

SIZES = [16, 24, 32, 48, 64, 128, 256, 512]
# 512 is deliberately out: a .ico carrying it is ~1 MB and Windows never asks
# for more than 256.
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]


def run(*cmd: str) -> None:
    subprocess.run([str(c) for c in cmd], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main() -> int:
    for tool in ("inkscape", "magick"):
        if not shutil.which(tool):
            print(f"!! {tool} is not on PATH", file=sys.stderr)
            return 1
    if not SVG.is_file():
        print(f"!! missing {SVG}", file=sys.stderr)
        return 1

    ICONS.mkdir(parents=True, exist_ok=True)
    for size in SIZES:
        out = ICONS / f"ingecad_{size}.png"
        run("inkscape", "-w", size, "-h", size, SVG, "-o", out)
        print(f"  {out.relative_to(ROOT)}")

    ico = ICONS / "ingecad.ico"
    run("magick", *[ICONS / f"ingecad_{s}.png" for s in ICO_SIZES], ico)
    print(f"  {ico.relative_to(ROOT)}")

    print("\nNow run: python scripts/gen_doc_icons.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
