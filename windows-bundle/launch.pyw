"""Relocatable application entry point; no system Python or PATH needed."""
import os
import site
import sys
import traceback
from pathlib import Path

root = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(root))
site.addsitedir(str(root/"runtime"/"site-packages"))
os.chdir(root)
os.environ["PATH"] = str(root/"vendor"/"libredwg"/"bin")+os.pathsep+os.environ.get("PATH", "")
os.environ.setdefault("INGECAD_SHOW_AI", "1")
try:
    from configure import configure
    configure(root)
    import main
    sys.exit(main.main())
except Exception:
    log = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))/"IngeCAD-AI"/"launch-error.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(traceback.format_exc(), encoding="utf-8")
    raise
