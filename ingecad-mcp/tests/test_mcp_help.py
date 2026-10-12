import importlib.util
import json
import tomllib
from pathlib import Path

path = Path(__file__).resolve().parents[1]/"plugin"/"mcp_help.py"
spec = importlib.util.spec_from_file_location("mcp_help_tests", path)
help_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(help_module)


def test_setup_examples_roundtrip_unicode_and_spaces(tmp_path):
    command = tmp_path/"โปรแกรม AI"/"python.exe"
    command.parent.mkdir()
    command.touch()
    script = tmp_path/"บ้าน 2 ชั้น"/"server.py"
    script.parent.mkdir()
    script.touch()
    connection = {"command": str(command), "args": [str(script)]}
    text = help_module.build_help(connection, True, "current-session")
    assert help_module.connection_ready(connection)
    assert "current-session" in text and "list_sessions" in text
    decoder = json.JSONDecoder()
    first = decoder.raw_decode(text[text.index('{'):])[0]
    assert first["mcpServers"]["ingecad"] == connection
    second_start = text.index('{', text.index("VS Code —"))
    second = decoder.raw_decode(text[second_start:])[0]
    assert second["servers"]["ingecad"]["type"] == "stdio"
    section = text.split("[mcp_servers.ingecad]", 1)[1].split("\n\n", 1)[0]
    assert tomllib.loads("[mcp_servers.ingecad]"+section)["mcp_servers"]["ingecad"] == connection


def test_missing_connector_and_off_status():
    assert "install.py" in help_module.build_help(None, False)
    assert "Start bridge" in help_module.build_help(None, False)
    assert not help_module.connection_ready(None)
    text = help_module.build_help({"command":"Z:/missing/python.exe", "args":["Z:/missing/server.py"]}, False)
    assert "ไม่พบ python.exe" in text
