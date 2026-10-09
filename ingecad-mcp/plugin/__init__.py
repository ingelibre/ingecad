"""IngeCAD GUI-thread bridge. SPDX-License-Identifier: GPL-3.0-or-later."""
from core.plugins import PluginSpec, MenuItem
from .bridge import start, stop
from .ai_panel import show_panel, document_opened

PLUGIN = PluginSpec(
    id="ingecad_mcp", name="IngeCAD AI + MCP", version="0.3.2",
    description="Native multi-provider AI assistant and local MCP bridge. AI / MCPSTART / MCPSTOP.",
    commands={"AI": show_panel, "MCPSTART": start, "MCPSTOP": stop},
    menu=(MenuItem("AI Assistant", "AI"), MenuItem("Start MCP bridge", "MCPSTART"), MenuItem("Stop MCP bridge", "MCPSTOP")),
    on_document_open=document_opened,
)
