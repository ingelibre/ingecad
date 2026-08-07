# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
#
# PyInstaller spec for IngeCAD. Build it through packaging/build-appimage.sh,
# which sets the working directory and the output paths this expects.
#
#     pyinstaller --noconfirm packaging/ingecad.spec
#
# onedir, not onefile: onefile unpacks ~250 MB to /tmp on every launch, which
# on a tmpfs desktop means a quarter gigabyte of RAM and a visible delay each
# time. The AppImage already gives the single-file experience.
import os
from pathlib import Path

ROOT = Path(os.environ.get("INGECAD_ROOT", os.getcwd())).resolve()

# Data the app reads at runtime, kept at the same relative paths the repo uses
# so core.paths.app_root() resolves them identically frozen or not.
datas = [
    (str(ROOT / "resources"), "resources"),
    (str(ROOT / "i18n"), "i18n"),
]

# The two LibreDWG converters, as binaries so the executable bit survives.
# They are statically linked against libredwg (ldd shows only libc and libm),
# so nothing else has to come along. The other ten programs in vendor/bin are
# never invoked by IngeCAD and would add ~118 MB.
binaries = []
for tool in ("dwg2dxf", "dxf2dwg"):
    path = ROOT / "vendor" / "libredwg" / "bin" / tool
    if not path.is_file():
        raise SystemExit(
            f"missing {path}\n"
            "Build vendor/libredwg first — see tools/libredwg-patches/README.md."
        )
    binaries.append((str(path), "vendor/libredwg/bin"))

# ezdxf finds these through its own registry rather than a plain import, so
# PyInstaller's static analysis does not see them.
hiddenimports = [
    "ezdxf.addons.drawing.pyqt",
    "ezdxf.addons.drawing.frontend",
    "ezdxf.addons.drawing.text_renderer",
    "ezdxf.addons.drawing.unified_text_renderer",
    "ezdxf.render.hatching",
]

# Qt ships far more than a 2D CAD viewport needs. Everything here is verified
# absent from the source: grep for "from PySide6." lists only QtCore, QtGui,
# QtOpenGL, QtOpenGLWidgets, QtPrintSupport, QtTest and QtWidgets.
excludes = [
    "PySide6.Qt3DAnimation", "PySide6.Qt3DCore", "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput", "PySide6.Qt3DLogic", "PySide6.Qt3DRender",
    "PySide6.QtBluetooth", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtLocation",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtNfc",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtPositioning",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D",
    "PySide6.QtQuickControls2", "PySide6.QtQuickWidgets", "PySide6.QtRemoteObjects",
    "PySide6.QtScxml", "PySide6.QtSensors", "PySide6.QtSerialBus",
    "PySide6.QtSerialPort", "PySide6.QtSpatialAudio", "PySide6.QtSql",
    "PySide6.QtStateMachine", "PySide6.QtTextToSpeech", "PySide6.QtUiTools",
    "PySide6.QtWebChannel", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineQuick",
    "PySide6.QtWebEngineWidgets", "PySide6.QtWebSockets",
    # not Qt: pulled in transitively and unused here
    "matplotlib", "tkinter", "PyQt5", "PyQt6", "pytest", "PIL.ImageQt",
]

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ingecad",
    debug=False,
    strip=False,
    upx=False,          # upx breaks Qt plugin loading often enough not to risk it
    console=False,      # a GUI app; errors go to the terminal when run from one
    icon=str(ROOT / "resources" / "icons" / "ingecad.png")
    if (ROOT / "resources" / "icons" / "ingecad.png").is_file()
    else None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="ingecad",
)
