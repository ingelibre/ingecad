# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""IngeCAD file bridges: the LibreDWG DWG satellite and PDF output.

DWG is never parsed in-process — the bundled patched LibreDWG converts to/from
DXF and ezdxf does the rest (see CLAUDE.md, principle 2). No proprietary
converter is required or used.
"""
