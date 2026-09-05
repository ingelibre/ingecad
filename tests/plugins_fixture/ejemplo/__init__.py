# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The sample plugin: the tutorial of docs/plugins.md and the fixture the
suite activates and deactivates to prove the host is left untouched.

One command (HELLO), one alias (HQ), one interactive tool (ECHOPT), a menu
with a submenu and a separator, a one-button toolbar, a document hook and
a Spanish pack -- every kind of thing a real plugin declares, at the
smallest size that still exercises the path.
"""
from __future__ import annotations

from pathlib import Path

from core.plugins import SEPARATOR, MenuItem, PluginSpec, Submenu, ToolbarItem
from tools.base import Tool

OPENED: list = []          # documents the hook saw, for the tests


class EchoPointTool(Tool):
    """Asks for a point and echoes it -- an interactive tool at its smallest."""

    def start(self) -> None:
        self.name = "ECHOPT"
        self.prompt("Specify a point to echo:")

    def on_point(self, point) -> None:
        self.ctx.echo(f"({point[0]:.3f}, {point[1]:.3f})")
        self.ctx.finish()


def hello(ctx, *args) -> None:
    ctx.echo("Hello from the sample plugin" + (" " + " ".join(args) if args else ""))


def _on_document_open(ctx, document) -> None:
    OPENED.append(document)


PLUGIN = PluginSpec(
    id="ejemplo",
    name="Sample",
    version="0.1",
    description="The tutorial plugin: one command, one tool, one alias, one menu.",
    commands={"HELLO": hello},
    tools={"ECHOPT": EchoPointTool},
    aliases={"HQ": "HELLO"},
    menu=(
        MenuItem("Say hello", "HELLO"),
        SEPARATOR,
        Submenu("Points", (MenuItem("Echo a point", "ECHOPT"),)),
    ),
    toolbar=(ToolbarItem("Say hello", "HELLO"),),
    i18n_dir=Path(__file__).parent / "i18n",
    on_document_open=_on_document_open,
)
