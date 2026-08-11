# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""IngeCAD main window — classic pre-ribbon layout.

Menu bar + (from Phase 3) dockable toolbars, command line at the bottom, and a
status bar with coordinate readout and mode toggles. The ribbon does not exist
and will never exist here.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (QEvent, QObject, QPoint, QSettings, Qt,
                            QThread, Signal)
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMenuBar,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from core import i18n
from core.actions import Dispatcher, Prompt
from core.commands import History
from core.document import Document, DocumentError
from core.i18n import tr
from views.command_line import CommandLine
from views.title_bar import TitleBar
from core.version import __version__
from views.viewport import Viewport


class _OpenWorker(QObject):
    """Loads and regens a drawing off the UI thread.

    Real plans take seconds (a colleague's 4.5 MB pavement sheet froze the UI
    for minutes before the hatch density cap) — the window must stay alive.
    Only plain Python/ezdxf objects cross the thread boundary.
    """

    done = Signal(object, object)   # Document, Scene
    failed = Signal(str)            # error text

    def __init__(self, path: Path) -> None:
        super().__init__()
        self._path = path

    def run(self) -> None:
        from formats.dwg_bridge import DwgBridgeError, load_dwg
        from render.backend import build_scene

        try:
            if self._path.suffix.lower() == ".dwg":
                # Transparent conversion: the user never sees the temp DXF.
                document = load_dwg(self._path)
            else:
                document = Document.load(self._path)
            scene = build_scene(document)
        except (DocumentError, DwgBridgeError) as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # a malformed file must never crash the app
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        else:
            self.done.emit(document, scene)


