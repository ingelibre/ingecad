# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Bundled plugins, one folder each (docs/plugins.md).

Every folder here with an ``__init__.py`` that exposes ``PLUGIN`` (a
:class:`core.plugins.PluginSpec`) is discovered at start-up, loaded by
path, and turned on unless the user switched it off in Tools > Plugins.
The core never imports these as a package; this file only keeps the
folder honest for tooling. Folders starting with ``_`` are ignored.
"""
