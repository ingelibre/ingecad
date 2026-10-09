"""Dedicated real IngeCAD window; never attaches to or closes user windows."""
import os
import sys
from pathlib import Path

APP = Path(os.environ["LOCALAPPDATA"])/"Programs"/"IngeCAD"
sys.path.insert(0, str(APP))
os.chdir(APP)
os.environ["PATH"] = str(APP/"vendor"/"libredwg") + os.pathsep + os.environ["PATH"]
from PySide6.QtCore import QCoreApplication, QTimer
from PySide6.QtWidgets import QApplication
QCoreApplication.setApplicationName("IngeCAD")
QCoreApplication.setOrganizationName("IngeCAD")
import main
main._configure_surface_format()
app = QApplication(["IngeCAD MCP verification"])
main._apply_dark_theme(app)
main._init_language()
from views.main_window import MainWindow
from PySide6.QtCore import Qt
window = MainWindow()
window.show()
window.new_document()
window.document.doc.units = 4
window.setWindowTitle("IngeCAD MCP — verification drawing")
out = Path(sys.argv[1])
out.mkdir(exist_ok=True)
(out/"host-ready.txt").write_text(window._mcp_bridge.id)


def check_stop():
    if (out/"replace-document.txt").exists():
        (out/"replace-document.txt").unlink()
        window.document.dirty = False
        window.new_document()
        (out/"replacement-session.txt").write_text(window._mcp_bridge.id)
    if (out/"stop-host.txt").exists():
        for w in list(app.topLevelWidgets()):
            if isinstance(w, MainWindow):
                w.document.dirty = False
                w.close()
        app.quit()


timer = QTimer()
timer.timeout.connect(check_stop)
timer.start(250)
sys.exit(app.exec())
