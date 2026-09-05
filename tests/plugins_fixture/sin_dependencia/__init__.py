# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A plugin that needs a module this interpreter does not have: it must be
listed as unavailable with the reason, and never break the start-up."""
from __future__ import annotations

from core.plugins import PluginSpec


def never(ctx, *args) -> None:
    ctx.echo("this cannot run")


PLUGIN = PluginSpec(
    id="sin_dependencia",
    name="Needs a module",
    requires=("ingecad_no_such_module_xyz",),
    commands={"NEVER": never},
)
