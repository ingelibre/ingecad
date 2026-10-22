"""Offline post-install dependency and converter checks, without opening a document."""
import json
import site
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
site.addsitedir(str(root/"runtime"/"site-packages"))
sys.path.insert(0, str(root))
from configure import configure
configure(root)
import PySide6.QtWidgets
import ezdxf
import numpy
import PIL.Image
import pyproj
import mcp.server.fastmcp
from formats.dwg_bridge import find_dwg2dxf, find_dxf2dwg

checks = {}
for name, path in [("dwg2dxf", root/"vendor"/"libredwg"/"bin"/"dwg2dxf.exe"), ("dxf2dwg",root/"vendor"/"libredwg"/"bin"/"dxf2dwg.exe")]:
    result = subprocess.run([str(path), "--version"], capture_output=True, timeout=30)
    if result.returncode:
        raise RuntimeError(name+" cannot run")
    checks[name] = result.stdout.decode("utf-8", errors="replace").strip()
checks["python"] = sys.version
checks["qt"] = PySide6.__version__
checks["passed"] = True
(root/"install-check.json").write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding="utf-8")