class RegenWorker(QThread):
    """Rebuild the scene off the UI thread (a cadastre regen takes seconds).

    The GIL makes concurrent reads memory-safe, but the user may edit while
    we tessellate: the worker records the document revision it started from
    and any exception mid-build is treated as "the doc moved under us" — the
    result is discarded and the owner reruns once the edits settle. Visually
    nothing is lost: edits show instantly through the surgical/overlay paths.
    """

    done = Signal(object, object, int, object)  # document, scene|None, rev, layout

    def __init__(self, document: Document, layout: str, revision: int) -> None:
        super().__init__()
        self._document = document
        self._layout = layout
        self._revision = revision

    def run(self) -> None:
        from render.backend import build_scene

        try:
            scene = build_scene(self._document, self._layout)
        except Exception:
            scene = None    # doc mutated mid-read (or bad data): stale
        self.done.emit(self._document, scene, self._revision, self._layout)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.document: Document | None = None
        self._regen_worker: RegenWorker | None = None
        self._regen_rerun = False
        self._regen_zoom = False
        self._layers_dock = None
        self._layers_panel = None
        self._active_vp = None    # MSPACE-activated viewport entity, if any
        # Wheel/pan inside the active viewport mutate its view live; ONE
        # Command is committed when the gesture settles (AutoCAD groups
        # zooms too). Holds (vp, old_view_center, old_view_height).
        self._vp_gesture = None
        from PySide6.QtCore import QTimer

        self._vp_gesture_timer = QTimer(self)
        self._vp_gesture_timer.setSingleShot(True)
        self._vp_gesture_timer.setInterval(700)
        self._vp_gesture_timer.timeout.connect(self._vp_gesture_commit)
        self._open_thread: QThread | None = None
        self._open_worker: _OpenWorker | None = None
        self._opening_name = ""
        self.setWindowTitle(f"IngeCAD — {tr('Untitled')}")
        self.resize(1280, 800)
        # Own the title bar: the system one follows the desktop's light theme
        # on GNOME/Wayland and cannot be forced dark (see views/title_bar.py).
        self.setWindowFlag(Qt.FramelessWindowHint, True)

        self.viewport = Viewport(self)
        self.setCentralWidget(self.viewport)

        self._menu_bar = QMenuBar(self)
        header = QWidget(self)
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(0)
        header_layout.addWidget(TitleBar(self))
        header_layout.addWidget(self._menu_bar)
        self.setMenuWidget(header)

        self._build_menus()
        self._build_status_bar()
        self._build_command_line()
        self._build_sidebar()
        self._build_toolbars()
        self.viewport.cursorMoved.connect(self._on_cursor_moved)

        # Frameless windows have no system resize borders; an app-wide filter
        # turns presses on the outer margin into native resizes, wherever the
        # child widget under the cursor is. The status bar's size grip still
        # works as usual.
        from PySide6.QtWidgets import QApplication

        QApplication.instance().installEventFilter(self)

    RESIZE_MARGIN = 8

    def _edges_at(self, x: int, y: int):
        edges = Qt.Edges()
        m = self.RESIZE_MARGIN
        if x <= m:
            edges |= Qt.LeftEdge
        elif x >= self.width() - m:
            edges |= Qt.RightEdge
        if y <= m:
            edges |= Qt.TopEdge
        elif y >= self.height() - m:
            edges |= Qt.BottomEdge
        return edges

    def keyPressEvent(self, event) -> None:
        # While DTEXT is typing in place, Esc finishes the text (keeping it),
        # otherwise Esc cancels the active tool / clears the selection.
        if event.key() == Qt.Key_Escape:
            if self.tools.text_capturing():
                self.tools.text_finish()
            else:
                self._on_prompt_cancelled()
            return
        super().keyPressEvent(event)

    def _cmd_delete(self) -> None:
        if self.tools.delete_selection():
            self.viewport.update()

    def _cmd_copy(self) -> None:
        if self.tools.copy_selection():
            self.command_line.echo(tr("Copied to clipboard."))

    def _cmd_cut(self) -> None:
        if self.tools.copy_selection(cut=True):
            self.command_line.echo(tr("Cut to clipboard."))
            self.viewport.update()

    def _cmd_paste(self) -> None:
        self.tools.paste()
        self.viewport.setFocus()

    # -- canvas right-click (classic AutoCAD shortcut menu) ---------------------
    def on_canvas_right_click(self, global_pos) -> None:
        """Right-click on the canvas: Enter while a command runs, the
        shortcut menu when idle (classic AutoCAD defaults)."""
        if self.tools.active() or self.tools._selecting_for is not None:
            if not self.tools.on_text(""):
                self.dispatcher.submit("")
            return
        if self.dispatcher.pending_prompt is not None:
            self.dispatcher.submit("")      # accept the prompt's default
            return
        self.show_canvas_context_menu(global_pos)

    def show_canvas_context_menu(self, global_pos) -> None:
        from PySide6.QtWidgets import QMenu

        from core import layouts as layout_ops

        menu = QMenu(self)
        last = self.dispatcher.last_command
        if last:
            menu.addAction(tr("Repeat {name}", name=last),
                           lambda: self.dispatcher.submit(last))
            menu.addSeparator()
        model_sel = bool(self.tools.selection)
        vp = self.tools.paper_vp
        vp_sel = vp is not None and vp.is_alive
        act = menu.addAction(tr("Cut"), self._cmd_cut)
        act.setEnabled(model_sel)
        act = menu.addAction(tr("Copy"), self._cmd_copy)
        act.setEnabled(model_sel)
        menu.addAction(tr("Paste"), self._cmd_paste)
        menu.addSeparator()
        if vp_sel:
            # selected viewport: AutoCAD's viewport shortcut entries
            menu.addAction(tr("Erase"), self._cmd_delete)
            lock = menu.addAction(tr("Display locked"))
            lock.setCheckable(True)
            lock.setChecked(layout_ops.is_viewport_locked(vp))
            lock.triggered.connect(lambda _=False: self._cmd_vplock())
            menu.addSeparator()
            menu.addAction(tr("Deselect All"), self.tools.clear_selection)
        elif model_sel:
            menu.addAction(tr("Erase"), self._cmd_delete)
            for label, name in ((tr("Move"), "MOVE"),
                                (tr("Copy Selection"), "COPY"),
                                (tr("Rotate"), "ROTATE"),
                                (tr("Scale"), "SCALE")):
                menu.addAction(
                    label, lambda checked=False, n=name: self._invoke_command(n))
            menu.addSeparator()
            menu.addAction(tr("Deselect All"), self.tools.clear_selection)
        else:
            menu.addAction(tr("Undo"), self._cmd_undo)
            menu.addAction(tr("Redo"), self._cmd_redo)
            menu.addSeparator()
            menu.addAction(tr("Pan"), lambda: self._invoke_command("PAN"))
            menu.addAction(tr("Zoom Extents"), self.viewport.zoom_extents)
        menu.exec(global_pos)

    def _plot_dialog(self) -> None:
        if self.document is None:
            self.command_line.echo(tr("Nothing to plot."))
            return
        from views.print_dialog import PrintDialog

        PrintDialog(self).exec()

    def eventFilter(self, obj, event) -> bool:
        # In-place TEXT typing captures the keyboard before the command line.
        if (event.type() == QEvent.KeyPress and self.tools.text_capturing()
                and not event.modifiers() & (Qt.ControlModifier | Qt.AltModifier)):
            key = event.key()
            if key in (Qt.Key_Return, Qt.Key_Enter):
                self.tools.text_newline()
            elif key == Qt.Key_Escape:
                self.tools.text_finish()
            elif key == Qt.Key_Backspace:
                self.tools.text_backspace()
            elif event.text() and event.text().isprintable():
                self.tools.text_char(event.text())
            return True
        # AutoCAD feel: typing over the canvas lands in the command line.
        if (
            event.type() == QEvent.KeyPress
            and obj is getattr(self, "viewport", None)
            and not event.modifiers() & (Qt.ControlModifier | Qt.AltModifier)
            and (event.text().strip() or event.key() in (
                Qt.Key_Return, Qt.Key_Enter, Qt.Key_Escape, Qt.Key_Backspace))
        ):
            self.command_line.type_ahead(event)
            return True
        if (
            event.type() == QEvent.MouseButtonDblClick
            and event.button() == Qt.LeftButton
            and obj in getattr(self, "_tab_buttons", {})
        ):
            # Double-click renames a layout tab (BricsCAD; Model is fixed).
            name = self._tab_buttons[obj]
            if name != "Model":
                self._rename_layout_tab(name)
                return True
        if (
            event.type() == QEvent.MouseButtonPress
            and event.button() == Qt.LeftButton
            and isinstance(obj, QWidget)
            # Call QWidget.window() unbound: our panels store a `self.window`
            # attribute (the MainWindow) that shadows the QWidget.window()
            # method, so obj.window() would try to call the MainWindow.
            and QWidget.window(obj) is self
            and not self.isMaximized()
        ):
            pos = self.mapFromGlobal(event.globalPosition().toPoint())
            edges = self._edges_at(pos.x(), pos.y())
            handle = self.windowHandle()
            if edges and handle is not None and handle.startSystemResize(edges):
                return True
        return super().eventFilter(obj, event)

    # -- chrome ---------------------------------------------------------------
    def _build_menus(self) -> None:
        menu_bar = self._menu_bar
        menu_bar.clear()

        def item(menu, label, slot, shortcut=None, icon=None):
            from views.icons import command_icon
            act = QAction(label, self)
            if shortcut is not None:
                act.setShortcut(shortcut)
            if icon is not None:
                act.setIcon(command_icon(icon))
            act.triggered.connect(slot)
            menu.addAction(act)
            return act

        def cmd_item(menu, label, name, icon=True):
            from views.icons import command_icon
            act = QAction(label, self)
            if icon:
                act.setIcon(command_icon(name))
            act.triggered.connect(lambda _=False, n=name: self._invoke_command(n))
            menu.addAction(act)
            return act

        # -- File -------------------------------------------------------------
        file_menu = menu_bar.addMenu(tr("File"))
        item(file_menu, tr("New"), self.new_document, QKeySequence.New,
             icon="NEW")
        item(file_menu, tr("Open..."), self._open_dialog, QKeySequence.Open,
             icon="OPEN")
        # Owned by the window on the C++ side, not by Python: a QMenu that
        # addMenu(title) hands back is Python-owned, and this one is reached
        # later (every open and every save refresh it). Without a real parent
        # it is collected as soon as the garbage collector runs on a window
        # that has not been shown yet, and refreshing it raises "C++ object
        # already deleted" in the middle of saving a drawing.
        previous = getattr(self, "_recent_menu", None)
        if previous is not None:
            try:
                previous.deleteLater()      # language switch: no leak
            except RuntimeError:
                pass
        self._recent_menu = QMenu(tr("Recent drawings"), self)
        file_menu.addMenu(self._recent_menu)
        self._refresh_recent_menu()
        file_menu.addSeparator()
        item(file_menu, tr("Save"), self.save_document, QKeySequence.Save,
             icon="SAVEAS")
        item(file_menu, tr("Save As..."), self._save_as_dialog,
             QKeySequence.SaveAs, icon="SAVEAS")
        file_menu.addSeparator()
        item(file_menu, tr("Page Setup..."), lambda: self._cmd_pagesetup(),
             icon="PAGESETUP")
        item(file_menu, tr("Plot..."), self._plot_dialog, QKeySequence.Print,
             icon="PLOT")
        file_menu.addSeparator()
        item(file_menu, tr("Quit"), self.close, QKeySequence.Quit)

        # -- Edit -------------------------------------------------------------
        edit_menu = menu_bar.addMenu(tr("Edit"))
        item(edit_menu, tr("Undo"), self._cmd_undo, QKeySequence.Undo,
             icon="UNDO")
        # Redo answers to the platform key AND to AutoCAD's Ctrl+Y. Both go on
        # the ONE action: a separate QShortcut for Ctrl+Y made Qt see two
        # handlers for the same key on platforms where QKeySequence.Redo
        # already is Ctrl+Y (Linux), and an ambiguous shortcut fires neither —
        # Ctrl+Y silently did nothing.
        redo_action = item(edit_menu, tr("Redo"), self._cmd_redo, icon="REDO")
        redo_keys = [QKeySequence(QKeySequence.Redo)]
        autocad_redo = QKeySequence("Ctrl+Y")
        if autocad_redo not in redo_keys:
            redo_keys.append(autocad_redo)
        redo_action.setShortcuts(redo_keys)
        edit_menu.addSeparator()

        # Clipboard / Delete fire only when the drawing canvas has focus, so
        # Ctrl+C/X/V and Delete keep their text meaning inside the command
        # line and other input fields (added to the viewport widget).
        def canvas_action(label, slot, seq, icon=None):
            from views.icons import command_icon
            act = QAction(label, self)
            act.setShortcut(seq)
            act.setShortcutContext(Qt.WidgetWithChildrenShortcut)
            if icon is not None:
                act.setIcon(command_icon(icon))
            act.triggered.connect(slot)
            edit_menu.addAction(act)
            self.viewport.addAction(act)
            return act

        canvas_action(tr("Cut"), self._cmd_cut, QKeySequence.Cut,
                      icon="CUTCLIP")
        canvas_action(tr("Copy"), self._cmd_copy, QKeySequence.Copy,
                      icon="COPYCLIP")
        canvas_action(tr("Paste"), self._cmd_paste, QKeySequence.Paste,
                      icon="PASTECLIP")
        canvas_action(tr("Delete"), self._cmd_delete, QKeySequence.Delete,
                      icon="ERASE")
        edit_menu.addSeparator()
        cmd_item(edit_menu, tr("Erase"), "ERASE")
        cmd_item(edit_menu, tr("Move"), "MOVE")
        cmd_item(edit_menu, tr("Copy"), "COPY")

        # -- View -------------------------------------------------------------
        view_menu = menu_bar.addMenu(tr("View"))
        item(view_menu, tr("Zoom Extents"), self.viewport.zoom_extents,
             icon="ZOOM_EXTENTS")
        item(view_menu, tr("Zoom Window"),
             lambda: self._invoke_command("ZOOM"), icon="ZOOM_WINDOW")
        item(view_menu, tr("Pan"), lambda: self._invoke_command("PAN"),
             icon="PAN")
        item(view_menu, tr("Regenerate"), self.regen_in_memory, icon="REGEN")
        view_menu.addSeparator()
        # Classic AutoCAD: View > Viewports (paper-space floating viewports).
        vp_menu = view_menu.addMenu(tr("Viewports"))
        cmd_item(vp_menu, tr("1 Viewport"), "MVIEW")
        cmd_item(vp_menu, tr("Lock/Unlock Viewport"), "VPLOCK")
        vp_menu.addSeparator()
        item(vp_menu, tr("Model space (MSPACE)"),
             lambda: self._invoke_command("MSPACE"))
        item(vp_menu, tr("Paper space (PSPACE)"),
             lambda: self._invoke_command("PSPACE"))
        view_menu.addSeparator()
        item(view_menu, tr("Layers panel"), self.toggle_layers_panel,
             icon="LAYER")

        # -- Insert -----------------------------------------------------------
        insert_menu = menu_bar.addMenu(tr("Insert"))
        cmd_item(insert_menu, tr("Block..."), "INSERT")
        cmd_item(insert_menu, tr("Create Block..."), "BLOCK")
        insert_menu.addSeparator()
        # Classic AutoCAD: Insert > Layout.
        layout_menu = insert_menu.addMenu(tr("Layout"))
        item(layout_menu, tr("New Layout"), self._new_layout_tab,
             icon="LAYOUT")
        cmd_item(layout_menu, tr("Layout..."), "LAYOUT")

        # -- Format -----------------------------------------------------------
        format_menu = menu_bar.addMenu(tr("Format"))
        item(format_menu, tr("Layers..."), self.toggle_layers_panel,
             icon="LAYER")
        cmd_item(format_menu, tr("Linetype..."), "LINETYPE")
        format_menu.addSeparator()
        item(format_menu, tr("Text Style..."), self.toggle_styles_panel,
             icon="STYLE")
        item(format_menu, tr("Dimension Style..."),
             self._open_dimstyle_manager, icon="DIMSTYLE")
        format_menu.addSeparator()
        item(format_menu, tr("Units..."), self._units_dialog)

        # -- Draw -------------------------------------------------------------
        draw_menu = menu_bar.addMenu(tr("Draw"))
        cmd_item(draw_menu, tr("Construction Line"), "XLINE")
        cmd_item(draw_menu, tr("Ray"), "RAY")
        draw_menu.addSeparator()
        for label, name in ((tr("Line"), "LINE"), (tr("Polyline"), "PLINE"),
                            (tr("Circle"), "CIRCLE"), (tr("Arc"), "ARC"),
                            (tr("Ellipse"), "ELLIPSE"),
                            (tr("Rectangle"), "RECTANG"), (tr("Polygon"), "POLYGON"),
                            (tr("Point"), "POINT")):
            cmd_item(draw_menu, label, name)
        # AutoCAD classic: Draw > Point > Divide / Measure
        point_menu = draw_menu.addMenu(tr("Point"))
        cmd_item(point_menu, tr("Divide"), "DIVIDE")
        cmd_item(point_menu, tr("Measure"), "MEASURE")
        cmd_item(draw_menu, tr("Revision Cloud"), "REVCLOUD")
        draw_menu.addSeparator()
        cmd_item(draw_menu, tr("Text"), "TEXT")
        cmd_item(draw_menu, tr("Multiline text"), "MTEXT")
        cmd_item(draw_menu, tr("Hatch"), "HATCH")

        # -- Dimension --------------------------------------------------------
        dim_menu = menu_bar.addMenu(tr("Dimension"))
        cmd_item(dim_menu, tr("Linear"), "DIMLINEAR")
        cmd_item(dim_menu, tr("Aligned"), "DIMALIGNED")
        cmd_item(dim_menu, tr("Arc Length"), "DIMARC")
        cmd_item(dim_menu, tr("Ordinate"), "DIMORDINATE")
        cmd_item(dim_menu, tr("Radius"), "DIMRADIUS")
        cmd_item(dim_menu, tr("Diameter"), "DIMDIAMETER")
        cmd_item(dim_menu, tr("Angular"), "DIMANGULAR")
        dim_menu.addSeparator()
        cmd_item(dim_menu, tr("Baseline"), "DIMBASELINE")
        cmd_item(dim_menu, tr("Continue"), "DIMCONTINUE")
        dim_menu.addSeparator()
        cmd_item(dim_menu, tr("Center Mark"), "DIMCENTER")
        cmd_item(dim_menu, tr("Align Text"), "DIMTEDIT")
        dim_menu.addSeparator()
        style_act = QAction(tr("Dimension Style..."), self)
        from views.icons import command_icon as _cmd_icon
        style_act.setIcon(_cmd_icon("DIMSTYLE"))
        style_act.triggered.connect(self._open_dimstyle_manager)
        dim_menu.addAction(style_act)
        dim_menu.addSeparator()
        cmd_item(dim_menu, tr("Area"), "AREA", icon=False)

        # -- Modify -----------------------------------------------------------
        modify_menu = menu_bar.addMenu(tr("Modify"))
        for label, name in ((tr("Move"), "MOVE"), (tr("Copy"), "COPY"),
                            (tr("Rotate"), "ROTATE"), (tr("Scale"), "SCALE"),
                            (tr("Mirror"), "MIRROR"), (tr("Offset"), "OFFSET")):
            cmd_item(modify_menu, label, name)
        modify_menu.addSeparator()
        for label, name in ((tr("Trim"), "TRIM"), (tr("Extend"), "EXTEND"),
                            (tr("Fillet"), "FILLET"), (tr("Erase"), "ERASE")):
            cmd_item(modify_menu, label, name)
        cmd_item(modify_menu, tr("Chamfer"), "CHAMFER")
        cmd_item(modify_menu, tr("Array"), "ARRAY")
        modify_menu.addSeparator()
        for label, name in ((tr("Stretch"), "STRETCH"), (tr("Break"), "BREAK"),
                            (tr("Join"), "JOIN")):
            cmd_item(modify_menu, label, name)
        modify_menu.addSeparator()
        cmd_item(modify_menu, tr("Match Properties"), "MATCHPROP")
        object_menu = QMenu(tr("Object"), self)
        modify_menu.addMenu(object_menu)
        cmd_item(object_menu, tr("Polyline"), "PEDIT")
        cmd_item(modify_menu, tr("Explode"), "EXPLODE")

        # -- Tools ------------------------------------------------------------
        tools_menu = menu_bar.addMenu(tr("Tools"))
        inquiry_menu = tools_menu.addMenu(tr("Inquiry"))
        cmd_item(inquiry_menu, tr("Distance"), "DIST", icon=False)
        cmd_item(inquiry_menu, tr("Area"), "AREA", icon=False)
        cmd_item(inquiry_menu, tr("List"), "LIST", icon=False)
        cmd_item(inquiry_menu, tr("ID Point"), "ID", icon=False)
        tools_menu.addSeparator()
        lang_menu = tools_menu.addMenu(tr("Language"))
        lang_group = QActionGroup(self)
        # Each language is listed in its own name — recognizable no matter
        # which language is currently active.
        for code, native_name in (("en", "English"), ("es", "Español")):
            act = QAction(native_name, self)
            act.setCheckable(True)
            act.setChecked(i18n.current_language() == code)
            act.triggered.connect(lambda _=False, c=code: self._set_language(c))
            lang_group.addAction(act)
            lang_menu.addAction(act)

        # -- Window / Help ----------------------------------------------------
        window_menu = menu_bar.addMenu(tr("Window"))
        item(window_menu, tr("Layers panel"), self.toggle_layers_panel)
        item(window_menu, tr("Command line"),
             lambda: self.command_line.input.setFocus())

        help_menu = menu_bar.addMenu(tr("Help"))
        item(help_menu, tr("About IngeCAD"), self._show_about)

        # PySide6 gotcha: QMenus returned by addMenu(title) are Python-owned
        # — without a live reference, gc.collect() DELETES them (menus and
        # submenus would vanish from a running app). Keep them all.
        self._menus = []
        for action in menu_bar.actions():
            menu = action.menu()
            if menu is None:
                continue
            self._menus.append(menu)
            for sub in menu.actions():
                if sub.menu() is not None:
                    self._menus.append(sub.menu())

    def _show_about(self) -> None:
        from PySide6.QtWidgets import QMessageBox
        from core.version import __version__

        QMessageBox.about(
            self, tr("About IngeCAD"),
            f"IngeCAD {__version__}\n"
            + tr("Free 2D CAD for Linux in the spirit of classic AutoCAD.")
            + "\nGPL-3.0-or-later · Marco Sumari Tellez")

    def _set_language(self, code: str) -> None:
        """Switch the UI language, persist it, and retranslate live."""
        if code == i18n.current_language():
            return
        QSettings().setValue("language", code)
        i18n.set_language(code)
        self._retranslate()

    def _retranslate(self) -> None:
        name = self.document.name if self.document else tr("Untitled")
        self.setWindowTitle(f"IngeCAD — {name}")
        self._build_menus()

    # -- command line -----------------------------------------------------------
    def _build_command_line(self) -> None:
        self.command_line = CommandLine(self)
        dock = QDockWidget(tr("Command"), self)
        dock.setObjectName("command_dock")
        dock.setWidget(self.command_line)
        dock.setFeatures(QDockWidget.DockWidgetFloatable | QDockWidget.DockWidgetMovable)
        dock.setTitleBarWidget(QWidget(dock))  # slim: no dock title bar
        self.addDockWidget(Qt.BottomDockWidgetArea, dock)

        self.history = History()
        self.dispatcher = Dispatcher(echo=self.command_line.echo)

        from views.tool_controller import ToolController

        self.tools = ToolController(self)
        self.viewport.tool_delegate = self.tools
        self.tools.changed.connect(self.viewport.update)

        self._register_commands()
        self.command_line.set_completions(self.dispatcher.known_names())
        self.command_line.submitted.connect(self._on_command_submitted)
        self.command_line.cancelled.connect(self._on_prompt_cancelled)
        self.command_line.input.raw_text_check = (
            lambda: self.tools.tool is not None
            and self.tools.tool.wants_raw_text())
        # F2: the classic expanded text window (command history).
        from PySide6.QtGui import QShortcut
        QShortcut(QKeySequence("F2"), self, self._toggle_text_window)
        self.command_line.echo(tr("IngeCAD — type a command (L, C, Z, ...)"))
        self._build_mode_toggles()

    def _on_command_submitted(self, text: str) -> None:
        self.command_line.echo_input(text)
        stripped = text.strip()
        if stripped.startswith("'"):
            # Transparent command ('ZOOM, 'PAN, 'REDRAW) — runs without
            # disturbing the active command, then resumes it.
            if self.tools.active() or self.dispatcher.pending_prompt \
                    is not None:
                self._run_transparent(stripped[1:])
                return
            self.dispatcher.submit(stripped[1:])
            return
        if self.tools.on_text(text):
            return
        self.dispatcher.submit(text)

    def _run_transparent(self, body: str) -> None:
        from core import aliases as aliases_mod

        tokens = body.split()
        if not tokens:
            return
        name = aliases_mod.resolve(tokens[0], self.dispatcher.aliases)
        args = tokens[1:]
        if name == "ZOOM":
            if not args:
                self.command_line.echo(
                    tr("'ZOOM: give an option (Extents/Previous or a "
                       "scale) — the wheel zooms anytime."))
            elif args[0].upper().startswith("W"):
                self.command_line.echo(
                    tr("ZOOM Window is not available transparently."))
            else:
                self._zoom_option(args[0])
        elif name == "PAN":
            self.command_line.echo(
                tr("Pan with the middle mouse button — it works during "
                   "any command."))
        elif name in ("REDRAW", "REGEN"):
            self.regen_in_memory()
        else:
            self.command_line.echo(
                tr("{name} cannot be used transparently.", name=name))
        active = self.tools.tool
        if active is not None:
            self.command_line.echo(tr(">> Resuming {name} command.",
                                      name=active.name))

    def _toggle_text_window(self) -> None:
        """F2 — the AutoCAD text window: the full command history, large."""
        from PySide6.QtWidgets import QDialog, QPlainTextEdit, QVBoxLayout

        dlg = getattr(self, "_text_window", None)
        if dlg is not None and dlg.isVisible():
            dlg.close()
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("IngeCAD Text Window"))
        dlg.resize(680, 420)
        text = QPlainTextEdit(dlg)
        text.setReadOnly(True)
        text.setStyleSheet("background: #1e1e22; color: #d8d8d8;"
                           " font-family: monospace;")
        text.setPlainText(self.command_line.history.toPlainText())
        scrollbar = text.verticalScrollBar()
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.addWidget(text)
        dlg.show()
        scrollbar.setValue(scrollbar.maximum())
        self._text_window = dlg

    def _on_prompt_cancelled(self) -> None:
        # tools.cancel() handles both cases: active tool, or idle selection
        if self.viewport._pan_mode:
            self.viewport.stop_pan_mode()
        self.tools.cancel()
        self.dispatcher.cancel()

    def _cmd_pan(self, *args) -> None:
        """Interactive PAN: open hand, left-drag pans, Esc/right-click ends."""
        self.viewport.start_pan_mode()
        self.command_line.echo(
            tr("Press Esc or right-click to exit pan."))
        self.viewport.setFocus()

    # -- drafting mode toggles (classic status bar buttons) ---------------------
    # AutoCAD status bar: clickable toggle buttons + their F-keys.
    _MODES = (
        ("grid", "F7", "GRID", "Grid display"),
        ("ortho", "F8", "ORTHO", "Ortho mode"),
        ("polar", "F10", "POLAR", "Polar tracking"),
        ("osnap", "F3", "OSNAP", "Object snap"),
        ("lwt", None, "LWT", "Show lineweight"),
    )

    def _build_mode_toggles(self) -> None:
        from PySide6.QtGui import QShortcut
        from PySide6.QtWidgets import QToolButton

        style = """
        QToolButton { border: 1px solid transparent; padding: 1px 7px;
            color: #6a6a6a; font-size: 11px; font-weight: bold; }
        QToolButton:hover { border-color: #4a4a52; }
        QToolButton:checked { color: #e8e8e8; background: #35424f;
            border-color: #4a5a6a; border-radius: 2px; }
        """
        # Classic AutoCAD PAPER/MODEL toggle: on a layout tab it flips
        # MSPACE/PSPACE; the Model tab always reads MODEL.
        self._space_btn = QToolButton(self)
        self._space_btn.setStyleSheet(style)
        self._space_btn.setToolTip(
            tr("Toggle paper/model space in the layout (MSPACE/PSPACE)"))
        self._space_btn.setFocusPolicy(Qt.NoFocus)
        self._space_btn.clicked.connect(self._toggle_space)
        self.statusBar().addPermanentWidget(self._space_btn)
        self._update_space_button()

        self._mode_buttons: dict[str, QToolButton] = {}
        for key, fkey, label, tip in self._MODES:
            b = QToolButton(self)
            b.setText(tr(label))
            b.setCheckable(True)
            b.setStyleSheet(style)
            b.setToolTip(tr(tip) + (f" ({fkey})" if fkey else ""))
            b.setFocusPolicy(Qt.NoFocus)   # clicks must not steal the canvas
            b.clicked.connect(lambda _=False, k=key: self._toggle_mode(k))
            self._mode_buttons[key] = b
            self.statusBar().addPermanentWidget(b)
            if key == "osnap":
                # AutoCAD's status bar hangs the running-snap list off this
                # button; the arrow opens it without toggling the snap.
                arrow = QToolButton(self)
                arrow.setText("\u25b4")
                arrow.setStyleSheet(style)
                arrow.setToolTip(tr("Object snap modes"))
                arrow.setFocusPolicy(Qt.NoFocus)
                arrow.clicked.connect(self._show_osnap_menu)
                self._osnap_arrow = arrow
                self.statusBar().addPermanentWidget(arrow)
            if fkey:
                QShortcut(QKeySequence(fkey), self,
                          lambda k=key: self._toggle_mode(k))
        self._load_osnap_modes()

    def _toggle_space(self) -> None:
        if self.document is None or self._active_layout == "Model":
            self.command_line.echo(
                tr("The Model tab is model space — the toggle works on a "
                   "layout tab."))
            return
        if self._active_vp is not None:
            self._cmd_pspace()
        else:
            self._cmd_mspace()

    def _update_space_button(self) -> None:
        btn = getattr(self, "_space_btn", None)
        if btn is None:
            return
        in_paper = (self._active_layout != "Model"
                    and getattr(self, "_active_vp", None) is None)
        btn.setText(tr("PAPER") if in_paper else tr("MODEL"))

    def _mode_state(self, key: str) -> bool:
        if key == "grid":
            return self.viewport.grid_on
        if key == "lwt":
            return self.viewport.lwt_on
        return getattr(self.tools, f"{key}_on")

    def _toggle_mode(self, which: str) -> None:
        if which == "grid":
            self.viewport.grid_on = not self.viewport.grid_on
            value = self.viewport.grid_on
            self.viewport.update()
        elif which == "lwt":
            self.viewport.lwt_on = not self.viewport.lwt_on
            value = self.viewport.lwt_on
            self.viewport.update()
        else:
            value = self.tools.toggle(which)
            if which == "osnap":
                self._save_osnap_modes()
        self._update_mode_buttons()
        names = {"grid": tr("Grid"), "osnap": tr("Object snap"),
                 "ortho": tr("Ortho"), "polar": tr("Polar"),
                 "lwt": tr("Lineweight display")}
        state = tr("on") if value else tr("off")
        self.command_line.echo(f"{names[which]}: {state}")

    # -- running object snaps (the status-bar dropdown) ------------------------
    def _osnap_settings_key(self) -> str:
        return "osnap/osmode"

    def _load_osnap_modes(self) -> None:
        """Restore the running snaps from the saved OSMODE bitcode."""
        from core import osnap as osnap_modes

        raw = QSettings().value(self._osnap_settings_key(),
                                osnap_modes.DEFAULT_BITS)
        try:
            bits = int(raw)
        except (TypeError, ValueError):
            bits = osnap_modes.DEFAULT_BITS
        self.tools.osnap_modes = set(osnap_modes.from_bits(bits))
        self.tools.osnap_on = not osnap_modes.is_off(bits)
        self._update_mode_buttons()

    def _save_osnap_modes(self) -> None:
        from core import osnap as osnap_modes

        bits = osnap_modes.with_off(
            osnap_modes.to_bits(self.tools.osnap_modes),
            not self.tools.osnap_on)
        QSettings().setValue(self._osnap_settings_key(), bits)

    def _show_osnap_menu(self) -> None:
        from core import osnap as osnap_modes

        from views.osnap_dialog import marker_icon

        menu = QMenu(self)
        for mode in osnap_modes.MODES:
            action = menu.addAction(tr(mode.label))
            running = mode.key in self.tools.osnap_modes
            action.setCheckable(True)
            action.setChecked(running)
            action.setIcon(marker_icon(mode.key, running and mode.available))
            if mode.available:
                action.triggered.connect(
                    lambda checked, k=mode.key: self._set_osnap_mode(k, checked))
            else:
                action.setEnabled(False)
                action.setToolTip(tr(mode.note))
        menu.addSeparator()
        menu.addAction(tr("Object Snap Settings..."), self._osnap_settings)
        button = self._mode_buttons.get("osnap")
        anchor = getattr(self, "_osnap_arrow", button)
        menu.exec(anchor.mapToGlobal(anchor.rect().topLeft())
                  - QPoint(0, menu.sizeHint().height()))

    def _set_osnap_mode(self, key: str, on: bool) -> None:
        if on:
            self.tools.osnap_modes.add(key)
        else:
            self.tools.osnap_modes.discard(key)
        self._save_osnap_modes()
        from core import osnap as osnap_modes

        self.command_line.echo(
            tr("{mode}: {state}", mode=tr(osnap_modes.label_of(key)),
               state=tr("on") if on else tr("off")))

    def _osnap_settings(self) -> None:
        from views.osnap_dialog import OsnapSettingsDialog

        dialog = OsnapSettingsDialog(self, self.tools.osnap_modes,
                                     self.tools.osnap_on)
        if not dialog.exec():
            return
        self.tools.osnap_modes = set(dialog.modes())
        self.tools.osnap_on = dialog.osnap_on()
        self._save_osnap_modes()
        self._update_mode_buttons()

    def _update_mode_buttons(self) -> None:
        for key, b in self._mode_buttons.items():
            b.setChecked(self._mode_state(key))

    # -- document plumbing for the tools ---------------------------------------
    def _refresh_recent_menu(self) -> None:
        """File > Recent drawings, newest first."""
        from core import recent as recent_mod

        menu = getattr(self, "_recent_menu", None)
        if menu is None:
            return
        try:
            menu.clear()
        except RuntimeError:
            # The menu bar was rebuilt (language switch) and this submenu's
            # C++ side is gone. Saving a drawing must not die over a menu.
            self._recent_menu = None
            return
        paths = recent_mod.load()
        if not paths:
            empty = menu.addAction(tr("(none yet)"))
            empty.setEnabled(False)
            return
        for path in paths:
            action = menu.addAction(path.name)
            action.setToolTip(str(path))
            action.triggered.connect(
                lambda _=False, p=path: self.open_path(p))
        menu.addSeparator()
        menu.addAction(tr("Clear list"), self._clear_recent)

    def _clear_recent(self) -> None:
        from core import recent as recent_mod

        recent_mod.clear()
        self._refresh_recent_menu()

    def startup_template(self) -> str:
        """The template the user last started a drawing with."""
        from core import templates as templates_mod
        from views.startup_dialog import SETTING_TEMPLATE

        return str(QSettings().value(SETTING_TEMPLATE,
                                     templates_mod.DEFAULT_TEMPLATE))

    def new_from_drawing(self, path: Path) -> None:
        """Start from an existing drawing used as a template.

        It opens like any other file and then forgets where it came from, so
        the first Save asks for a name instead of overwriting the template —
        which is the whole point of a template.
        """
        self.open_path(path, as_template=True)

    def new_document(self, template: str | None = None) -> None:
        from core import templates as templates_mod

        self.document = templates_mod.new_document(
            template or self.startup_template())
        self._active_layout = "Model"
        self._deactivate_viewport()
        self._update_space_button()
        self._refresh_layout_tabs()
        self.viewport.set_scene(None)
        self.tools.attach_document(self.document)
        if self._layers_panel is not None:
            self._layers_panel.refresh()
        if getattr(self, "_styles_panel", None) is not None:
            self._styles_panel.refresh()
        if getattr(self, "_properties_panel", None) is not None:
            self._properties_panel.refresh()
        self.setWindowTitle(f"IngeCAD — {tr('Untitled')}")

    # -- classic toolbars (Draw left, Modify top) ------------------------------
    def _build_toolbars(self) -> None:
        from PySide6.QtWidgets import QToolBar

        from views.icons import command_icon

        draw = [("LINE", tr("Line")), ("PLINE", tr("Polyline")),
                ("CIRCLE", tr("Circle")), ("ARC", tr("Arc")),
                ("ELLIPSE", tr("Ellipse")), ("RECTANG", tr("Rectangle")),
                ("POLYGON", tr("Polygon")), ("POINT", tr("Point")),
                ("TEXT", tr("Text")), ("MTEXT", tr("Multiline text")),
                ("HATCH", tr("Hatch"))]
        # AutoCAD's own Modify toolbar order, so the hand finds them where
        # it expects: erase, copy, mirror, offset, array, move, rotate,
        # scale, stretch, trim, extend, break, join, chamfer, fillet,
        # explode.
        modify = [("ERASE", tr("Erase")), ("COPY", tr("Copy")),
                  ("MIRROR", tr("Mirror")), ("OFFSET", tr("Offset")),
                  ("ARRAY", tr("Array")), ("MOVE", tr("Move")),
                  ("ROTATE", tr("Rotate")), ("SCALE", tr("Scale")),
                  ("STRETCH", tr("Stretch")), ("TRIM", tr("Trim")),
                  ("EXTEND", tr("Extend")), ("BREAK", tr("Break")),
                  ("JOIN", tr("Join")), ("CHAMFER", tr("Chamfer")),
                  ("FILLET", tr("Fillet")), ("MATCHPROP", tr("Match Properties")),
                  ("EXPLODE", tr("Explode"))]

        self._draw_toolbar = QToolBar(tr("Draw"), self)
        self._draw_toolbar.setObjectName("draw_toolbar")
        self._draw_toolbar.setOrientation(Qt.Vertical)
        self._draw_toolbar.setMovable(True)
        for name, label in draw:
            act = QAction(command_icon(name), label, self)
            act.setToolTip(f"{label} ({name})")
            act.triggered.connect(lambda _=False, n=name: self._invoke_command(n))
            self._draw_toolbar.addAction(act)
        self.addToolBar(Qt.LeftToolBarArea, self._draw_toolbar)

        self._modify_toolbar = QToolBar(tr("Modify"), self)
        self._modify_toolbar.setObjectName("modify_toolbar")
        self._modify_toolbar.setMovable(True)
        for name, label in modify:
            act = QAction(command_icon(name), label, self)
            act.setToolTip(f"{label} ({name})")
            act.triggered.connect(lambda _=False, n=name: self._invoke_command(n))
            self._modify_toolbar.addAction(act)
        self.addToolBar(Qt.TopToolBarArea, self._modify_toolbar)
        self._build_props_toolbar()

    def _build_props_toolbar(self) -> None:
        """BricsCAD-style quick Layer + Properties bar on top."""
        from PySide6.QtWidgets import QComboBox, QLabel, QToolBar

        # Its own row under Modify: four combos plus seventeen modify
        # buttons do not fit on one row on a laptop, and what overflows is
        # silently hidden behind a chevron.
        bar = QToolBar(tr("Properties"), self)
        bar.setObjectName("props_toolbar")

        # Compact popups: a drawing can carry hundreds of layers, so cap the
        # visible rows. "combobox-popup: 0" forces Qt's non-native popup,
        # which is the one that actually honours setMaxVisibleItems (the
        # native popup ignores it and spans the whole screen).
        combo_style = "QComboBox { font-size: 11px; combobox-popup: 0; } " \
                      "QComboBox QAbstractItemView::item { min-height: 18px; }"

        self._layer_combo = QComboBox(self)
        self._layer_combo.setMinimumWidth(130)
        self._layer_combo.setMaximumWidth(200)
        self._layer_combo.setMaxVisibleItems(18)
        self._layer_combo.setStyleSheet(combo_style)
        self._layer_combo.setToolTip(tr("Current layer"))
        self._layer_combo.activated.connect(self._on_layer_combo)
        bar.addWidget(self._layer_combo)

        self._color_combo = QComboBox(self)
        self._color_combo.setFixedWidth(96)
        self._color_combo.setMaxVisibleItems(12)
        self._color_combo.setStyleSheet(combo_style)
        self._color_combo.setToolTip(tr("Color"))
        self._color_combo.activated.connect(self._on_prop_color)
        bar.addSeparator()
        bar.addWidget(self._color_combo)

        self._linetype_combo = QComboBox(self)
        self._linetype_combo.setFixedWidth(128)
        self._linetype_combo.setMaxVisibleItems(16)
        self._linetype_combo.setStyleSheet(combo_style)
        self._linetype_combo.setToolTip(tr("Linetype"))
        self._linetype_combo.activated.connect(self._on_prop_linetype)
        bar.addWidget(self._linetype_combo)

        self._lineweight_combo = QComboBox(self)
        self._lineweight_combo.setFixedWidth(104)
        self._lineweight_combo.setMaxVisibleItems(16)
        self._lineweight_combo.setStyleSheet(combo_style)
        self._lineweight_combo.setToolTip(tr("Lineweight"))
        self._lineweight_combo.activated.connect(self._on_prop_lineweight)
        bar.addWidget(self._lineweight_combo)
        self.addToolBarBreak(Qt.TopToolBarArea)
        self.addToolBar(Qt.TopToolBarArea, bar)
        self._props_toolbar = bar
        self._build_viewports_toolbar()
        if self._layers_panel is not None:
            self._layers_panel.changed.connect(self._refresh_props_toolbar)
        self.tools.changed.connect(self._refresh_props_toolbar)
        self._refresh_props_toolbar()

    # Viewport scale list (the classic Viewports toolbar combo). Unitless
    # like AutoCAD: a meters drawing on a mm sheet uses 10:1 for real 1:100.
    _VP_SCALES = [(1000, 1), (100, 1), (10, 1), (4, 1), (2, 1), (1, 1),
                  (1, 2), (1, 4), (1, 5), (1, 8), (1, 10), (1, 16), (1, 20),
                  (1, 25), (1, 30), (1, 40), (1, 50), (1, 100), (1, 200),
                  (1, 500), (1, 1000)]

    def _build_viewports_toolbar(self) -> None:
        """Classic AutoCAD "Viewports" toolbar: viewport buttons + the
        viewport scale combo, docked next to Modify/Properties."""
        from PySide6.QtWidgets import QComboBox, QToolBar

        from views.icons import command_icon

        bar = QToolBar(tr("Viewports"), self)
        bar.setObjectName("viewports_toolbar")
        for name, label in (("MVIEW", tr("New viewport")),
                            ("VPLOCK", tr("Lock/unlock viewport")),
                            ("PAGESETUP", tr("Page setup"))):
            act = QAction(command_icon(name), label, self)
            act.setToolTip(f"{label} ({name})")
            act.triggered.connect(lambda _=False, n=name: self._invoke_command(n))
            bar.addAction(act)
        self._vp_scale_combo = QComboBox(self)
        self._vp_scale_combo.setToolTip(tr("Viewport scale"))
        self._vp_scale_combo.setMinimumWidth(84)
        self._vp_scale_combo.setStyleSheet(
            "QComboBox { font-size: 11px; combobox-popup: 0; }")
        self._vp_scale_combo.setMaxVisibleItems(16)
        self._vp_scale_combo.addItem("", None)     # slot 0: current/none
        for num, den in self._VP_SCALES:
            self._vp_scale_combo.addItem(f"{num:g}:{den:g}", (num, den))
        self._vp_scale_combo.activated.connect(self._on_vp_scale_combo)
        bar.addSeparator()
        bar.addWidget(self._vp_scale_combo)
        self.addToolBar(Qt.TopToolBarArea, bar)
        self.tools.changed.connect(self._refresh_vp_scale_combo)
        self._refresh_vp_scale_combo()
        self._build_dimension_toolbar()

    def _build_dimension_toolbar(self) -> None:
        """Classic AutoCAD "Dimension" toolbar: the dim commands in the 2011
        order, the current-style combo, and the Dimension Style manager."""
        from PySide6.QtWidgets import QComboBox, QToolBar

        from views.icons import command_icon

        bar = QToolBar(tr("Dimension"), self)
        bar.setObjectName("dimension_toolbar")
        for name, label in (("DIMLINEAR", tr("Linear")),
                            ("DIMALIGNED", tr("Aligned")),
                            ("DIMARC", tr("Arc Length")),
                            ("DIMORDINATE", tr("Ordinate")),
                            ("DIMRADIUS", tr("Radius")),
                            ("DIMDIAMETER", tr("Diameter")),
                            ("DIMANGULAR", tr("Angular")),
                            ("DIMBASELINE", tr("Baseline")),
                            ("DIMCONTINUE", tr("Continue"))):
            act = QAction(command_icon(name), label, self)
            act.setToolTip(f"{label} ({name})")
            act.triggered.connect(lambda _=False, n=name: self._invoke_command(n))
            bar.addAction(act)
        bar.addSeparator()
        for name, label in (("DIMCENTER", tr("Center Mark")),
                            ("DIMTEDIT", tr("Dimension Text Edit"))):
            act = QAction(command_icon(name), label, self)
            act.setToolTip(f"{label} ({name})")
            act.triggered.connect(lambda _=False, n=name: self._invoke_command(n))
            bar.addAction(act)
        bar.addSeparator()
        self._dim_style_combo = QComboBox(self)
        self._dim_style_combo.setToolTip(tr("Current dimension style"))
        self._dim_style_combo.setMinimumWidth(96)
        self._dim_style_combo.setMaximumWidth(150)
        self._dim_style_combo.setStyleSheet(
            "QComboBox { font-size: 11px; combobox-popup: 0; }")
        self._dim_style_combo.setMaxVisibleItems(16)
        self._dim_style_combo.activated.connect(self._on_dim_style_combo)
        bar.addWidget(self._dim_style_combo)
        act = QAction(command_icon("DIMSTYLE"), tr("Dimension Style..."), self)
        act.setToolTip(tr("Dimension Style Manager (DIMSTYLE)"))
        act.triggered.connect(self._open_dimstyle_manager)
        bar.addAction(act)
        self.addToolBar(Qt.TopToolBarArea, bar)
        self._dimension_toolbar = bar
        self.tools.changed.connect(self._refresh_dim_style_combo)
        self._refresh_dim_style_combo()

    def _refresh_dim_style_combo(self) -> None:
        from core import styles as style_ops

        combo = getattr(self, "_dim_style_combo", None)
        if combo is None:
            return
        if self.document is None:
            combo.clear()
            return
        names = style_ops.dim_style_names(self.document)
        current = style_ops.current_dim_style(self.document)
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(names)
        if current in names:
            combo.setCurrentText(current)
        combo.blockSignals(False)

    def _on_dim_style_combo(self, index: int) -> None:
        from core import styles as style_ops

        if self.document is None:
            return
        name = self._dim_style_combo.itemText(index)
        if name and name != style_ops.current_dim_style(self.document):
            self.history.execute(style_ops.SetCurrentDimStyleCommand(name))
            self.command_line.echo(
                tr("Current dimension style: {name}", name=name))
            self.after_style_change()

    def _open_dimstyle_manager(self) -> None:
        """DIMSTYLE — AutoCAD's Dimension Style Manager window."""
        if self.document is None:
            return
        from views.dimstyle_dialog import DimStyleManagerDialog

        DimStyleManagerDialog(self).exec()
        self.after_style_change()

    def after_style_change(self) -> None:
        """Refresh every surface that mirrors the dim style tables."""
        self._refresh_dim_style_combo()
        if getattr(self, "_styles_panel", None) is not None:
            self._styles_panel.refresh()
        self.regen_in_memory()
        self.viewport.update()

    def _scale_target_vp(self):
        """The viewport the scale combo / VPLOCK act on: MSPACE first,
        then the border-selected one."""
        vp = getattr(self, "_active_vp", None)
        if vp is not None and vp.is_alive:
            return vp
        vp = self.tools.paper_vp if getattr(self, "tools", None) else None
        return vp if vp is not None and vp.is_alive else None

    def _on_vp_scale_combo(self, index: int) -> None:
        from core import layouts as layout_ops

        data = self._vp_scale_combo.itemData(index)
        if data is None:
            return
        vp = self._scale_target_vp()
        if vp is None:
            self.command_line.echo(
                tr("Select a viewport (border) or MSPACE first."))
            self._refresh_vp_scale_combo()
            return
        if layout_ops.is_viewport_locked(vp):
            self.command_line.echo(
                tr("Viewport is view-locked — VPLOCK to unlock."))
            self._refresh_vp_scale_combo()
            return
        num, den = data
        self._vp_gesture_commit()
        self.history.execute(layout_ops.xp_zoom_command(vp, num / den))
        self.command_line.echo(tr("Viewport scale set to {scale}.",
                                  scale=layout_ops.scale_label(num / den)))
        self.regen_in_memory()
        self._refresh_vp_scale_combo()

    def _refresh_vp_scale_combo(self) -> None:
        combo = getattr(self, "_vp_scale_combo", None)
        if combo is None:
            return
        from core import layouts as layout_ops

        vp = self._scale_target_vp()
        if vp is None:
            combo.setItemText(0, "")
            combo.setCurrentIndex(0)
            combo.setEnabled(self._active_layout != "Model")
            return
        combo.setEnabled(True)
        factor = layout_ops.viewport_scale(vp)
        for i in range(1, combo.count()):
            num, den = combo.itemData(i)
            if abs(factor - num / den) < 1e-9 * max(1.0, factor):
                combo.setCurrentIndex(i)
                return
        combo.setItemText(0, layout_ops.scale_label(factor))
        combo.setCurrentIndex(0)

    def _refresh_props_toolbar(self) -> None:
        from core import layers as layer_ops
        from views.layers_panel import fill_color_combo, swatch_icon

        self._props_loading = True
        self._layer_combo.clear()
        self._color_combo.clear()
        if self.document is not None:
            for info in layer_ops.layer_list(self.document):
                # small colour chip beside each layer name (BricsCAD look)
                self._layer_combo.addItem(swatch_icon(info.color), info.name)
            current = layer_ops.current_layer_name(self.document)
            idx = self._layer_combo.findText(current)
            if idx >= 0:
                self._layer_combo.setCurrentIndex(idx)
        fill_color_combo(self._color_combo)
        self._fill_linetype_combo()
        self._fill_lineweight_combo()
        self._show_current_properties()
        self._props_loading = False

    def _fill_linetype_combo(self) -> None:
        from core import layers as layer_ops
        from views.layers_panel import linetype_icon

        combo = getattr(self, "_linetype_combo", None)
        if combo is None:
            return
        combo.clear()
        names = ["ByLayer", "ByBlock"]
        if self.document is not None:
            names += [n for n in layer_ops.available_linetypes(self.document)
                      if n not in names]
        for name in names:
            combo.addItem(linetype_icon(name, self.document), name, name)

    def _fill_lineweight_combo(self) -> None:
        from core import layers as layer_ops
        from views.layers_panel import lineweight_icon

        combo = getattr(self, "_lineweight_combo", None)
        if combo is None:
            return
        combo.clear()
        for value in (-1, -2, *layer_ops.LINEWEIGHTS):
            combo.addItem(lineweight_icon(value),
                          tr(layer_ops.lineweight_label(value)), value)

    def _show_current_properties(self) -> None:
        """Reflect either the selection or the current settings, as AutoCAD."""
        from core import layers as layer_ops

        if self.document is None:
            return
        selection = self.tools._selection_entities() if self.tools else []
        for prop, combo in (("color", getattr(self, "_color_combo", None)),
                            ("linetype", getattr(self, "_linetype_combo", None)),
                            ("lineweight",
                             getattr(self, "_lineweight_combo", None))):
            if combo is None:
                continue
            if selection:
                values = {e.dxf.get(prop, layer_ops.CURRENT_DEFAULTS[prop])
                          for e in selection}
                value = values.pop() if len(values) == 1 else None
            else:
                value = layer_ops.current_property(self.document, prop)
            index = combo.findData(value) if value is not None else -1
            combo.setCurrentIndex(index)

    def _on_layer_combo(self, index: int) -> None:
        if getattr(self, "_props_loading", False) or self.document is None:
            return
        from core import layers as layer_ops

        name = self._layer_combo.itemText(index)
        selection = self.tools._selection_entities() if self.tools else []
        if selection:
            from core import actions
            self.history.execute(actions.SetPropertyCommand(selection, "layer", name))
            self.regen_in_memory()
        else:
            layer_ops.set_current_layer(self.document, name)
        self._sync_panels()

    def _on_prop_color(self, index: int) -> None:
        self._apply_property("color", self._color_combo.itemData(index))

    def _on_prop_linetype(self, index: int) -> None:
        self._apply_property("linetype", self._linetype_combo.itemData(index))

    def _on_prop_lineweight(self, index: int) -> None:
        self._apply_property("lineweight",
                             self._lineweight_combo.itemData(index))

    def _apply_property(self, prop: str, value) -> None:
        """The Properties bar rule: change the selection, or set the default.

        With objects selected the combo edits them; with nothing selected it
        sets what the NEXT object will be drawn with ($CECOLOR/$CELTYPE/
        $CELWEIGHT). Same control, two jobs — AutoCAD's, and the reason the
        bar is worth having at all.
        """
        if getattr(self, "_props_loading", False) or self.document is None:
            return
        from core import actions, layers as layer_ops

        selection = self.tools._selection_entities() if self.tools else []
        if selection:
            self.history.execute(
                actions.SetPropertyCommand(selection, prop, value))
            self.regen_in_memory()
            self._sync_panels()
            return
        layer_ops.set_current_property(self.document, prop, value)
        self.command_line.echo(
            tr("Current {prop}: {value}", prop=tr(prop.capitalize()),
               value=self._property_label(prop, value)))

    def _property_label(self, prop: str, value) -> str:
        from core import layers as layer_ops

        if prop == "lineweight":
            return tr(layer_ops.lineweight_label(value))
        if prop == "color":
            from views.layers_panel import ACI_NAMES

            return tr(ACI_NAMES.get(value, str(value)))
        return str(value)

    def _sync_panels(self) -> None:
        if self._layers_panel is not None:
            self._layers_panel.refresh()
        if getattr(self, "_properties_panel", None) is not None:
            self._properties_panel.refresh()
        self._refresh_props_toolbar()

    def _invoke_command(self, name: str) -> None:
        """A toolbar button runs a command like typing it: any running tool
        is cancelled first (AutoCAD interrupts the current command)."""
        if self.tools.active():
            self.tools.cancel()
        self.command_line.echo(f"{tr('Command')}: {name}")
        self.dispatcher.submit(name)
        self.viewport.setFocus()

    def _build_sidebar(self) -> None:
        """Persistent right sidebar: Layers | Properties tabs (bottom tabs)."""
        from PySide6.QtWidgets import QTabWidget

        from views.layers_panel import LayersPanel
        from views.properties_panel import PropertiesPanel
        from views.styles_panel import StylesPanel

        self._layers_panel = LayersPanel(self)
        self._layers_panel.changed.connect(self.viewport.update)
        self._properties_panel = PropertiesPanel(self)
        self.tools.changed.connect(self._properties_panel.refresh)
        self._styles_panel = StylesPanel(self)
        self._styles_panel.changed.connect(self.viewport.update)

        from PySide6.QtWidgets import QHBoxLayout, QToolButton

        tabs = QTabWidget(self)
        tabs.setObjectName("sidebar_tabs")
        tabs.setTabPosition(QTabWidget.South)   # tabs at the bottom (IngeTrazo)
        tabs.addTab(self._layers_panel, tr("Layers"))
        tabs.addTab(self._properties_panel, tr("Properties"))
        tabs.addTab(self._styles_panel, tr("Palette"))
        collapse_btn = QToolButton(tabs)
        collapse_btn.setText("›")
        collapse_btn.setToolTip(tr("Collapse"))
        collapse_btn.clicked.connect(self._collapse_sidebar)
        tabs.setCornerWidget(collapse_btn, Qt.TopRightCorner)
        self._sidebar_tabs = tabs
        self._sidebar_collapsed = False

        # Thin expand strip shown when collapsed.
        self._sidebar_strip = QToolButton(self)
        self._sidebar_strip.setText("‹")
        self._sidebar_strip.setToolTip(tr("Expand"))
        self._sidebar_strip.clicked.connect(self._expand_sidebar)
        self._sidebar_strip.setVisible(False)
        self._sidebar_strip.setFixedWidth(20)

        container = QWidget(self)
        clay = QHBoxLayout(container)
        clay.setContentsMargins(0, 0, 0, 0)
        clay.setSpacing(0)
        clay.addWidget(self._sidebar_strip)
        clay.addWidget(tabs)

        dock = QDockWidget(self)
        dock.setObjectName("sidebar_dock")
        dock.setTitleBarWidget(QWidget(dock))   # no dock chrome
        dock.setFeatures(QDockWidget.NoDockWidgetFeatures)  # fixed, always there
        dock.setWidget(container)
        dock.setMinimumWidth(250)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)
        self.resizeDocks([dock], [280], Qt.Horizontal)
        self._layers_dock = dock

    def _collapse_sidebar(self) -> None:
        self._sidebar_collapsed = True
        self._sidebar_tabs.setVisible(False)
        self._sidebar_strip.setVisible(True)
        self._layers_dock.setMinimumWidth(20)
        self._layers_dock.setFixedWidth(20)

    def _expand_sidebar(self) -> None:
        self._sidebar_collapsed = False
        self._sidebar_strip.setVisible(False)
        self._sidebar_tabs.setVisible(True)
        self._layers_dock.setFixedWidth(280)
        self._layers_dock.setMinimumWidth(250)
        self._layers_dock.setMaximumWidth(16777215)

    def toggle_layers_panel(self) -> None:
        # LA / Format>Layers focuses the Layers tab and refreshes it.
        if self._layers_panel is None:
            return
        if self._sidebar_collapsed:
            self._expand_sidebar()
        self._sidebar_tabs.setCurrentWidget(self._layers_panel)
        self._layers_panel.refresh()

    def toggle_styles_panel(self) -> None:
        # STYLE / DIMSTYLE / Format menu focuses the Styles tab.
        if getattr(self, "_styles_panel", None) is None:
            return
        if self._sidebar_collapsed:
            self._expand_sidebar()
        self._sidebar_tabs.setCurrentWidget(self._styles_panel)
        self._styles_panel.refresh()

    def regen_in_memory(self, zoom_after: bool = False) -> None:
        """Rebuild the scene in a background thread; adopt when done.

        Never blocks the UI: the old scene keeps showing (edits already
        visible via overlay/surgical display) until the fresh one is ready.
        If a regen is in flight, one rerun is queued instead of stacking.
        """
        if self.document is None:
            return
        self._regen_zoom = self._regen_zoom or zoom_after
        if self._regen_worker is not None:
            self._regen_rerun = True
            return
        self._start_regen()

    def _start_regen(self) -> None:
        self._regen_rerun = False
        worker = RegenWorker(self.document, self._active_layout,
                             self.document.revision)
        worker.done.connect(self._on_regen_done)
        self._regen_worker = worker
        worker.start()

    def _on_regen_done(self, document, scene, revision, layout) -> None:
        worker, self._regen_worker = self._regen_worker, None
        if worker is not None:
            worker.wait()   # thread has emitted; joins immediately
        if document is not self.document:
            return          # another file was opened meanwhile
        stale = (self._regen_rerun
                 or scene is None
                 or revision != self.document.revision
                 or layout != self._active_layout)
        if stale:
            self._start_regen()
            return
        self.viewport.set_scene(scene)
        self.tools.mark_scene_merged()
        if self._regen_zoom:
            self._regen_zoom = False
            self.viewport.zoom_extents()

    def _register_commands(self) -> None:
        d = self.dispatcher
        d.register("ZOOM", self._cmd_zoom)
        d.register("PAN", self._cmd_pan)
        d.register("REGEN", self._cmd_regen)
        d.register("U", self._cmd_undo)
        d.register("UNDO", self._cmd_undo)
        d.register("REDO", self._cmd_redo)
        d.register("OPEN", lambda *a: self._open_dialog())
        d.register("SAVEAS", lambda *a: self._save_as_dialog())
        d.register("QUIT", lambda *a: self.close())
        d.register("EXIT", lambda *a: self.close())
        d.register("LAYER", lambda *a: self.toggle_layers_panel())
        d.register("STYLE", lambda *a: self.toggle_styles_panel())
        d.register("DIMSTYLE", lambda *a: self._open_dimstyle_manager())
        d.register("-LAYER", self._cmd_layer_cli)
        d.register("COPYCLIP", lambda *a: self._cmd_copy())
        d.register("CUTCLIP", lambda *a: self._cmd_cut())
        d.register("PASTECLIP", lambda *a: self._cmd_paste())
        d.register("PLOT", lambda *a: self._plot_dialog())
        d.register("PRINT", lambda *a: self._plot_dialog())
        d.register("LAYOUT", self._cmd_layout)
        d.register("MSPACE", self._cmd_mspace)
        d.register("PSPACE", self._cmd_pspace)
        d.register("VPLOCK", self._cmd_vplock)
        d.register("PAGESETUP", self._cmd_pagesetup)
        # Phase 4 drawing + Phase 5 editing tools.
        for name in ("LINE", "CIRCLE", "ARC", "PLINE", "RECTANG", "POLYGON",
                     "ELLIPSE", "POINT", "TEXT", "MTEXT",
                     "ERASE", "MOVE", "COPY", "ROTATE", "SCALE", "MIRROR",
                     "OFFSET", "TRIM", "EXTEND", "FILLET",
                     "BLOCK", "INSERT", "EXPLODE", "HATCH", "-HATCH",
                     "DIMLINEAR", "DIMALIGNED", "DIMRADIUS", "DIMDIAMETER",
                     "DIMANGULAR", "DIMARC", "DIMORDINATE", "DIMCENTER",
                     "DIMCONTINUE", "DIMBASELINE", "DIMTEDIT",
                     "MVIEW", "XLINE", "RAY", "DIVIDE", "MEASURE",
                     "REVCLOUD",
                     "DIST", "ID", "AREA", "LIST",
                     "STRETCH", "BREAK", "JOIN",
                     "CHAMFER", "ARRAY", "MATCHPROP", "PEDIT"):
            d.register(name, lambda *a, n=name: self.tools.start_tool(n))
        d.register("SAVE", lambda *a: self.save_document())
        d.register("QSAVE", lambda *a: self.save_document())
        d.register("UNITS", lambda *a: self._units_dialog())
        d.register("DDUNITS", lambda *a: self._units_dialog())
        d.register("-UNITS", self._cmd_units_cli)
        d.register("LTSCALE", self._cmd_ltscale)
        # In-scope commands that land in later phases: answer honestly.
        for name, phase in (
            ("LINETYPE", 6),
        ):
            d.register_future(name, phase)

    # -- MSPACE / PSPACE (activate a viewport; ZOOM nXP sets its scale) ---------
    def _cmd_mspace(self, *args) -> None:
        from core import layouts as layout_ops

        if self.document is None or self._active_layout == "Model":
            self.command_line.echo(
                tr("MSPACE needs a layout tab with a viewport."))
            return
        layout = self.document.doc.layouts.get(self._active_layout)
        viewports = layout_ops.visible_viewports(layout)
        if not viewports:
            self.command_line.echo(
                tr("No viewports in this layout — create one with MVIEW."))
            return
        self._activate_viewport(viewports[-1])   # topmost, like AutoCAD

    def _cmd_pspace(self, *args) -> None:
        self._deactivate_viewport(echo=True)

    def _cmd_vplock(self, *args) -> None:
        """VPLOCK (BricsCAD): toggle the display lock of the active or
        selected viewport. Optional ON/OFF argument."""
        from core import layouts as layout_ops

        vp = self._active_vp
        if vp is None or not vp.is_alive:
            vp = self.tools.paper_vp
        if vp is None or not vp.is_alive:
            self.command_line.echo(
                tr("VPLOCK needs a viewport — select its border or MSPACE."))
            return
        self._vp_gesture_commit()   # settle any live wheel burst first
        arg = (args[0].strip().upper() if args else "")
        if arg in ("ON", "1"):
            locked = True
        elif arg in ("OFF", "0"):
            locked = False
        else:
            locked = not layout_ops.is_viewport_locked(vp)
        if locked == layout_ops.is_viewport_locked(vp):
            pass    # already in that state: echo it anyway
        else:
            self.history.execute(
                layout_ops.SetViewportLockCommand(vp, locked))
        self.command_line.echo(
            tr("Viewport display locked — the scale is protected.") if locked
            else tr("Viewport display unlocked."))

    def _activate_viewport(self, vp) -> None:
        from core import layouts as layout_ops

        self.tools.clear_selection()      # entering MSPACE deselects (AutoCAD)
        self._active_vp = vp
        self.viewport.active_vp_rect = layout_ops.viewport_rect(vp)
        self.viewport.update()
        label = layout_ops.scale_label(layout_ops.viewport_scale(vp))
        if layout_ops.is_viewport_locked(vp):
            self.command_line.echo(
                tr("Viewport active (scale {scale}, display LOCKED — "
                   "VPLOCK to unlock). PSPACE returns to paper.", scale=label))
        else:
            self.command_line.echo(
                tr("Viewport active (scale {scale}). Z + nXP sets the exact "
                   "scale (e.g. 1/100XP); PSPACE returns to paper.", scale=label))
        self._update_space_button()
        self._refresh_vp_scale_combo()

    # -- wheel/pan navigation inside the active viewport ------------------------
    def vp_view_zoom(self, factor: float, anchor) -> bool:
        """Wheel over the canvas while MSPACE is active: zoom the MODEL
        inside the viewport (at the cursor), not the paper."""
        from core import layouts as layout_ops

        vp = self._active_vp
        if vp is None or not vp.is_alive:
            return False
        if layout_ops.is_viewport_locked(vp):
            return False    # locked: the wheel falls through to the paper
        self._vp_gesture_begin(vp)
        layout_ops.zoom_viewport_view(vp, factor, anchor)
        self.document.dirty = True
        self._vp_gesture_timer.start()
        self.regen_in_memory()          # coalesced; content converges live
        return True

    def vp_view_pan(self, dx_world: float, dy_world: float) -> bool:
        """Middle-drag while MSPACE is active: pan the model in the viewport."""
        from core import layouts as layout_ops

        vp = self._active_vp
        if vp is None or not vp.is_alive:
            return False
        if layout_ops.is_viewport_locked(vp):
            return False    # locked: the drag falls through to the paper
        self._vp_gesture_begin(vp)
        layout_ops.pan_viewport_view(vp, dx_world, dy_world)
        self.document.dirty = True
        self._vp_gesture_timer.start()
        self.regen_in_memory()
        return True

    def _vp_gesture_begin(self, vp) -> None:
        if self._vp_gesture is None:
            self._vp_gesture = (
                vp,
                (vp.dxf.view_center_point.x, vp.dxf.view_center_point.y),
                float(vp.dxf.view_height))

    def _vp_gesture_commit(self) -> None:
        """Fold the finished wheel/pan burst into one undoable Command."""
        from core import layouts as layout_ops

        gesture, self._vp_gesture = self._vp_gesture, None
        self._vp_gesture_timer.stop()
        if gesture is None:
            return
        vp, old_center, old_height = gesture
        if not vp.is_alive:
            return
        now_center = (vp.dxf.view_center_point.x, vp.dxf.view_center_point.y)
        now_height = float(vp.dxf.view_height)
        if now_center == old_center and now_height == old_height:
            return
        # do() re-applies the values already live — recording, not changing.
        self.history.execute(layout_ops.SetViewportViewCommand(
            vp, view_center=now_center, view_height=now_height,
            name=tr("Viewport view"),
            old_center=old_center, old_height=old_height))

    def _deactivate_viewport(self, echo: bool = False) -> None:
        self._vp_gesture_commit()       # leaving MSPACE settles the gesture
        had = getattr(self, "_active_vp", None) is not None
        self._active_vp = None
        if getattr(self.viewport, "active_vp_rect", None) is not None:
            self.viewport.active_vp_rect = None
            self.viewport.update()
        if echo:
            self.command_line.echo(
                tr("Paper space.") if had
                else tr("Already in paper space."))
        self._update_space_button()
        self._refresh_vp_scale_combo()

    def on_canvas_double_click(self, wx: float, wy: float) -> None:
        """AutoCAD: double-click inside a viewport enters it (MSPACE),
        double-click on empty paper leaves it (PSPACE)."""
        from core import layouts as layout_ops

        if self.document is None or self._active_layout == "Model":
            return
        layout = self.document.doc.layouts.get(self._active_layout)
        vp = layout_ops.viewport_hit(layout, wx, wy)
        if vp is not None:
            self._activate_viewport(vp)
        else:
            self._deactivate_viewport(echo=True)

    def _cmd_pagesetup(self, *args) -> None:
        """PAGESETUP: paper/orientation/margins of the current layout tab."""
        from core import layouts as layout_ops
        from views.page_setup_dialog import PageSetupDialog

        if self.document is None:
            self.new_document()
        name = self._active_layout
        if name == "Model":
            self.command_line.echo(
                tr("PAGESETUP works on a layout tab — switch to one first."))
            return
        layout = self.document.doc.layouts.get(name)
        dialog = PageSetupDialog(self, layout)
        if not dialog.exec():
            return
        values = dialog.values()
        width, height = values.pop("width"), values.pop("height")
        self.history.execute(layout_ops.page_setup_command(
            layout, width, height, values.pop("margins"),
            values.pop("size_name"), **values))
        self.regen_in_memory(zoom_after=True)   # the sheet changed size
        self.command_line.echo(
            tr("Page setup applied to \"{name}\": {w:g} × {h:g} mm.",
               name=name, w=width, h=height))

    def _cmd_layout(self, *args) -> Prompt | None:
        """LAYOUT — AutoCAD keywords, headless flow in core.layouts."""
        if self.document is None:
            self.new_document()
        from core import layouts as layout_ops

        return layout_ops.layout_command(
            self.document, self.history,
            switch=self.switch_layout,
            echo=self.command_line.echo,
            refresh=self._sync_layout_tabs,
            current=lambda: self._active_layout,
            args=args)

    def _cmd_layer_cli(self, *args) -> Prompt | None:
        """-LAYER — the command-line layer flow (official keywords)."""
        if self.document is None:
            self.new_document()
        from core import layers as layer_ops

        def refresh() -> None:
            if self._layers_panel is not None:
                self._layers_panel.refresh()
            self._refresh_props_toolbar()
            self.regen_in_memory()
            self.viewport.update()

        return layer_ops.layer_command(
            self.document, self.history,
            echo=self.command_line.echo, refresh=refresh, args=args)

    # -- UNITS / LTSCALE (drawing settings that live in the DXF header) --------
    def _header_value(self, name: str, default):
        if self.document is None:
            return default
        try:
            return self.document.doc.header[name]
        except Exception:
            return default

    def _apply_units(self, units, angdir: int, angbase: float) -> None:
        from core.units import LINEAR_NAMES

        doc = self.document.doc
        units.to_doc(doc)
        doc.header["$ANGDIR"] = int(angdir)
        doc.header["$ANGBASE"] = float(angbase)
        self._units_revision = getattr(self, "_units_revision", 0) + 1
        self.document.dirty = True
        self.command_line.echo(
            tr("Units: {type}, precision {precision}, "
               "insertion scale {scale}",
               type=tr(LINEAR_NAMES.get(units.lunits, "Decimal")),
               precision=units.luprec, scale=tr(units.unit_name)))

    def _units_dialog(self, *args) -> None:
        if self.document is None:
            self.new_document()
        from core.units import Units
        from views.units_dialog import UnitsDialog

        dialog = UnitsDialog(
            self, Units.from_doc(self.document.doc),
            angdir=int(self._header_value("$ANGDIR", 0) or 0),
            angbase=float(self._header_value("$ANGBASE", 0.0) or 0.0))
        if dialog.exec():
            self._apply_units(dialog.values(), dialog.angdir(), dialog.angbase())

    def _cmd_units_cli(self, *args) -> Prompt | None:
        """-UNITS — the prompt sequence, for the keyboard-only flow."""
        if self.document is None:
            self.new_document()
        from core.units import Units, units_command

        return units_command(
            Units.from_doc(self.document.doc),
            echo=self.command_line.echo,
            apply=self._apply_units,
            angdir=int(self._header_value("$ANGDIR", 0) or 0),
            angbase=float(self._header_value("$ANGBASE", 0.0) or 0.0),
            args=args)

    def _cmd_ltscale(self, *args) -> Prompt | None:
        """LTSCALE — global linetype scale; changing it regenerates."""
        if self.document is None:
            self.new_document()
        from core.units import ltscale_command

        def apply(value: float) -> None:
            self.document.doc.header["$LTSCALE"] = value
            self.document.dirty = True
            self.command_line.echo(tr("Regenerating model."))
            self.regen_in_memory()
            self.viewport.update()

        return ltscale_command(
            float(self._header_value("$LTSCALE", 1.0) or 1.0),
            echo=self.command_line.echo, apply=apply, args=args)

    # ZOOM [Extents/Window/Previous/nXP]
    def _cmd_zoom(self, *args) -> Prompt | None:
        if args:
            return self._zoom_option(args[0])
        if getattr(self, "_active_vp", None) is not None:
            return Prompt(tr("ZOOM [Extents/Window/Previous] or scale nXP:"),
                          self._zoom_option)
        return Prompt(tr("ZOOM [Extents/Window/Previous] <Extents>:"),
                      self._zoom_option)

    def _zoom_option(self, option: str) -> None:
        from core import layouts as layout_ops

        active_vp = getattr(self, "_active_vp", None)
        if active_vp is not None and not active_vp.is_alive:
            active_vp = None
            self._deactivate_viewport()
        if active_vp is not None:
            # a pending wheel/pan burst must land in history BEFORE the
            # explicit ZOOM command, so undo peels them in order
            self._vp_gesture_commit()
        if active_vp is not None and layout_ops.is_viewport_locked(active_vp) \
                and (layout_ops.parse_xp_factor(option) is not None
                     or option.strip().upper() in ("", "E", "EXTENTS")):
            # AutoCAD: a display-locked viewport keeps its view.
            self.command_line.echo(
                tr("Viewport is view-locked — VPLOCK to unlock."))
            return
        factor = layout_ops.parse_xp_factor(option)
        if factor is not None:
            # AutoCAD's exact-scale idiom: ZOOM 1/100XP inside a viewport.
            if active_vp is None:
                self.command_line.echo(
                    tr("nXP needs an active viewport — MSPACE or "
                       "double-click one first."))
                return
            self.history.execute(layout_ops.xp_zoom_command(active_vp, factor))
            self.command_line.echo(tr("Viewport scale set to {scale}.",
                                      scale=layout_ops.scale_label(factor)))
            self.regen_in_memory()
            return
        opt = option.strip().upper() or "E"
        if opt in ("E", "EXTENTS"):
            if active_vp is not None:
                # inside a viewport, Extents fits the MODEL in it
                self.history.execute(
                    layout_ops.viewport_fit_command(self.document, active_vp))
                self.regen_in_memory()
                return
            self.viewport.zoom_extents()
        elif opt in ("W", "WINDOW"):
            self.viewport.start_zoom_window()
            self.command_line.echo(tr("Drag a window in the viewport"))
        elif opt in ("P", "PREVIOUS"):
            if not self.viewport.zoom_previous():
                self.command_line.echo(tr("No previous view"))
        else:
            self.command_line.echo(tr('Unknown ZOOM option "{name}".', name=opt))

    def _cmd_regen(self, *args) -> None:
        if self.document is None:
            self.command_line.echo(tr("Nothing to regenerate"))
            return
        self.regen_in_memory()
        self.command_line.echo(tr("Regenerating..."))

    def _cmd_undo(self, *args) -> None:
        command = self.history.undo()
        self.command_line.echo(
            tr("Undo: {name}", name=command.name) if command else tr("Nothing to undo"))
        if command is not None:
            self.tools.after_history_change(command)
            self._sync_layout_tabs()

    def _cmd_redo(self, *args) -> None:
        command = self.history.redo()
        self.command_line.echo(
            tr("Redo: {name}", name=command.name) if command else tr("Nothing to redo"))
        if command is not None:
            self.tools.after_history_change(command)
            self._sync_layout_tabs()

    def _build_status_bar(self) -> None:
        from PySide6.QtWidgets import QHBoxLayout, QToolButton

        # Model / layout tabs, bottom-left on the coordinates row (BricsCAD).
        self._active_layout = "Model"
        self._layout_tab_host = QWidget(self)
        self._layout_tab_bar = QHBoxLayout(self._layout_tab_host)
        self._layout_tab_bar.setContentsMargins(0, 0, 6, 0)
        self._layout_tab_bar.setSpacing(1)
        self.statusBar().addWidget(self._layout_tab_host)

        # Coordinate readout — the classic AutoCAD tracker. It doubles as the
        # progress line while a drawing opens: see _set_busy. Nothing else may
        # write here: notices ("Saved x", "Opened x", F8 toggles) go to the
        # command line, which is where an AutoCAD user reads them and which
        # keeps them in the history instead of expiring after five seconds.
        # A QStatusBar temporary message would hide this label, so any use of
        # showMessage() costs the coordinate readout for as long as it shows.
        self._busy_text = ""
        self._coords_label = QLabel("0.0000, 0.0000")
        self._coords_label.setMinimumWidth(220)
        self.statusBar().addWidget(self._coords_label)
        self.statusBar().addPermanentWidget(QLabel(f"IngeCAD {__version__}"))
        self._refresh_layout_tabs()

    _TAB_STYLE = """
    QToolButton { border: 1px solid #3a3a42; border-bottom: none;
        padding: 1px 10px; color: #9a9a9a; font-size: 11px;
        background: #2a2a2e; }
    QToolButton:hover { color: #d0d0d0; }
    QToolButton:checked { color: #f0f0f0; background: #35424f;
        font-weight: bold; }
    """

    def _layout_names(self) -> list:
        if self.document is None:
            return ["Model"]
        from core import layouts as layout_ops

        return layout_ops.layout_names(self.document)

    def _refresh_layout_tabs(self) -> None:
        from PySide6.QtWidgets import QToolButton

        while self._layout_tab_bar.count():
            w = self._layout_tab_bar.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        self._tab_buttons: dict = {}
        for name in self._layout_names():
            b = QToolButton(self._layout_tab_host)
            b.setText(tr("Model") if name == "Model" else name)
            b.setCheckable(True)
            b.setChecked(name == self._active_layout)
            b.setStyleSheet(self._TAB_STYLE)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _=False, n=name: self.switch_layout(n))
            b.setContextMenuPolicy(Qt.CustomContextMenu)
            b.customContextMenuRequested.connect(
                lambda pos, n=name, btn=b: self._layout_tab_menu(
                    n, btn.mapToGlobal(pos)))
            self._tab_buttons[b] = name
            self._layout_tab_bar.addWidget(b)
        plus = QToolButton(self._layout_tab_host)
        plus.setText("+")
        plus.setToolTip(tr("New layout"))
        plus.setStyleSheet(self._TAB_STYLE)
        plus.setFocusPolicy(Qt.NoFocus)
        plus.clicked.connect(self._new_layout_tab)
        self._layout_tab_bar.addWidget(plus)

    def switch_layout(self, name: str) -> None:
        """Model/Layout tabs: re-render the chosen space (AutoCAD tabs)."""
        if (self.document is None or name == self._active_layout
                or name not in self._layout_names()):
            self._refresh_layout_tabs()   # re-sync checked states
            return
        from core import layouts as layout_ops

        self.tools.cancel()               # drop tool/selection across spaces
        self._deactivate_viewport()       # MSPACE state is per-tab
        # $TILEMODE + the *Paper_Space block dance, so the file reopens on
        # this tab in AutoCAD too (ezdxf does not touch the header itself).
        layout_ops.switch_active(self.document, name)
        self._active_layout = name
        self.regen_in_memory(zoom_after=True)   # zooms when the scene lands
        self._refresh_layout_tabs()
        self._update_space_button()
        if name != "Model":
            self.command_line.echo(
                tr("Layout \"{n}\" — MVIEW adds a viewport, MSPACE works "
                   "inside it, PSPACE returns to the sheet.", n=name))

    # -- layout tab operations (right-click menu / + button) --------------------
    def _layout_tab_menu(self, name: str, global_pos) -> None:
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        menu.addAction(tr("New layout"), self._new_layout_tab)
        if name != "Model":   # AutoCAD: the Model tab is fixed
            menu.addAction(tr("Delete"),
                           lambda: self._delete_layout_tab(name))
            menu.addAction(tr("Rename"),
                           lambda: self._rename_layout_tab(name))
            menu.addSeparator()
            # AutoCAD's tab menu carries these two as well.
            menu.addAction(tr("Page Setup..."),
                           lambda: self._page_setup_for_tab(name))
            menu.addAction(tr("Plot..."), self._plot_dialog)
        menu.exec(global_pos)

    def _page_setup_for_tab(self, name: str) -> None:
        # right-click targets a tab that may not be the active one: switch
        # first (AutoCAD's Page Setup Manager also acts on the current tab)
        if name != self._active_layout:
            self.switch_layout(name)
        self._cmd_pagesetup()

    def _new_layout_tab(self) -> None:
        if self.document is None:
            self.new_document()
        from core import layouts as layout_ops

        name = layout_ops.default_new_name(self.document)
        self.history.execute(layout_ops.NewLayoutCommand(name))
        # AutoCAD adds the tab without activating it.
        self._refresh_layout_tabs()
        self.command_line.echo(tr('Layout "{name}" created.', name=name))

    def _rename_layout_tab(self, name: str) -> None:
        from PySide6.QtWidgets import QInputDialog

        from core import layouts as layout_ops

        new, ok = QInputDialog.getText(
            self, tr("Rename Layout"), tr("New layout name:"), text=name)
        if not ok or not new.strip() or new.strip() == name:
            return
        new = new.strip()
        problem = layout_ops.validate_new_name(self.document, new)
        if problem:
            self.command_line.echo(problem)
            return
        self.history.execute(layout_ops.RenameLayoutCommand(name, new))
        if self._active_layout == name:
            self._active_layout = new
        self._refresh_layout_tabs()

    def _delete_layout_tab(self, name: str) -> None:
        from ezdxf.lldxf.const import DXFValueError

        from core import layouts as layout_ops

        # AutoCAD's own warning: layout deletion is permanent (not undoable —
        # a faithful undo would need to snapshot every entity on the sheet).
        answer = QMessageBox.question(
            self, tr("Delete Layout"),
            tr('Layout "{name}" and everything on it will be permanently '
               "deleted. Continue?", name=name),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        was_active = self._active_layout == name
        try:
            layout_ops.delete_layout(self.document, name)
        except DXFValueError:
            self.command_line.echo(tr("The last layout cannot be deleted."))
            return
        self.command_line.echo(tr('Layout "{name}" deleted.', name=name))
        if was_active:
            self._active_layout = ""      # force the switch to re-render
            self.switch_layout("Model")
        else:
            self._refresh_layout_tabs()

    def _sync_layout_tabs(self) -> None:
        """After undo/redo: the tab set may have changed under the UI."""
        if self.document is None:
            return
        names = self._layout_names()
        if self._active_layout not in names:
            from core import layouts as layout_ops

            # Renamed or deleted: the document knows which paperspace is
            # current; fall back to Model otherwise.
            self._active_layout = layout_ops.startup_tab(self.document) or "Model"
            self.regen_in_memory(zoom_after=True)
        self._refresh_layout_tabs()

    def _set_busy(self, text: str) -> None:
        """Show (or clear, with "") a long operation on the coordinates line.

        Progress goes where the coordinates go, on purpose: there is one text
        in that spot at a time and never two competing for the same pixels.
        A status bar *message* cannot be used for it — QStatusBar paints the
        message over the whole left area and only hides the widgets underneath
        when they happen to be visible already, so it collides at startup.
        And there is nothing to track while the drawing is still loading.
        """
        self._busy_text = text
        self._coords_label.setText(text or "0.0000, 0.0000")

    def display_units(self):
        """The drawing's units, cached — this is read on every mouse move.

        The cache key is the document plus a counter UNITS bumps, so the
        readout follows a units change immediately without re-reading five
        header variables per pixel of cursor travel.
        """
        from core.units import Units

        key = (self.document, getattr(self, "_units_revision", 0))
        if getattr(self, "_units_cache_key", None) != key:
            self._units_cache = (Units.from_doc(self.document.doc)
                                 if self.document is not None else Units())
            self._units_cache_key = key
        return self._units_cache

    def _on_cursor_moved(self, wx: float, wy: float) -> None:
        if self._busy_text:
            return          # the coordinates line is showing progress
        units = self.display_units()
        self._coords_label.setText(f"{units.length(wx)}, {units.length(wy)}")

    # -- documents -------------------------------------------------------------
    def _open_dialog(self) -> None:
        filename, _filter = QFileDialog.getOpenFileName(
            self,
            tr("Open Drawing"),
            "",
            tr("Drawings (*.dwg *.dxf);;All files (*)"),
        )
        if filename:
            self.open_path(Path(filename))

    def _save_as_dialog(self) -> None:
        if self.document is None:
            self.command_line.echo(tr("Nothing to save yet"))
            return
        filename, selected = QFileDialog.getSaveFileName(
            self,
            tr("Save Drawing As"),
            self.document.name,
            tr("DWG (*.dwg);;DXF (*.dxf)"),
        )
        if not filename:
            return
        path = Path(filename)
        if path.suffix.lower() not in (".dwg", ".dxf"):
            path = path.with_suffix(".dwg" if "dwg" in selected.lower() else ".dxf")
        self._write_document(path)

    def save_document(self) -> None:
        """SAVE / QSAVE / Ctrl+S — write over the file that is open.

        A drawing that has never been written has nowhere to go, so it falls
        through to Save As, which is what AutoCAD does with an unnamed
        drawing.
        """
        if self.document is None:
            self.command_line.echo(tr("Nothing to save yet"))
            return
        if self.document.path is None:
            self._save_as_dialog()
            return
        self._write_document(self.document.path)

    def _write_document(self, path: Path) -> None:
        """The shared tail of SAVE and SAVEAS: write, report, warn."""
        if self.document is None:
            return
        try:
            engine, warnings = self.document.save_as(path)
        except Exception as exc:
            QMessageBox.warning(
                self,
                tr("Save Drawing"),
                tr("Cannot save {name}: {error}", name=path.name, error=str(exc)),
            )
            return
        from core import recent as recent_mod

        recent_mod.add(path)
        self._refresh_recent_menu()
        self.setWindowTitle(f"IngeCAD — {self.document.name}")
        if engine == "libredwg":
            # r2000 opens in every AutoCAD/BricsCAD since 2000. Paperspace
            # layout settings are simplified on the way out (older container).
            self.command_line.echo(
                tr("Saved {name} (DWG r2000)", name=path.name))
        else:
            self.command_line.echo(tr("Saved {name}", name=path.name))
        # Verified save: the file is written either way, but if the DWG did not
        # check out, tell the user up front (non-blocking) and offer DXF, which
        # is always exact. Never leave a possibly-bad DWG shipped silently.
        if warnings:
            detail = "\n".join(f"• {w}" for w in warnings)
            QMessageBox.warning(
                self,
                tr("Saved with a warning"),
                tr("{name} was saved, but the DWG check found a possible "
                   "problem:\n\n{detail}\n\nIf a colleague cannot open it, save "
                   "as DXF instead — DXF is always exact.",
                   name=path.name, detail=detail),
            )

    def open_path(self, path: Path, as_template: bool = False) -> None:
        """OS file associations, argv[1], and File > Open land here.

        ``as_template`` keeps the content and drops the origin, so the drawing
        becomes an unnamed new one.
        """
        self._open_as_template = bool(as_template)
        if path.suffix.lower() == ".dwg":
            from formats.dwg_bridge import have_dwg_support

            if not have_dwg_support():
                QMessageBox.warning(
                    self,
                    tr("Open Drawing"),
                    tr("DWG support needs the LibreDWG converter (dwg2dxf), "
                       "which was not found."),
                )
                return
        if self._open_thread is not None:
            self.command_line.echo(tr("Still opening the previous drawing..."))
            return
        self._opening_name = path.name
        self._set_busy(tr("Opening {name}...", name=path.name))
        thread = QThread(self)
        worker = _OpenWorker(path)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_open_done)
        worker.failed.connect(self._on_open_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._on_open_thread_finished)
        self._open_thread = thread
        self._open_worker = worker  # keep alive while the thread runs
        thread.start()

    def _on_open_done(self, document: Document, scene) -> None:
        from core import recent as recent_mod

        self._set_busy("")
        if getattr(self, "_open_as_template", False):
            document.path = None          # a template has no file of its own
            document.dirty = True
        elif document.path is not None:
            recent_mod.add(document.path)
            self._refresh_recent_menu()
        self._open_as_template = False
        self.document = document
        self._deactivate_viewport()
        # the open may have fallen back to a paper layout (empty modelspace)
        self._active_layout = scene.layout_name or "Model"
        self._refresh_layout_tabs()
        self._update_space_button()
        self.viewport.set_scene(scene)
        self.viewport.zoom_extents()
        self.tools.attach_document(document, flatten=scene.flatten)
        if self._layers_panel is not None:
            self._layers_panel.refresh()   # show the opened drawing's layers
        if getattr(self, "_styles_panel", None) is not None:
            self._styles_panel.refresh()   # and its text/dimension styles
        if getattr(self, "_props_toolbar", None) is not None:
            self._refresh_props_toolbar()
        self.setWindowTitle(f"IngeCAD — {document.name}")
        if scene.layout_name:
            # Saved on a layout tab ($TILEMODE) or empty modelspace fallback.
            self.command_line.echo(
                tr("Opened {name} — showing layout \"{layout}\"",
                   name=document.name, layout=scene.layout_name))
        elif scene.skipped:
            self.command_line.echo(
                tr("Opened {name} — {count} damaged entities could not be drawn",
                   name=document.name, count=len(scene.skipped)))
        else:
            self.command_line.echo(tr("Opened {name}", name=document.name))

    def _on_open_failed(self, error: str) -> None:
        self._set_busy("")
        QMessageBox.warning(
            self,
            tr("Open Drawing"),
            tr("Cannot open {name}: {error}", name=self._opening_name, error=error),
        )

    def _on_open_thread_finished(self) -> None:
        # Only the progress line is ours to clear here; the temporary message
        # is the "Opened X" confirmation _on_open_done just posted, and this
        # runs microseconds later -- clearing it wiped it before it was read.
        self._set_busy("")
        if self._open_thread is not None:
            self._open_thread.deleteLater()
        self._open_thread = None
        self._open_worker = None
