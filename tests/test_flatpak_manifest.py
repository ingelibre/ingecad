# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""What the Flatpak sandbox lets IngeCAD see."""
from __future__ import annotations

from pathlib import Path

MANIFEST = Path(__file__).resolve().parents[1] / "packaging/flatpak/org.ingecad.IngeCAD.yml"


def _finish_args() -> list[str]:
    lines = MANIFEST.read_text(encoding="utf-8").splitlines()
    start = lines.index("finish-args:")
    args = []
    for line in lines[start + 1:]:
        if line and not line.startswith(" "):
            break
        line = line.split("#", 1)[0].strip()
        if line.startswith("- "):
            args.append(line[2:].strip())
    return args


def test_external_disks_are_reachable_by_their_real_path():
    """An xref attached from a USB disk was saved as /run/flatpak/doc/...
    (Rafael, reviews 6 and 7): the sandbox must see where disks mount."""
    args = _finish_args()
    for where in ("home", "/media", "/run/media"):
        assert f"--filesystem={where}" in args, where
