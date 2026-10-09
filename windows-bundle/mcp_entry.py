"""MCP stdio bootstrap; stdout is reserved for protocol messages."""
import os
import runpy
import site
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
site.addsitedir(str(root/"runtime"/"site-packages"))
sys.path.insert(0, str(root/"mcp"))
os.environ["PATH"] = str(root/"vendor"/"libredwg"/"bin")+os.pathsep+os.environ.get("PATH", "")
runpy.run_path(str(root/"mcp"/"server.py"), run_name="__main__")
