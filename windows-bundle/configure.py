"""Generate machine-specific client examples; never edits a user's AI configuration."""
import json
from pathlib import Path


def write_if_changed(path, text):
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def configure(root):
    root = Path(root).resolve()
    connection = {"command": str(root/"runtime"/"python.exe"), "args": [str(root/"mcp_entry.py")]}
    write_if_changed(root/"plugins"/"ingecad_mcp"/"connection.json", json.dumps(connection, ensure_ascii=False, indent=2))
    write_if_changed(root/"MCP-config"/"client-config.json", json.dumps({"mcpServers":{"ingecad":connection}}, ensure_ascii=False, indent=2))
    write_if_changed(root/"MCP-config"/"vscode-mcp.json", json.dumps({"servers":{"ingecad":{"type":"stdio", **connection}}}, ensure_ascii=False, indent=2))
    write_if_changed(root/"MCP-config"/"codex-config.toml", "[mcp_servers.ingecad]\ncommand = "+json.dumps(connection["command"], ensure_ascii=False)+"\nargs = "+json.dumps(connection["args"], ensure_ascii=False)+"\n")
    write_if_changed(root/"MCP-config"/"commands.txt", '\n'.join([
        'claude mcp add --transport stdio --scope user ingecad -- "'+connection["command"]+'" "'+connection["args"][0]+'"',
        'codex mcp add ingecad -- "'+connection["command"]+'" "'+connection["args"][0]+'"', '']))
    return connection


if __name__ == "__main__":
    configure(Path(__file__).resolve().parent)
