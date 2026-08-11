# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Which object snaps are running — AutoCAD's OSMODE, as a set of modes.

The state is a bitcode in AutoCAD ($OSMODE, documented on p.2436) and it is
kept as one here too, because that is what a drawing and a user's settings
carry: 1 endpoint, 2 midpoint, 4 centre, 8 node, 16 quadrant, 32
intersection, 64 insertion, 128 perpendicular, 256 tangent, 512 nearest,
2048 apparent intersection, 4096 extension, 8192 parallel. Bit 16384 means
"object snap switched off at the status bar", which is how AutoCAD tells a
user who pressed F3 from a user who unticked every box.

Geometric Center is newer than the reference we work from and has no
documented bit there, so it takes the next free one (32768).

Modes that are listed but not yet implemented are marked ``available=False``:
they appear in the menu greyed out with the reason, rather than offering a
tick that does nothing.
"""
from __future__ import annotations

from dataclasses import dataclass

OFF_BIT = 16384          # $OSMODE's "toggled off at the status bar" flag


@dataclass(frozen=True)
class Mode:
    key: str             # what core.snap calls it
    bit: int             # the OSMODE bit
    label: str           # what the menu shows
    available: bool = True
    note: str = ""


MODES: tuple[Mode, ...] = (
    Mode("END", 1, "Endpoint"),
    Mode("MID", 2, "Midpoint"),
    Mode("CEN", 4, "Center"),
    Mode("GCE", 32768, "Geometric Center"),
    Mode("NOD", 8, "Node"),
    Mode("QUA", 16, "Quadrant"),
    Mode("INT", 32, "Intersection"),
    Mode("EXT", 4096, "Extension", False,
         "Extension tracking is not implemented yet."),
    Mode("INS", 64, "Insertion"),
    Mode("PER", 128, "Perpendicular"),
    Mode("TAN", 256, "Tangent"),
    Mode("NEA", 512, "Nearest"),
    Mode("APP", 2048, "Apparent Intersection", False,
         "Apparent intersection is not implemented yet."),
    Mode("PAR", 8192, "Parallel", False,
         "Parallel tracking is not implemented yet."),
)

BY_KEY = {mode.key: mode for mode in MODES}
AVAILABLE = frozenset(mode.key for mode in MODES if mode.available)

# What a fresh install snaps to. AutoCAD ships 4133 (endpoint, centre,
# intersection, extension); ours is the same idea minus the tracking mode we
# do not have, plus midpoint and node, which a drafter turns on immediately.
DEFAULT_BITS = 1 | 2 | 4 | 8 | 32 | 128 | 512


def from_bits(bits: int) -> frozenset[str]:
    """The running modes in a bitcode (the off-flag is not a mode)."""
    return frozenset(mode.key for mode in MODES
                     if mode.available and bits & mode.bit)


def to_bits(keys) -> int:
    wanted = set(keys)
    return sum(mode.bit for mode in MODES if mode.key in wanted)


def is_off(bits: int) -> bool:
    return bool(bits & OFF_BIT)


def with_off(bits: int, off: bool) -> int:
    return (bits | OFF_BIT) if off else (bits & ~OFF_BIT)


def label_of(key: str) -> str:
    mode = BY_KEY.get(key)
    return mode.label if mode else key
