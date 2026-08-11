"""IngeCAD entry point.

Free 2D CAD for Linux in the spirit of classic AutoCAD. Part of the Inge
ecosystem (IngeTrazo 3D modeling, IngePresupuestos budgeting).

Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
Licensed under GPL-3.0-or-later. See LICENSE.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QColor, QPalette, QSurfaceFormat
from PySide6.QtWidgets import QApplication

from core import i18n
from core.version import __version__


def _configure_surface_format() -> None:
    """Request an OpenGL 3.3 Core context (matches the GLSL 330 shaders).

    No depth buffer request: the canvas is 2D and draws back-to-front. MSAA
    stays off the widget surface (IngeTrazo lesson: multisampled surfaces
    interleave stale frames on Wayland); AA arrives later in an offscreen FBO
    if line quality asks for it.
    """
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    QSurfaceFormat.setDefaultFormat(fmt)


def _apply_dark_theme(app: QApplication) -> None:
    """Force dark UI chrome regardless of the desktop theme.

    Model space is dark by design; light menus and title bar clash with it.
    ``setColorScheme`` drives the platform pieces (Wayland client-side title
    bar, native menus); the Fusion style + palette cover every widget so the
    look does not depend on whatever desktop theme is installed.
    """
    app.styleHints().setColorScheme(Qt.ColorScheme.Dark)
    app.setStyle("Fusion")

    window = QColor(45, 45, 48)
    base = QColor(37, 37, 40)
    text = QColor(224, 224, 224)
    disabled = QColor(128, 128, 128)
    highlight = QColor(42, 93, 143)

    p = QPalette()
    p.setColor(QPalette.Window, window)
    p.setColor(QPalette.WindowText, text)
    p.setColor(QPalette.Base, base)
    p.setColor(QPalette.AlternateBase, window)
    p.setColor(QPalette.Text, text)
    p.setColor(QPalette.PlaceholderText, disabled)
    p.setColor(QPalette.Button, window)
    p.setColor(QPalette.ButtonText, text)
    p.setColor(QPalette.BrightText, QColor(255, 96, 96))
    p.setColor(QPalette.ToolTipBase, QColor(58, 58, 61))
    p.setColor(QPalette.ToolTipText, text)
    p.setColor(QPalette.Highlight, highlight)
    p.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    p.setColor(QPalette.Link, QColor(74, 163, 224))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText, QPalette.HighlightedText):
        p.setColor(QPalette.Disabled, role, disabled)
    app.setPalette(p)


def _init_language() -> None:
    """Load the saved UI language; English by default.

    Engineers learned AutoCAD in English — commands, menus, muscle memory —
    so English is the default regardless of the system locale. Spanish is a
    deliberate opt-in via Tools > Language.
    """
    i18n.set_language(str(QSettings().value("language", "en")))


def _self_check() -> int:
    """Report whether this install can find everything it needs; --check.

    A packaged build can be missing a shader, a translation or a converter and
    still start, then fail the first time the user opens a drawing. This is what
    CI asserts on after building the AppImage, and what to run when an install
    misbehaves.
    """
    from core.paths import app_root, is_frozen
    from formats.dwg_bridge import find_dwg2dxf, find_dxf2dwg

    root = app_root()
    print(f"IngeCAD {__version__}")
    print(f"  packaged   : {'yes' if is_frozen() else 'no (running from the repo)'}")
    print(f"  app root   : {root}")

    problems: list[str] = []
    # Only files something actually reads. resources/linetypes and
    # resources/hatch are empty placeholders from the Phase 0 layout: the
    # standard linetypes come from ezdxf (core/document.py loads them) and the
    # hatch patterns from ezdxf.addons.drawing, so there is nothing to ship.
    for label, path in (
        ("vertex shader", root / "resources" / "shaders" / "line.vert"),
        ("fragment shader", root / "resources" / "shaders" / "line.frag"),
        ("thick shader", root / "resources" / "shaders" / "thick.vert"),
        ("app icon", root / "resources" / "ingecad.svg"),
        ("translations", root / "i18n" / "es.json"),
    ):
        ok = path.is_file()
        print(f"  {label:<14}: {'found' if ok else 'MISSING'}  {path}")
        if not ok:
            problems.append(label)

    # The drawing frontend resolves hatch patterns and text through these; a
    # missing hidden import shows up here rather than on the first HATCH.
    for label, module in (
        ("ezdxf render", "ezdxf.addons.drawing.frontend"),
        ("ezdxf hatch", "ezdxf.render.hatching"),
        ("ezdxf text", "ezdxf.addons.drawing.text_renderer"),
    ):
        try:
            __import__(module)
            print(f"  {label:<14}: import ok  ({module})")
        except Exception as exc:  # noqa: BLE001 - report whatever it is
            print(f"  {label:<14}: MISSING  {module}: {exc}")
            problems.append(label)

    for label, finder in (("dwg2dxf", find_dwg2dxf), ("dxf2dwg", find_dxf2dwg)):
        tool = finder()
        where = "bundled" if tool and str(tool).startswith(str(root)) else "system PATH"
        print(f"  {label:<14}: {f'{tool} ({where})' if tool else 'MISSING'}")
        if tool is None:
            problems.append(label)

    if problems:
        print(f"\nNOT OK — missing: {', '.join(problems)}")
        return 1
    print("\nOK")
    return 0


def main() -> int:
    # Background regens are pure-Python tessellation: with CPython's default
    # 5 ms GIL switch interval the UI thread starves in 5 ms chunks and the
    # crosshair stutters while a big drawing rebuilds. 1 ms keeps input smooth
    # for a barely measurable regen slowdown.
    if "--check" in sys.argv[1:]:
        return _self_check()
    sys.setswitchinterval(0.001)
    _configure_surface_format()
    app = QApplication(sys.argv)
    app.setApplicationName("IngeCAD")
    app.setOrganizationName("IngeCAD")
    # Wayland matches the running window to its .desktop entry by this name.
    app.setDesktopFileName("ingecad")
    from PySide6.QtGui import QIcon

    from core.paths import app_root

    icon_path = app_root() / "resources" / "ingecad.svg"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    _apply_dark_theme(app)
    _init_language()

    from views.main_window import MainWindow

    window = MainWindow()
    # Show before opening, not after. A double-clicked drawing can take
    # seconds, and the window must already be on screen for that wait to be
    # visible at all. It also keeps the status bar honest: QStatusBar only
    # hides the coordinate readout for a message if the readout is visible
    # when the message arrives, so opening first painted the "Opening..."
    # text underneath the coordinates, both illegible.
    window.show()
    # A document passed on the command line (the OS file association's
    # double-click hands it as argv[1]) opens right away; otherwise start with
    # a blank drawing, like AutoCAD's Drawing1, so the panels and commands work
    # from the first click instead of waiting for File > New.
    opened = False
    if len(sys.argv) > 1:
        doc = Path(sys.argv[1])
        if doc.suffix.lower() in (".dxf", ".dwg") and doc.exists():
            window.open_path(doc)
            opened = True
    if not opened:
        # No file to open: ask which unit this drawing is in, and offer the
        # recent ones — the two things BricsCAD asks at startup. A drawing
        # double-clicked in the file manager never sees this window, and the
        # user can retire it with its own checkbox.
        opened = _startup_choice(window)
    if not opened:
        window.new_document()
    return app.exec()


def _startup_choice(window) -> bool:
    """Show the startup window. True if it already produced a document."""
    from views.startup_dialog import StartupDialog, should_show

    if not should_show():
        window.new_document(window.startup_template())
        return True
    dialog = StartupDialog(window)
    dialog.exec()
    choice = dialog.choice()
    if choice is None:
        return False
    action, value = choice
    if action == "open":
        window.open_path(Path(value))
    elif action == "template":
        window.new_from_drawing(Path(value))
    else:
        window.new_document(value)
    return True


if __name__ == "__main__":
    sys.exit(main())
