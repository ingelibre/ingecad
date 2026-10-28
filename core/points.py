# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Point style: PDMODE and PDSIZE, as AutoCAD keeps them (#69).

Both live in the header ($PDMODE, $PDSIZE) and apply to every POINT of the
drawing. PDMODE is a shape (0 dot, 1 nothing, 2 plus, 3 cross, 4 tick) plus
an optional circle (32) and/or square (64) around it -- the 20 values the
Point Style dialog offers. PDSIZE > 0 is a size in drawing units; 0 is 5 %
of the view height and a negative value is that percentage (render.backend
.point_size draws it). The symbol is display only: object snaps see the
POINT itself, its NODe.
"""
from __future__ import annotations

from core.commands import CompositeCommand

#: The 20 PDMODE values, in the Point Style dialog's order (rows of five).
MODES = (0, 1, 2, 3, 4, 32, 33, 34, 35, 36, 64, 65, 66, 67, 68,
         96, 97, 98, 99, 100)


def pdmode(doc) -> int:
    try:
        value = int(doc.header.get("$PDMODE", 0))
    except (TypeError, ValueError):
        return 0
    return value if value in MODES else 0


def pdsize(doc) -> float:
    try:
        return float(doc.header.get("$PDSIZE", 0.0))
    except (TypeError, ValueError):
        return 0.0


def set_point_style_command(mode: int | None = None, size: float | None = None):
    """One undo step setting $PDMODE and/or $PDSIZE."""
    from core.attributes import SetHeaderCommand

    members = []
    if mode is not None:
        members.append(SetHeaderCommand("$PDMODE", int(mode), "PDMODE"))
    if size is not None:
        members.append(SetHeaderCommand("$PDSIZE", float(size), "PDSIZE"))
    return CompositeCommand("DDPTYPE", members)


def pdmode_command(document, execute, echo, refresh, args=()):
    """PDMODE: "Enter new value for PDMODE <0>:"."""
    from core.actions import Prompt
    from core.i18n import tr

    def commit(text):
        text = text.strip()
        if not text:
            return None
        try:
            value = int(text)
        except ValueError:
            echo(tr("Requires an integer value."))
            return ask()
        if value not in MODES:
            echo(tr("Invalid point display mode."))
            return ask()
        execute(set_point_style_command(mode=value))
        refresh()
        return None

    def ask():
        return Prompt(tr("Enter new value for PDMODE <{current}>:",
                         current=pdmode(document.doc)), commit)

    return commit(str(args[0])) if args else ask()


def pdsize_command(document, execute, echo, refresh, args=()):
    """PDSIZE: "Enter new value for PDSIZE <0.0000>:"."""
    from core.actions import Prompt
    from core.i18n import tr

    def commit(text):
        text = text.strip()
        if not text:
            return None
        try:
            value = float(text)
        except ValueError:
            echo(tr("Requires a number."))
            return ask()
        execute(set_point_style_command(size=value))
        refresh()
        return None

    def ask():
        return Prompt(tr("Enter new value for PDSIZE <{current}>:",
                         current=f"{pdsize(document.doc):.4f}"), commit)

    return commit(str(args[0])) if args else ask()
