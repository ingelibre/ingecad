"""Install/update the per-user plugin without editing the IngeCAD application."""
import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ingecad", type=Path, default=Path(os.environ["LOCALAPPDATA"]) / "Programs" / "IngeCAD")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    target = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home()/".config"))) / "IngeCAD" / "plugins" / "ingecad_mcp"
    target.mkdir(parents=True, exist_ok=True)
    for source in (root/"plugin").iterdir():
        if source.suffix not in {".py", ".json"}:
            continue
        shutil.copy2(source, target/source.name)
    python = args.ingecad/".venv"/"Scripts"/"python.exe"
    subprocess.run([str(python), "-c", "from PySide6.QtCore import QSettings; s=QSettings('IngeCAD','IngeCAD'); s.setValue('plugins/ingecad_mcp/enabled',True); s.sync()"], check=True)
    config = {"mcpServers": {"ingecad": {"command": str(root/".venv"/"Scripts"/"python.exe"), "args": [str(root/"server.py")]}}}
    (target/"connection.json").write_text(json.dumps(config["mcpServers"]["ingecad"], ensure_ascii=False, indent=2), encoding="utf-8")
    (root/"client-config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Installed plugin: {target}\nMCP configuration: {root/'client-config.json'}\nRestart IngeCAD to load the new plugin.")


if __name__ == "__main__":
    main()
