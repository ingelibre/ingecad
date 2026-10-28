# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""IngeCAD main window — classic pre-ribbon layout.

Menu bar + (from Phase 3) dockable toolbars, command line at the bottom, and a
status bar with coordinate readout and mode toggles. The ribbon does not exist
and will never exist here.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (QEvent, QPoint, QSettings, Qt,
                            QThread, QTimer, Signal)
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDockWidget,
    QLabel,
    QMainWindow,
    QMenu,
    QMenuBar,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from core import gc_guard
from core import i18n
from core.actions import Dispatcher, Prompt
from core.commands import History
from core.document import Document, DocumentError
from core.i18n import tr
from views import file_dialogs
from views.command_line import CommandLine
from views.document_tabs import DocumentTabsMixin
from views.title_bar import TitleBar
from core.version import __version__
from views.viewport import Viewport

SETTING_SIDEBAR_SHOWN = "ui/sidebar_shown"
SETTING_SIDEBAR_WIDTH = "ui/sidebar_width"
#: The Linetype control's last entry, "Other...", which opens the manager.
_OTHER_LINETYPE = "\x00other"


class _OpenWorker(QThread):
    """Loads and regens a drawing off the UI thread.

    Real plans take seconds (a colleague's 4.5 MB pavement sheet froze the UI
    for minutes before the hatch density cap) — the window must stay alive.
    Only plain Python/ezdxf objects cross the thread boundary.

    A QThread subclass like every other worker. It was a QObject moved to a
    QThread, the one worker of that shape -- and every crash the CI caught
    (a SIGBUS destroying it on its own thread, segfaults delivering posted
    events on the GUI thread) happened while a drawing opened. This object
    lives on the GUI thread its whole life; only run() is elsewhere.
    """

    done = Signal(object, object)   # Document, Scene
    failed = Signal(str)            # error text
    phase = Signal(str)             # English source text of the phase (tr'd by the window)

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.setObjectName("open-drawing")
        self._path = path

    def run(self) -> None:
        from core import gc_guard

        # every worker under gc_guard.paused(): without it the collector
        # ran on this thread -- 106 collections while opening a small
        # drawing with thresholds lowered, any of which may destroy a GUI
        # object off the GUI thread
        with gc_guard.paused():
            self._run()

    def _run(self) -> None:
        from formats.dwg_bridge import DwgBridgeError, load_dwg
        from render.backend import build_scene

        try:
            if self._path.suffix.lower() == ".dwg":
                # Transparent conversion: the user never sees the temp DXF.
                self.phase.emit("Converting the DWG...")
                document = load_dwg(self._path, progress=self.phase.emit)
            else:
                self.phase.emit("Reading the drawing...")
                document = Document.load(self._path)
            self.phase.emit("Regenerating...")
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
        self.setObjectName("regen")       # names the thread in Qt's aborts
        self._document = document
        self._layout = layout
        self._revision = revision

    def run(self) -> None:
        from core import gc_guard

        with gc_guard.paused():      # never collect Qt garbage off the GUI thread
            self._run()

    def _run(self) -> None:
        import time

        from render.backend import build_scene

        t0 = time.perf_counter()
        try:
            scene = build_scene(self._document, self._layout)
        except Exception:
            scene = None    # doc mutated mid-read (or bad data): stale
        # Measured cost of this layout's regen: the viewport pan/zoom path
        # uses it to decide whether a live synchronous rebuild is affordable.
        self.duration_ms = (time.perf_counter() - t0) * 1000.0
        self.done.emit(self._document, scene, self._revision, self._layout)


class _LiveSceneWorker(QThread):
    """The model tessellated for live navigation inside a viewport, off the
    UI thread: on a real plan the first pan tick built it synchronously
    (5.8 s frozen, Planos Constructivos). It starts when the viewport is
    activated, so by the time the user drags it is usually ready."""

    done = Signal(object, object)          # key, scene | None

    def __init__(self, document: Document, layout_name: str, key) -> None:
        super().__init__()
        self.setObjectName("vp-live")
        self._document = document
        self._layout_name = layout_name
        self._key = key

    def run(self) -> None:
        from core import gc_guard

        with gc_guard.paused():      # never collect Qt garbage off the GUI thread
            from render.backend import build_scene

            try:
                sheet = self._document.doc.layouts.get(self._layout_name)
                scene = build_scene(self._document, "Model", canvas=sheet)
            except Exception:                 # noqa: BLE001 - the sync path will say
                scene = None
            self.done.emit(self._key, scene)


class _AutoSaveWorker(QThread):
    """Writes the drawing to its .sv$ file off the UI thread.

    A real plan takes 1.0-2.2 s to serialise (measured), and a freeze that
    long every ten minutes is exactly what the automatic save is not
    allowed to cost. The document must not change while this runs, which
    is what MainWindow's mutation gate is for.
    """

    done = Signal(bool, str)     # ok, message

    def __init__(self, document, sv_path, info_path) -> None:
        super().__init__()
        self.setObjectName("autosave")
        self._document = document
        self._sv = Path(sv_path)
        self._info = Path(info_path)

    def run(self) -> None:
        from core import gc_guard

        with gc_guard.paused():      # never collect Qt garbage off the GUI thread
            self._run()

    def _run(self) -> None:
        from core import autosave

        temporary = self._sv.with_suffix(self._sv.suffix + ".part")
        try:
            self._sv.parent.mkdir(parents=True, exist_ok=True)
            self._document.doc.saveas(str(temporary))
            temporary.replace(self._sv)     # atomic: never a half file
            autosave.write_info(self._info, self._document.path,
                                len(self._document.doc.entitydb))
        except Exception as exc:            # a failed autosave is not fatal
            try:
                temporary.unlink()
            except OSError:
                pass
            self.done.emit(False, str(exc))
            return
        self.done.emit(True, str(self._sv))


class _SaveWorker(QThread):
    """A save, off the UI thread: the intermediate DXF ezdxf writes (2 s on
    Plaza Yanque, 10 000 objects), LibreDWG's conversion and the check that
    reads the result back (7.7 s) -- the ~10 s Ctrl+S used to freeze the
    window for. It only READS the drawing, and nothing can change the
    drawing meanwhile: the window holds keyboard and mouse until it ends."""

    def __init__(self, finish) -> None:
        super().__init__()
        self.setObjectName("save")
        self._finish = finish
        self.result = None
        self.error = None            # the exception, if it failed

    def run(self) -> None:
        from core import gc_guard

        with gc_guard.paused():      # never collect Qt garbage off the GUI thread
            try:
                self.result = self._finish()
            except Exception as exc:  # noqa: BLE001 - reported on the GUI thread
                self.error = exc


class _InputHold(QWidget):
    """Holds keyboard, mouse and shortcuts while a save runs, as AutoCAD
    does: an application-modal window, invisible and never active. Qt
    itself then drops the input of every other window -- the main one, the
    floating toolbars, the shortcuts -- without a line of Python per event
    (an app-wide event filter did it before, and cost the window a second
    of GIL waits per save)."""

    def __init__(self, parent) -> None:
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint
                         | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowModality(Qt.ApplicationModal)
        self.setGeometry(parent.x(), parent.y(), 1, 1)


#: QSettings key of the main window's geometry (saveGeometry()).
SETTING_WINDOW_GEOMETRY = "ui/window_geometry"


class _LayoutTabHost(QWidget):
    """The Model/layout tab row: asks for the width of every tab, even
    while some wait behind "…"."""

    full_width = 0

    def sizeHint(self):
        hint = super().sizeHint()
        hint.setWidth(max(hint.width(), self.full_width))
        return hint


def _lineweight_name(value: int) -> str:
    return {-1: "ByLayer", -2: "ByBlock", -3: "Default"}.get(
        int(value), f"{int(value) / 100:.2f} mm")


class MainWindow(DocumentTabsMixin, QMainWindow):
    # A live viewport regen must fit a frame-ish budget or pan blocks the UI.
    _VP_LIVE_BUDGET_MS = 33.0

    #: Backing store of :attr:`_active_layout`. A class attribute so the
    #: property answers before __init__ has run a line.
    _active_layout_name = "Model"

    @property
    def _active_layout(self) -> str:
        """The current tab: "Model" or a layout name.

        Writing it also tells the DOCUMENT which space is current, and that
        is the whole point of the property: paper-space editing works because
        ``Document.current_space()`` follows the tab, and the two must never
        be able to drift apart. Seven places set the tab; none of them has to
        remember.
        """
        return self._active_layout_name

    @_active_layout.setter
    def _active_layout(self, name: str) -> None:
        self._active_layout_name = name
        self._sync_document_space()

    #: Backing store of :attr:`_active_vp`, for the same reason.
    _active_vp_entity = None

    @property
    def _active_vp(self):
        """The viewport MSPACE activated, or None while the sheet is current.

        A property for the same reason the tab is one: inside a viewport the
        current space is the MODELSPACE -- that is what MSPACE means -- and
        the document has to hear it, or a command would edit the sheet while
        the user is drawing in the model.
        """
        return self._active_vp_entity

    @_active_vp.setter
    def _active_vp(self, vp) -> None:
        self._active_vp_entity = vp
        self._sync_document_space()

    def _sync_document_space(self) -> None:
        """Tell the document which space is current: model, sheet, or the
        model reached through an activated viewport."""
        document = getattr(self, "document", None)
        if document is None:
            return
        name = self._active_layout_name
        if self._active_vp_entity is not None:
            document.active_layout = None       # MSPACE: the model is current
        else:
            document.active_layout = None if name in ("Model", "") else name

    def __init__(self) -> None:
        super().__init__()
        # Closing a window destroys it. Without this close() only hid it,
        # and the lambdas its menus and toolbars connect to its signals
        # live on the C++ side, out of the collector's reach: every closed
        # window stayed in memory with its thousands of widgets. 135 tests
        # left 63 windows and 1 GB behind, and every later processEvents
        # walked them -- why v0.6.5's CI ran 3.4x longer than v0.6.4's.
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.document: Document | None = None
        self._regen_worker: RegenWorker | None = None
        self._regen_rerun = False
        self._regen_zoom = False
        # Measured regen cost per layout (ms): whether a live synchronous
        # rebuild is affordable during a viewport pan/zoom gesture.
        self._regen_ms: dict[str, float] = {}
        #: layout name -> (document revision, built Scene). Serves ONLY the
        #: Model/Layout tab switch: every other regen request means "the
        #: scene is stale" and empties it (display settings such as VIEWRES
        #: change the tessellation without touching the revision, so the
        #: revision alone cannot be trusted as the cache key).
        self._layout_scenes: dict[str, tuple[int, object]] = {}
        #: layout name -> (cx, cy, scale): the view each Model/Layout tab was
        #: left with, as AutoCAD keeps one per tab (core/saved_views.py)
        self._layout_cameras: dict[str, tuple[float, float, float]] = {}
        #: the layout whose regen should land on that tab's own view
        self._regen_view_for: str | None = None
        self._layers_dock = None
        self._layers_panel = None
        self._active_vp = None    # MSPACE-activated viewport entity, if any
        # Automatic save (SAVETIME): the timer starts when the drawing is
        # first changed and is reset by a real save, exactly as AutoCAD
        # documents it. The write itself runs on a worker.
        self._autosave_worker = None
        self._save_worker = None
        #: When the drawing last changed. The automatic save waits for a
        #: pause, so the one moment it can make the app wait -- an edit
        #: landing while the file is being written -- almost never arrives.
        self._last_mutation = 0.0
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.timeout.connect(self._autosave_tick)
        # Wheel/pan inside the active viewport mutate its view live; ONE
        # Command is committed when the gesture settles (AutoCAD groups
        # zooms too). Holds (vp, old_view_center, old_view_height).
        self._vp_gesture = None
        self._vp_gesture_timer = QTimer(self)
        self._vp_gesture_timer.setSingleShot(True)
        self._vp_gesture_timer.setInterval(700)
        self._vp_gesture_timer.timeout.connect(self._vp_gesture_commit)
        self._open_thread: QThread | None = None
        self._pending_opens: list[Path] = []   # see open_paths
        self._open_worker: _OpenWorker | None = None
        self._opening_name = ""
        self.setWindowTitle(f"IngeCAD — {tr('Untitled')}")
        self.resize(1280, 800)
        # Own the title bar: the system one follows the desktop's light theme
        # on GNOME/Wayland and cannot be forced dark (see views/title_bar.py).
        self.setWindowFlag(Qt.FramelessWindowHint, True)

        self.viewport = Viewport(self)
        # the drawing tabs on top of the canvas (#71): views/document_tabs.py
        from views.document_tabs import central_widget

        self._tabs_init()
        host, self._file_tabs = central_widget(self, self.viewport)
        self.setCentralWidget(host)

        self._menu_bar = QMenuBar(self)
        header = QWidget(self)
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(0)
        header_layout.addWidget(TitleBar(self))
        header_layout.addWidget(self._menu_bar)
        self.setMenuWidget(header)

        # Qt hands the bottom corners to the BOTTOM dock area by default, so
        # the command window ran the full width and cut the right sidebar
        # short. The sidebar is a palette that belongs beside the drawing all
        # the way down (AutoCAD docks its palettes to the full height and the
        # command window spans the drawing area, not the palette).
        self.setCorner(Qt.BottomRightCorner, Qt.RightDockWidgetArea)

        # Plugins (docs/plugins.md): discovered now, so the menus can list
        # them; activated once the toolbars exist, since they add to both.
        from core.plugins import PluginManager

        self.plugins = PluginManager(host=self)
        self.plugins.discover()
        self._plugin_toolbars: dict = {}

        self._build_menus()
        self._build_status_bar()
        self._build_command_line()
        self._build_sidebar()
        self._build_toolbars()
        self.plugins.activate_enabled()
        self.viewport.cursorMoved.connect(self._on_cursor_moved)

        # The canvas's own events (typing over it, the sidebar handle that
        # rides its edge); the native window's are watched from showEvent.
        # Never an app-wide filter: it put EVERY event of the application --
        # paints, timers, deleted widgets -- through Python, and while a
        # worker held the GIL each one waited its turn. Save as DWG froze
        # the window 1.05 s for it; 0.29 s without (release bench, 0.6.6).
        self.viewport.installEventFilter(self)

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
    def _circle_by(self, option: str) -> None:
        """Draw > Circle > ...: CIRCLE, answered with the option picked.
        Center, Diameter answers at the radius prompt, like AutoCAD's macro."""
        self._invoke_command("CIRCLE")
        tool = self.tools.tool
        if option == "D" and tool is not None:
            tool.diameter_after_center = True
        elif option:
            self.tools.on_text(option)

    def show_osnap_menu(self, global_pos) -> None:
        """Shift + right-click during a command: the object snap menu. The
        snap picked is for the next point only (a one-shot override)."""
        self._osnap_menu = self.osnap_override_menu()
        self._osnap_menu.popup(global_pos)

    def osnap_override_menu(self):
        """The Shift + right-click object snap menu, built fresh each time."""
        from PySide6.QtWidgets import QMenu
        from core import osnap as osnap_modes

        menu = QMenu(self)
        # AutoCAD's Object Snap shortcut menu, in its order: the point
        # modifiers, then the snaps in their groups, then None.
        menu.addAction(tr("From"),
                       lambda: self.tools.start_point_modifier("FROM"))
        menu.addAction(tr("Mid Between 2 Points"),
                       lambda: self.tools.start_point_modifier("M2P"))
        groups = (("END", "MID", "INT", "APP", "EXT"),
                  ("CEN", "GCE", "QUA", "TAN"),
                  ("PER", "PAR", "NOD", "INS", "NEA", "ORI"))
        for group in groups:
            menu.addSeparator()
            for key in group:
                mode = osnap_modes.BY_KEY[key]
                action = menu.addAction(tr(mode.label))
                action.setEnabled(mode.available)
                if not mode.available and mode.note:
                    action.setToolTip(tr(mode.note))
                action.triggered.connect(
                    lambda _=False, k=key: self.tools.set_osnap_override({k}))
        menu.addAction(tr("None"),
                       lambda: self.tools.set_osnap_override(()))
        menu.addSeparator()
        menu.addAction(tr("Object Snap Settings..."), self._osnap_settings)
        menu.setToolTipsVisible(True)
        return menu

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
        from views.options_dialog import RIGHT_CLICK_ENTER, right_click_mode

        if right_click_mode() == RIGHT_CLICK_ENTER and not self.tools.selection:
            # Options > User Preferences > Right-click Customization: the
            # drafters who set this want Enter, which repeats the last
            # command exactly as pressing it would.
            self.dispatcher.submit("")
            return
        self.show_canvas_context_menu(global_pos)

    def show_canvas_context_menu(self, global_pos) -> None:
        self.build_canvas_context_menu().exec(global_pos)

    def build_canvas_context_menu(self):
        """The Default and Edit mode shortcut menus.

        Built from the reference's own Access Methods: every command whose
        page names the shortcut menu earns a place here — Clipboard
        (CUTCLIP/COPYCLIP/PASTECLIP), Undo, Redo, Pan, Zoom with nothing
        selected; Erase, Move, Copy Selection, Scale, Rotate, Draw Order and
        Properties with a selection; and the type-specific entries for text
        (DDEDIT), polylines (PEDIT) and images (IMAGEADJUST/TRANSPARENCY).
        Nothing the app cannot actually do is listed, which is the same rule
        the command prompts follow.
        """
        from PySide6.QtWidgets import QMenu

        from core import layouts as layout_ops

        menu = QMenu(self)
        last = self.dispatcher.last_command
        if last:
            menu.addAction(tr("Repeat {name}", name=last),
                           lambda: self.dispatcher.submit(last))
            menu.addSeparator()
        selection = self.tools._selection_entities() if self.tools else []
        model_sel = bool(selection)
        vp = self.tools.paper_vp
        vp_sel = vp is not None and vp.is_alive

        clip = menu.addMenu(tr("Clipboard"))
        act = clip.addAction(tr("Cut"), self._cmd_cut)
        act.setEnabled(model_sel)
        act = clip.addAction(tr("Copy"), self._cmd_copy)
        act.setEnabled(model_sel)
        clip.addAction(tr("Paste"), self._cmd_paste)
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
                                (tr("Scale"), "SCALE"),
                                (tr("Rotate"), "ROTATE")):
                menu.addAction(
                    label, lambda checked=False, n=name: self._invoke_command(n))
            order = menu.addMenu(tr("Draw Order"))
            order.addAction(tr("Bring to Front"),
                            lambda: self._draworder("front"))
            order.addAction(tr("Send to Back"),
                            lambda: self._draworder("back"))
            self._add_isolate_menu(menu)
            self._add_type_entries(menu, selection)
            group = menu.addMenu(tr("Group"))
            group.addAction(tr("Group..."), self._cmd_group)
            menu.addAction(tr("Add Selected"),
                           lambda: self._invoke_command("ADDSELECTED"))
            menu.addAction(tr("Select Similar"),
                           lambda: self._invoke_command("SELECTSIMILAR"))
            menu.addSeparator()
            menu.addAction(tr("Deselect All"), self.tools.clear_selection)
            menu.addSeparator()
            menu.addAction(tr("Quick Select..."), self._cmd_qselect)
            menu.addAction(tr("QuickCalc"), self._cmd_quickcalc)
            menu.addAction(tr("Properties"), self.toggle_properties_panel)
        else:
            menu.addAction(tr("Undo"), self._cmd_undo)
            menu.addAction(tr("Redo"), self._cmd_redo)
            self._add_isolate_menu(menu)
            menu.addSeparator()
            menu.addAction(tr("Pan"), lambda: self._invoke_command("PAN"))
            zoom = menu.addMenu(tr("Zoom"))
            zoom.addAction(tr("Extents"), self.viewport.zoom_extents)
            zoom.addAction(tr("Window"), lambda: self.dispatcher.submit("ZOOM W"))
            zoom.addAction(tr("Previous"), self.viewport.zoom_previous)
            menu.addSeparator()
            menu.addAction(tr("Quick Select..."), self._cmd_qselect)
            menu.addAction(tr("QuickCalc"), self._cmd_quickcalc)
            menu.addAction(tr("Find..."), self._cmd_find)
            menu.addSeparator()
            menu.addAction(tr("Properties"), self.toggle_properties_panel)
            # "with no commands active and no objects selected" (p. 1314):
            # Options belongs to the Default mode menu only.
            menu.addAction(tr("Options..."), self._cmd_options)
        return menu

    def _add_isolate_menu(self, menu) -> None:
        """Isolate > Isolate Objects / Hide Objects / End Object Isolation —
        the submenu all three commands name as their access method."""
        from core import isolate as isolation

        sub = menu.addMenu(tr("Isolate"))
        sub.addAction(tr("Isolate Objects"),
                      lambda: self._invoke_command("ISOLATEOBJECTS"))
        sub.addAction(tr("Hide Objects"),
                      lambda: self._invoke_command("HIDEOBJECTS"))
        act = sub.addAction(tr("End Object Isolation"), self._cmd_unisolate)
        act.setEnabled(self.document is not None
                       and isolation.is_isolating(self.document))

    def _add_type_entries(self, menu, selection: list) -> None:
        """The entries the reference gives a single selected object of a kind:
        Edit for text (DDEDIT p. 604), Polyline > Edit (PEDIT p. 1418), and
        Image > Adjust / Transparency (p. 927, p. 1964)."""
        if len(selection) != 1:
            return
        entity = selection[0]
        kind = entity.dxftype()
        if kind in ("TEXT", "MTEXT", "ATTRIB", "ATTDEF"):
            menu.addAction(tr("Edit..."),
                           lambda: self.tools.open_text_editor_for(entity))
        elif kind in ("LWPOLYLINE", "POLYLINE"):
            poly = menu.addMenu(tr("Polyline"))
            poly.addAction(tr("Edit..."),
                           lambda: self._invoke_command("PEDIT"))
        elif kind == "IMAGE":
            image = menu.addMenu(tr("Image"))
            image.addAction(tr("Adjust..."),
                            lambda: self._invoke_command("IMAGEADJUST"))
            image.addAction(tr("Transparency"),
                            lambda: self._invoke_command("TRANSPARENCY"))
        elif kind == "INSERT":
            menu.addAction(tr("Block Editor"),
                           lambda: self._invoke_command("BEDIT"))
        elif kind == "DIMENSION":
            menu.addAction(tr("Dimension Style..."),
                           lambda: self.dispatcher.submit("DIMSTYLE"))

    def after_isolation_change(self) -> None:
        """ISOLATEOBJECTS/HIDEOBJECTS/UNISOLATEOBJECTS changed what is drawn.

        Nothing in the document moved, so there is no undo entry and no dirty
        flag — only the scene and the pick index have to be rebuilt.
        """
        self.tools.clear_selection()
        self.tools._invalidate_geometry()
        self.regen_in_memory()
        self._update_mode_buttons()

    def _cmd_unisolate(self, *args) -> None:
        """UNISOLATEOBJECTS (p. 1999): show what isolation hid."""
        from core import isolate as isolation

        if self.document is None:
            return
        count = isolation.unisolate(self.document)
        self.after_isolation_change()
        self.command_line.echo(
            tr("{count} object(s) shown again.", count=count) if count
            else tr("Nothing was hidden."))

    def zoom_to_entity(self, entity) -> None:
        """Frame one object — FIND's "Zoom to Highlighted Result" (p. 811)."""
        from ezdxf import bbox

        try:
            box = bbox.extents([entity], fast=True)
        except Exception:
            return
        if not box.has_data:
            return
        pad = max(box.size.x, box.size.y, 1.0) * 0.6
        self.viewport.view.zoom_extents(box.extmin.x - pad, box.extmin.y - pad,
                                        box.extmax.x + pad, box.extmax.y + pad)
        self.viewport.update()

    def _cmd_find(self, *args) -> None:
        """FIND (p. 808): find and replace text in the drawing."""
        from views.find_dialog import FindReplaceDialog

        if self.document is None:
            return
        FindReplaceDialog(self).exec()

    def _cmd_group(self, *args) -> None:
        """GROUP (p. 861): the Object Grouping dialog."""
        from views.group_dialog import ObjectGroupingDialog

        if self.document is None:
            return
        ObjectGroupingDialog(self).exec()

    def refresh_curve_tolerance(self) -> None:
        """VIEWRES changed: re-derive the tolerance and regenerate.

        The base scene, the overlay and every viewport pass all tessellate
        at the same distance, so they all have to be rebuilt together --
        otherwise a curve drawn after the change would not match the ones
        already on screen.
        """
        if self.document is None:
            return
        # The overlay's tolerance follows VIEWRES by itself (it is part of
        # the key ToolController._flatten caches under); only the ghost
        # built at the old distance has to go.
        self.tools._ghost_cache = None
        self.invalidate_vp_model_cache()
        self.regen_in_memory()

    def _cmd_viewres(self, *args) -> None:
        """VIEWRES (p. 2049): arc and circle smoothness, then a regen."""
        from render import backend

        current = backend.viewres()
        text = str(args[0]).strip() if args and str(args[0]).strip() else ""
        if not text:
            self.command_line.echo(
                tr("VIEWRES = {value}", value=current) + "  "
                + tr("Enter circle zoom percent ({min}-{max}):",
                     min=backend.VIEWRES_MIN, max=backend.VIEWRES_MAX))
            return
        try:
            value = int(text)
        except ValueError:
            self.command_line.echo(tr("Requires an integer value."))
            return
        if not backend.VIEWRES_MIN <= value <= backend.VIEWRES_MAX:
            self.command_line.echo(
                tr("Value must be between {min} and {max}.",
                   min=backend.VIEWRES_MIN, max=backend.VIEWRES_MAX))
            return
        QSettings().setValue(backend.SETTING_VIEWRES, value)
        self.refresh_curve_tolerance()
        self.command_line.echo(tr("VIEWRES = {value}", value=value) + "  "
                               + tr("Regenerating model."))

    def _cmd_cursorsize(self, *args) -> None:
        """CURSORSIZE (p. 2202): crosshair length, 1-100 % of the screen."""
        from views import viewport as vp_prefs

        self._set_int_pref(args, vp_prefs.SETTING_CURSORSIZE, 1, 100,
                           "CURSORSIZE", vp_prefs.cursorsize())

    def _cmd_pickbox(self, *args) -> None:
        """PICKBOX (p. 2452): the object selection target, in pixels."""
        from views import apertures

        self._set_int_pref(args, apertures.SETTING_PICKBOX, 1, 50,
                           "PICKBOX", apertures.pickbox())

    def _set_int_pref(self, args, key: str, low: int, high: int,
                      name: str, current: int) -> None:
        """The shared body of the integer system variables: bare name shows
        the value and the range, a number sets it."""
        text = str(args[0]).strip() if args and str(args[0]).strip() else ""
        if not text:
            self.command_line.echo(
                tr("{name} = {value}", name=name, value=current) + "  "
                + tr("Enter new value ({min}-{max}):", min=low, max=high))
            return
        try:
            value = int(text)
        except ValueError:
            self.command_line.echo(tr("Requires an integer value."))
            return
        if not low <= value <= high:
            self.command_line.echo(
                tr("Value must be between {min} and {max}.",
                   min=low, max=high))
            return
        QSettings().setValue(key, value)
        self.viewport.refresh_cursor_prefs()
        self.command_line.echo(tr("{name} = {value}", name=name, value=value))

    #: name: (kind, low, high) of the variables _cmd_sysvar answers
    _SYSVARS = {"DIMASSOC": (int, 0, 2), "CELTSCALE": (float, 1e-9, None),
                "DIMSCALE": (float, 0.0, None), "LWDISPLAY": (int, 0, 1),
                "ZOOMFACTOR": (int, 3, 100)}

    def _sysvar_value(self, name: str):
        from views import viewport as vp_prefs

        header = self.document.doc.header if self.document is not None else {}
        if name == "LWDISPLAY":
            return int(self.viewport.lwt_on)
        if name == "ZOOMFACTOR":
            return vp_prefs.zoomfactor()
        if name == "DIMSCALE":
            from core import styles as style_ops

            return style_ops.dim_style_attribs(
                self.document, header.get("$DIMSTYLE", "Standard")
            ).get("dimscale", 1.0) if self.document is not None else 1.0
        default = {"DIMASSOC": 2, "CELTSCALE": 1.0}[name]
        return header.get("$" + name, default)

    def _cmd_sysvar(self, name: str, *args) -> Prompt | None:
        """DIMASSOC, CELTSCALE, DIMSCALE, LWDISPLAY and ZOOMFACTOR typed:
        "Enter new value for NAME <current>:" as AutoCAD asks."""
        kind, low, high = self._SYSVARS[name]
        current = self._sysvar_value(name)
        text = str(args[0]).strip() if args and str(args[0]).strip() else ""
        if not text:
            return Prompt(tr("Enter new value for {name} <{value}>:",
                             name=name, value=f"{current:g}"),
                          lambda value: self._cmd_sysvar(name, value)
                          if str(value).strip() else None)
        try:
            value = kind(float(text.replace(",", ".")))
        except ValueError:
            self.command_line.echo(tr("Requires a numeric value."))
            return None
        if (low is not None and value < low) or (high is not None and value > high):
            self.command_line.echo(tr("Value must be between {min} and {max}.",
                                      min=low, max=high if high is not None else "∞"))
            return None
        if name == "LWDISPLAY":
            if bool(value) != self.viewport.lwt_on:
                self._toggle_mode("lwt")
        elif name == "ZOOMFACTOR":
            from views import viewport as vp_prefs

            QSettings().setValue(vp_prefs.SETTING_ZOOMFACTOR, value)
        elif name == "DIMSCALE":
            # the renderer reads DIMSCALE from the current style
            from core import styles as style_ops

            style = self.document.doc.header.get("$DIMSTYLE", "Standard")
            self.history.execute(
                style_ops.SetDimStylePropsCommand(style, {"dimscale": value}))
            self.after_style_change()
        elif self.document is not None:
            from core.attributes import SetHeaderCommand

            command = SetHeaderCommand("$" + name, value, name)
            command.needs_regen = False       # new objects only
            self.history.execute(command)
        self.command_line.echo(tr("{name} = {value}", name=name,
                                  value=f"{value:g}"))
        return None

    def _cmd_lweight(self, *args) -> Prompt | None:
        """-LWEIGHT: the lineweight new objects get ($CELWEIGHT)."""
        from core.attributes import SetHeaderCommand

        def answer(text: str):
            key = text.strip().upper()
            if not key:
                return None
            named = {"BYLAYER": -1, "BL": -1, "BYBLOCK": -2, "BB": -2,
                     "DEFAULT": -3, "D": -3}
            if key in named:
                value = named[key]
            else:
                try:
                    mm = float(key.replace(",", "."))
                except ValueError:
                    self.command_line.echo(tr("Invalid lineweight."))
                    return ask()
                from ezdxf.lldxf import const

                value = min(const.VALID_DXF_LINEWEIGHTS,
                            key=lambda w: abs(w - mm * 100))
            if self.document is not None:
                command = SetHeaderCommand("$CELWEIGHT", value, "LWEIGHT")
                command.needs_regen = False
                self.history.execute(command)
            self.command_line.echo(tr("Current lineweight for new objects: {w}",
                                      w=_lineweight_name(value)))
            return None

        def ask():
            current = int(self.document.doc.header.get("$CELWEIGHT", -1)) \
                if self.document is not None else -1
            return Prompt(tr("Enter default lineweight for new objects or "
                             "[ByLayer/ByBlock/Default] <{w}>:",
                             w=_lineweight_name(current)), answer)

        if args and str(args[0]).strip():
            return answer(str(args[0]))
        return ask()

    def _cmd_setvar(self, *args) -> Prompt | None:
        """SETVAR: a variable by name, then its own prompt."""
        def answer(text: str):
            name = text.strip().upper()
            if not name:
                return None
            entry = self.dispatcher._commands.get(name)
            if entry is None:
                self.command_line.echo(tr("Unknown variable name."))
                return None
            return entry.handler()

        if args and str(args[0]).strip():
            return answer(str(args[0]))
        return Prompt(tr("Enter variable name:"), answer)

    def _cmd_drafting_var(self, name: str, *args) -> Prompt | None:
        """The Drafting Settings variables, typed: POLARANG (degrees),
        POLARADDANG (angles separated by ;), POLARMODE (bits), GRIDUNIT,
        SNAPUNIT (0 = follow the grid on screen) and GRIDMAJOR."""
        from core import drafting

        drawing = self.document.doc if self.document is not None else None
        current = {
            "POLARANG": drafting.polar_increment(),
            "POLARADDANG": ";".join(f"{a:g}" for a in drafting.polar_additional()),
            "POLARMODE": drafting.polar_mode(),
            "GRIDUNIT": drafting.grid_unit(drawing) if drawing is not None else 0,
            "SNAPUNIT": drafting.snap_unit(drawing) if drawing is not None else 0,
            "GRIDMAJOR": drafting.grid_major(drawing) if drawing is not None else 5,
        }[name]
        text = str(args[0]).strip() if args and str(args[0]).strip() else ""
        if not text:
            return Prompt(
                tr("Enter new value for {name} <{value}>:",
                   name=name, value=current),
                lambda value: self._cmd_drafting_var(name, value))
        if name == "POLARADDANG":
            drafting.set_polar_additional(drafting.parse_angles(text))
            value = ";".join(f"{a:g}" for a in drafting.polar_additional())
        elif name == "POLARMODE":
            try:
                value = int(text)
            except ValueError:
                self.command_line.echo(tr("Requires an integer value."))
                return
            drafting.set_polar_mode(value)
        elif name == "GRIDMAJOR":
            try:
                value = int(text)
            except ValueError:
                self.command_line.echo(tr("Requires an integer value."))
                return
            if not 2 <= value <= 100:
                self.command_line.echo(
                    tr("Value must be between {min} and {max}.", min=2, max=100))
                return
            if self.document is not None:
                self.history.execute(drafting.SetGridCommand(major=value))
        else:
            try:
                value = float(text.replace(",", "."))
            except ValueError:
                self.command_line.echo(tr("Requires a numeric value."))
                return
            if name == "POLARANG":
                if not 0.0 < value <= 90.0:
                    self.command_line.echo(
                        tr("Value must be between {min} and {max}.",
                           min=0, max=90))
                    return
                drafting.set_polar_increment(value)
            elif value < 0.0 or (name == "GRIDUNIT" and value <= 0.0):
                self.command_line.echo(tr("Value must be positive."))
                return
            elif self.document is not None:
                self.history.execute(drafting.SetGridCommand(
                    **{"grid" if name == "GRIDUNIT" else "snap": value}))
        self.refresh_grid_settings()
        self.command_line.echo(tr("{name} = {value}", name=name, value=value))

    def _cmd_center_var(self, name: str, *args) -> None:
        """The CENTERMARK / CENTERLINE variables (AutoCAD 2017+): bare name
        shows the value, a value sets it. CENTEREXE is a length in drawing
        units, CENTERCROSSSIZE / CENTERCROSSGAP a length or a multiple of
        the diameter (``0.1x``), CENTERLTYPE a linetype name, CENTERLAYER a
        layer name or ``.`` for the current one, CENTERMARKEXE 0 or 1."""
        from core import centerlines

        prefs = centerlines.settings()
        key = {"CENTEREXE": centerlines.SETTING_EXE,
               "CENTERLTYPE": centerlines.SETTING_LTYPE,
               "CENTERCROSSSIZE": centerlines.SETTING_CROSSSIZE,
               "CENTERCROSSGAP": centerlines.SETTING_CROSSGAP,
               "CENTERLAYER": centerlines.SETTING_LAYER,
               "CENTERMARKEXE": centerlines.SETTING_MARKEXE}[name]
        current = {"CENTEREXE": prefs.exe, "CENTERLTYPE": prefs.ltype,
                   "CENTERCROSSSIZE": prefs.crosssize,
                   "CENTERCROSSGAP": prefs.crossgap,
                   "CENTERLAYER": prefs.layer,
                   "CENTERMARKEXE": int(prefs.markexe)}[name]
        text = str(args[0]).strip() if args and str(args[0]).strip() else ""
        if not text:
            self.command_line.echo(
                tr("{name} = {value}", name=name, value=current) + "  "
                + tr("Enter new value:"))
            return
        if name == "CENTEREXE":
            try:
                value = float(text.replace(",", "."))
            except ValueError:
                self.command_line.echo(tr("Requires a numeric value."))
                return
            if value < 0:
                self.command_line.echo(tr("Value must not be negative."))
                return
        elif name in ("CENTERCROSSSIZE", "CENTERCROSSGAP"):
            if not centerlines.valid_size(text):
                self.command_line.echo(
                    tr("Requires a length or a multiple of the diameter, "
                       "like 0.1x."))
                return
            value = text
        elif name == "CENTERMARKEXE":
            if text not in ("0", "1"):
                self.command_line.echo(tr("Requires 0 or 1."))
                return
            value = text == "1"
        else:
            value = text
        QSettings().setValue(key, value)
        self.command_line.echo(tr("{name} = {value}", name=name,
                                  value=int(value) if name == "CENTERMARKEXE"
                                  else value))

    def _cmd_pickstyle(self, *args) -> None:
        """PICKSTYLE (p. 2452): 0 turns group selection off, 1 on.

        Without a way to reach it, a grouped object could never be selected
        on its own again -- the group swallowed every pick.
        """
        from core import groups as group_ops

        if self.document is None:
            return
        current = group_ops.pickstyle(self.document)
        value = None
        if args and str(args[0]).strip() != "":
            try:
                value = int(str(args[0]).strip())
            except ValueError:
                value = None
            if value is not None and value not in (0, 1, 2, 3):
                value = None
            if value is None:
                self.command_line.echo(tr("Requires an integer value."))
                return
        if value is None:
            value = 0 if current else 1     # bare PICKSTYLE toggles
        group_ops.set_pickstyle(self.document, value)
        self.command_line.echo(
            tr("PICKSTYLE = {value}", value=value) + "  "
            + (tr("Group selection on.") if value else
               tr("Group selection off.")))

    def _cmd_quickcalc(self, *args) -> None:
        """QUICKCALC (p. 1589)."""
        from views.quickcalc_dialog import QuickCalcDialog

        QuickCalcDialog(self).exec()

    def _cmd_qselect(self, *args) -> None:
        """QSELECT (p. 1584): build a selection set from filter criteria."""
        from views.qselect_dialog import QuickSelectDialog

        if self.document is None:
            return
        current = self.tools._selection_entities()
        dialog = QuickSelectDialog(self, self.document, current)
        if not dialog.exec():
            return
        handles = {e.dxf.handle for e in dialog.result_entities()}
        if dialog.append_to_selection():
            handles |= set(self.tools.selection)
        self.tools.selection = handles
        self.tools.changed.emit()
        self.command_line.echo(
            tr("{count} object(s) selected.", count=len(handles)))

    def _cmd_options(self, *args) -> None:
        """OPTIONS: the program settings (p. 1314)."""
        from views.options_dialog import OptionsDialog

        OptionsDialog(self).exec()

    def _draworder(self, mode: str) -> None:
        """Tools > Draw Order and the shortcut menu: act on the selection, or
        ask for one and then act — never leave the user at a Front/Back
        prompt they did not ask for."""
        from core.draworder import DrawOrderCommand

        entities = self.tools._selection_entities() if self.tools else []
        if entities:
            self.history.execute(DrawOrderCommand(entities, mode))
            self.regen_in_memory()
            self.command_line.echo(
                tr("{count} object(s) reordered.", count=len(entities)))
            return
        self._invoke_command("DRAWORDER")
        tool = self.tools.tool
        if tool is not None:
            tool.mode = mode
            self.command_line.echo(
                tr("Select objects to bring to front:") if mode == "front"
                else tr("Select objects to send to back:"))

    def _cmd_dxfout(self, *args) -> None:
        """DXFOUT / File > Export > DXF (#51): write a DXF copy of the
        drawing for another program (Blender, QGIS...). Unlike Save As it
        does not change the file that is open: Ctrl+S keeps saving there."""
        if self.document is None:
            self.command_line.echo(tr("Nothing to export yet."))
            return
        if args:
            path = args[0]
        else:
            path, _f = file_dialogs.get_save_file(
                self, tr("Export to DXF"),
                Path(self.document.name).stem + ".dxf",
                tr("DXF (*.dxf)"), preferred=self.document.path)
        if not path:
            return
        path = Path(path)
        if path.suffix.lower() != ".dxf":
            path = path.with_suffix(".dxf")
        doc = self.document.doc
        keep = doc.filename
        try:
            doc.saveas(path)
        except Exception as exc:          # noqa: BLE001 - reported, not raised
            self.command_line.echo(
                tr("Cannot export {name}: {error}", name=path.name, error=str(exc)))
            return
        finally:
            doc.filename = keep           # the open drawing keeps its own file
        self.command_line.echo(tr("Exported {name} (DXF {version})",
                                  name=path.name, version=doc.acad_release))

    def _publish_dialog(self) -> None:
        """PUBLISH (p. 1509): the layouts of the drawing into one PDF."""
        from views.publish_dialog import PublishDialog

        if self.document is None:
            return
        if len(self.document.doc.layouts) < 2:
            self.command_line.echo(tr("This drawing has no layouts to publish."))
            return
        PublishDialog(self).exec()

    def _plot_dialog(self) -> None:
        if self.document is None:
            self.command_line.echo(tr("Nothing to plot."))
            return
        self._run_plot_dialog()

    def _run_plot_dialog(self, state: dict | None = None) -> None:
        """PLOT, and its Window pick: the dialog leaves, the corners are
        picked on the canvas, and it comes back as it was (AutoCAD, #52)."""
        from views.print_dialog import PICK_WINDOW, PrintDialog

        document = self.document
        layout = getattr(self, "_active_layout", "Model")
        if state is None and document is not None:
            # reopen as the last plot of this tab left it (Rafael's review 6:
            # back to Extents / Fit / Meters after a Window / mm / acad.ctb)
            state = document.plot_settings.get(layout)
        dialog = PrintDialog(self, state)
        result = dialog.exec()
        if result == QDialog.Accepted and document is not None:
            document.plot_settings[layout] = dialog.state()
        if result != PICK_WINDOW:
            return
        state = dialog.state()

        def picked(rect) -> None:
            if rect is not None:
                state["window"] = rect
            self._run_plot_dialog(state)

        # AutoCAD plots what the sheet shows: a window is picked on the
        # paper, never through an active viewport
        self._deactivate_viewport()
        self._plot_window_callback = picked
        self.tools.start_tool("PLOTWINDOW")
        if self.tools.tool is None:          # refused: the dialog comes back
            self._plot_window_callback = None
            picked(None)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        # The native window sees every key and press of this window before
        # any widget does -- and nothing else (no paints, no timers).
        handle = self.windowHandle()
        if handle is not None and handle is not getattr(self, "_native_window", None):
            handle.installEventFilter(self)
            self._native_window = handle

    def eventFilter(self, obj, event) -> bool:
        if (event.type() == QEvent.Resize
                and obj is getattr(self, "_layout_tab_host", None)):
            self._fit_layout_tabs()
        # The sidebar handle rides the drawing's right edge.
        if (event.type() in (QEvent.Resize, QEvent.Move, QEvent.Show)
                and obj is getattr(self, "viewport", None)):
            self._place_sidebar_handle()
        native = obj is getattr(self, "_native_window", None)
        # In-place TEXT typing captures the keyboard before the command line.
        if (event.type() == QEvent.KeyPress and self.tools.text_capturing()
                and (native or obj is getattr(self, "viewport", None))
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
        # Frameless windows have no system resize borders: a press on the
        # outer margin, whatever widget is under it, is a native resize. The
        # status bar's size grip still works as usual.
        if (
            native
            and event.type() == QEvent.MouseButtonPress
            and event.button() == Qt.LeftButton
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
        # The canvas actions (Ctrl+C/X/V, Delete, Ctrl+A...) hang off the
        # viewport, which outlives the menus. Every rebuild -- one per plugin
        # turned on or off -- added a fresh copy beside the old, and Qt
        # answers an ambiguous shortcut by firing NONE: with two plugins on,
        # Ctrl+C on the canvas silently did nothing. The old ones go first.
        for stale in getattr(self, "_canvas_actions", []):
            self.viewport.removeAction(stale)
            stale.deleteLater()
        self._canvas_actions = []

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
        item(file_menu, tr("Close"), lambda: self.close_document())
        file_menu.addSeparator()
        item(file_menu, tr("Save"), self.save_document, QKeySequence.Save,
             icon="SAVEAS")
        item(file_menu, tr("Save As..."), self._save_as_dialog,
             QKeySequence.SaveAs, icon="SAVEAS")
        # AutoCAD: Application menu > Export > Block (WBLOCK, p. 2086).
        cmd_item(file_menu, tr("Write Block..."), "WBLOCK", icon=False)
        # DXF for Blender, QGIS or any other program (#51): a copy, the
        # drawing that is open stays what it was.
        export_menu = file_menu.addMenu(tr("Export"))
        item(export_menu, tr("DXF..."), lambda: self._cmd_dxfout())
        file_menu.addSeparator()
        # AutoCAD: File > Drawing Utilities > Drawing Recovery (p. 659),
        # and Drawing Utilities > Purge (p. 1567).
        utilities = file_menu.addMenu(tr("Drawing Utilities"))
        item(utilities, tr("Drawing Recovery..."),
             lambda: self._cmd_drawing_recovery())
        cmd_item(utilities, tr("Purge..."), "PURGE", icon=False)
        file_menu.addSeparator()
        item(file_menu, tr("Page Setup..."), lambda: self._cmd_pagesetup(),
             icon="PAGESETUP")
        item(file_menu, tr("Plot..."), self._plot_dialog, QKeySequence.Print,
             icon="PLOT")
        item(file_menu, tr("Publish..."), self._publish_dialog)
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
            self._canvas_actions.append(act)
            return act

        canvas_action(tr("Cut"), self._cmd_cut, QKeySequence.Cut,
                      icon="CUTCLIP")
        canvas_action(tr("Copy"), self._cmd_copy, QKeySequence.Copy,
                      icon="COPYCLIP")
        canvas_action(tr("Paste"), self._cmd_paste, QKeySequence.Paste,
                      icon="PASTECLIP")
        canvas_action(tr("Delete"), self._cmd_delete, QKeySequence.Delete,
                      icon="ERASE")
        # AutoCAD's Ctrl+Shift+C / Ctrl+Shift+V: COPYBASE and PASTEBLOCK
        canvas_action(tr("Copy with Base Point"),
                      lambda: self._invoke_command("COPYBASE"), QKeySequence("Ctrl+Shift+C"))
        canvas_action(tr("Paste as Block"),
                      lambda: self._invoke_command("PASTEBLOCK"), QKeySequence("Ctrl+Shift+V"))
        canvas_action(tr("Select All"), self._cmd_select_all, QKeySequence("Ctrl+A"))
        edit_menu.addSeparator()
        # "Menu: Edit > Find" (p. 808), with the platform's own key.
        # (no key: in AutoCAD Ctrl+F toggles object snap, see _build_acad_shortcuts)
        item(edit_menu, tr("Find..."), self._cmd_find)
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
        clean = item(view_menu, tr("Clean Screen"), self.toggle_clean_screen)
        clean.setShortcut("Ctrl+0")
        # The same toggle as the handle on the sidebar's edge (IngeTrazo's
        # Window > Sidebar); Ctrl+F5 is free in AutoCAD. Made once: the
        # menus are rebuilt per plugin, and a second copy would leave the
        # handle toggling a stale action and Ctrl+F5 ambiguous (Qt fires
        # neither).
        sidebar = getattr(self, "_act_sidebar", None)
        if sidebar is None:
            sidebar = QAction(self)
            sidebar.setCheckable(True)
            sidebar.setChecked(True)
            sidebar.setShortcut(QKeySequence("Ctrl+F5"))
            sidebar.toggled.connect(lambda on: self._set_sidebar_visible(on))
            self._act_sidebar = sidebar
        sidebar.setText(tr("Sidebar"))
        sidebar.setToolTip(tr("Show or hide the sidebar (Ctrl+F5)"))
        view_menu.addAction(sidebar)
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
        # AutoCAD's Ctrl+R: "cycles the current viewport among the active
        # viewports when in model space in a layout".
        item(vp_menu, tr("Next viewport"), self.cycle_active_viewport,
             QKeySequence("Ctrl+R"))
        view_menu.addSeparator()
        item(view_menu, tr("Layers panel"), self.toggle_layers_panel,
             icon="LAYER")

        # -- Insert -----------------------------------------------------------
        insert_menu = menu_bar.addMenu(tr("Insert"))
        cmd_item(insert_menu, tr("Block..."), "INSERT")
        cmd_item(insert_menu, tr("Create Block..."), "BLOCK")
        cmd_item(insert_menu, tr("Define Attributes..."), "ATTDEF", icon=False)
        insert_menu.addSeparator()
        # Classic AutoCAD: Insert > External Reference (XATTACH) and the
        # External References palette (#33).
        cmd_item(insert_menu, tr("External Reference..."), "XATTACH", icon=False)
        cmd_item(insert_menu, tr("External References Palette"), "XREF",
                 icon=False)
        insert_menu.addSeparator()
        # Classic AutoCAD: Insert > Raster Image Reference.
        cmd_item(insert_menu, tr("Raster Image Reference..."), "IMAGEATTACH",
                 icon=False)
        cmd_item(insert_menu, tr("PDF as Raster Image..."), "PDFATTACH",
                 icon=False)
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
        layer_tools = format_menu.addMenu(tr("Layer Tools"))
        cmd_item(layer_tools, tr("Layer Isolate"), "LAYISO", icon=False)
        cmd_item(layer_tools, tr("Layer Unisolate"), "LAYUNISO", icon=False)
        cmd_item(layer_tools, tr("Layer Off"), "LAYOFF", icon=False)
        cmd_item(layer_tools, tr("Turn All Layers On"), "LAYON", icon=False)
        cmd_item(layer_tools, tr("Layer Freeze"), "LAYFRZ", icon=False)
        cmd_item(layer_tools, tr("Thaw All Layers"), "LAYTHW", icon=False)
        cmd_item(layer_tools, tr("Layer Lock"), "LAYLCK", icon=False)
        cmd_item(layer_tools, tr("Layer Unlock"), "LAYULK", icon=False)
        format_menu.addSeparator()
        item(format_menu, tr("Text Style..."), self.toggle_styles_panel,
             icon="STYLE")
        item(format_menu, tr("Dimension Style..."),
             self._open_dimstyle_manager, icon="DIMSTYLE")
        format_menu.addSeparator()
        cmd_item(format_menu, tr("Point Style..."), "DDPTYPE", icon=False)
        item(format_menu, tr("Units..."), self._units_dialog)

        # -- Draw -------------------------------------------------------------
        draw_menu = menu_bar.addMenu(tr("Draw"))
        cmd_item(draw_menu, tr("Construction Line"), "XLINE")
        cmd_item(draw_menu, tr("Ray"), "RAY")
        draw_menu.addSeparator()
        for label, name in ((tr("Line"), "LINE"), (tr("Polyline"), "PLINE")):
            cmd_item(draw_menu, label, name)
        # AutoCAD classic: Draw > Circle, one entry per way of drawing it
        circle_menu = draw_menu.addMenu(tr("Circle"))
        for label, option in ((tr("Center, Radius"), ""),
                              (tr("Center, Diameter"), "D"),
                              (tr("2 Points"), "2P"), (tr("3 Points"), "3P"),
                              (tr("Tan, Tan, Radius"), "T"),
                              (tr("Tan, Tan, Tan"), "TTT")):
            item(circle_menu, label,
                 lambda _=False, o=option: self._circle_by(o))
        for label, name in ((tr("Arc"), "ARC"), (tr("Ellipse"), "ELLIPSE"),
                            (tr("Rectangle"), "RECTANG"), (tr("Polygon"), "POLYGON")):
            cmd_item(draw_menu, label, name)
        # AutoCAD classic: one Draw > Point, a submenu (Rafael's review 6
        # found a "Point" item right above a "Point" submenu). POINT here
        # repeats until Enter, so it is the menu's Multiple Point.
        point_menu = draw_menu.addMenu(tr("Point"))
        cmd_item(point_menu, tr("Multiple Point"), "POINT")
        cmd_item(point_menu, tr("Divide"), "DIVIDE")
        cmd_item(point_menu, tr("Measure"), "MEASURE")
        cmd_item(draw_menu, tr("Spline"), "SPLINE")
        cmd_item(draw_menu, tr("Donut"), "DONUT", icon=False)
        cmd_item(draw_menu, tr("Boundary..."), "BOUNDARY", icon=False)
        cmd_item(draw_menu, tr("Revision Cloud"), "REVCLOUD")
        cmd_item(draw_menu, tr("Table..."), "TABLE", icon=False)
        draw_menu.addSeparator()
        cmd_item(draw_menu, tr("Text"), "TEXT")
        cmd_item(draw_menu, tr("Multiline text"), "MTEXT")
        cmd_item(draw_menu, tr("Hatch"), "HATCH")

        # -- Dimension --------------------------------------------------------
        dim_menu = menu_bar.addMenu(tr("Dimension"))
        cmd_item(dim_menu, tr("Quick Dimension"), "QDIM")
        cmd_item(dim_menu, tr("Dimension"), "DIM")
        dim_menu.addSeparator()
        cmd_item(dim_menu, tr("Linear"), "DIMLINEAR")
        cmd_item(dim_menu, tr("Aligned"), "DIMALIGNED")
        cmd_item(dim_menu, tr("Arc Length"), "DIMARC")
        cmd_item(dim_menu, tr("Ordinate"), "DIMORDINATE")
        cmd_item(dim_menu, tr("Radius"), "DIMRADIUS")
        cmd_item(dim_menu, tr("Diameter"), "DIMDIAMETER")
        cmd_item(dim_menu, tr("Angular"), "DIMANGULAR")
        cmd_item(dim_menu, tr("Jogged"), "DIMJOGGED")
        dim_menu.addSeparator()
        cmd_item(dim_menu, tr("Baseline"), "DIMBASELINE")
        cmd_item(dim_menu, tr("Continue"), "DIMCONTINUE")
        cmd_item(dim_menu, tr("Adjust Space"), "DIMSPACE")
        cmd_item(dim_menu, tr("Dimension Break"), "DIMBREAK")
        dim_menu.addSeparator()
        cmd_item(dim_menu, tr("Multileader"), "MLEADER")
        cmd_item(dim_menu, tr("Quick Leader"), "QLEADER")
        cmd_item(dim_menu, tr("Leader"), "LEADER")
        dim_menu.addSeparator()
        cmd_item(dim_menu, tr("Center Mark"), "DIMCENTER")
        cmd_item(dim_menu, tr("Center Mark with Centerlines"), "CENTERMARK")
        cmd_item(dim_menu, tr("Centerline"), "CENTERLINE")
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
        cmd_item(modify_menu, tr("Lengthen"), "LENGTHEN", icon=False)
        # AutoCAD keeps ALIGN under Modify > 3D Operations; a 2D CAD has no
        # such submenu, so it sits with the other modify commands.
        cmd_item(modify_menu, tr("Align"), "ALIGN", icon=False)
        modify_menu.addSeparator()
        cmd_item(modify_menu, tr("Match Properties"), "MATCHPROP")
        cmd_item(modify_menu, tr("Delete Duplicate Objects"), "OVERKILL",
                 icon=False)
        # ONE Object submenu -- there used to be two of them, both added to
        # Modify, so Image and Polyline lived in different menus of the
        # same name. AutoCAD's is Modify > Object > {Image, Polyline,
        # Hatch, ...}.
        object_menu = modify_menu.addMenu(tr("Object"))
        image_menu = object_menu.addMenu(tr("Image"))
        cmd_item(image_menu, tr("Adjust..."), "IMAGEADJUST", icon=False)
        cmd_item(image_menu, tr("Transparency"), "TRANSPARENCY", icon=False)
        cmd_item(object_menu, tr("Polyline"), "PEDIT")
        cmd_item(object_menu, tr("Hatch..."), "HATCHEDIT")
        # AutoCAD: Modify > Object > Text > Scale
        text_menu = object_menu.addMenu(tr("Text"))
        cmd_item(text_menu, tr("Scale"), "SCALETEXT", icon=False)
        # AutoCAD: Modify > Object > Attribute > {Single, Global, Block
        # Attribute Manager}; Synchronize is BATTMAN's Sync as a command.
        attribute_menu = object_menu.addMenu(tr("Attribute"))
        cmd_item(attribute_menu, tr("Single..."), "EATTEDIT", icon=False)
        cmd_item(attribute_menu, tr("Global"), "-ATTEDIT", icon=False)
        cmd_item(attribute_menu, tr("Block Attribute Manager..."), "BATTMAN",
                 icon=False)
        cmd_item(attribute_menu, tr("Synchronize"), "ATTSYNC", icon=False)
        # AutoCAD: Modify > Annotative Object Scale > Add/Delete Scales...
        # (#73: OBJECTSCALE existed and nobody could find it)
        anno_menu = modify_menu.addMenu(tr("Annotative Object Scale"))
        cmd_item(anno_menu, tr("Add Current Scale"), "AIOBJECTSCALEADD",
                 icon=False)
        cmd_item(anno_menu, tr("Delete Current Scale"), "AIOBJECTSCALEREMOVE",
                 icon=False)
        anno_menu.addSeparator()
        cmd_item(anno_menu, tr("Add/Delete Scales..."), "OBJECTSCALE",
                 icon=False)
        cmd_item(modify_menu, tr("Explode"), "EXPLODE")

        # -- Tools ------------------------------------------------------------
        # -- Plugins: one menu each, between Modify and Tools -----------------
        # The PySide6 gotcha below (Python-owned QMenus) bites here first: a
        # menu created in a loop has no local name, so it must be held until
        # the keep-alive pass at the end of this method has seen it.
        plugin_menus: list = []
        for spec in self.plugins.active_specs():
            if spec.menu:
                top = menu_bar.addMenu(tr(spec.name))
                plugin_menus.append(top)
                self._fill_plugin_menu(top, spec.menu, plugin_menus)

        tools_menu = menu_bar.addMenu(tr("Tools"))
        # AutoCAD's Tools > Draw Order, with its two entries: the command
        # itself still asks Front/Back, but nobody should have to find that
        # out to put a hatch behind a plan.
        order_menu = tools_menu.addMenu(tr("Draw Order"))
        order_menu.addAction(tr("Bring to Front"),
                             lambda: self._draworder("front"))
        order_menu.addAction(tr("Send to Back"),
                             lambda: self._draworder("back"))
        item(tools_menu, tr("Block Editor..."),
             lambda: self._invoke_command("BEDIT"))
        item(tools_menu, tr("Quick Select..."), self._cmd_qselect)
        item(tools_menu, tr("QuickCalc"), self._cmd_quickcalc)
        item(tools_menu, tr("Group..."), self._cmd_group)
        item(tools_menu, tr("Plugins..."), self._cmd_plugins)
        item(tools_menu, tr("Load Application..."), self._cmd_appload)
        item(tools_menu, tr("Run Script..."), self._cmd_script)
        # Tools > New UCS, as the classic menu has it (#91); each entry is
        # UCS with its option typed, like AutoCAD's menu macros.
        ucs_menu = tools_menu.addMenu(tr("New UCS"))
        for label, option in ((tr("World"), "W"), (tr("Previous"), "P"),
                              (tr("Origin"), "O"), (tr("3 Point"), ""),
                              (tr("Object"), "OB"), (tr("Align to View"), "V"),
                              (tr("Z"), "Z")):
            ucs_menu.addAction(label,
                               lambda o=option: self._ucs_from_menu(o))
        inquiry_menu = tools_menu.addMenu(tr("Inquiry"))
        cmd_item(inquiry_menu, tr("Distance"), "DIST", icon=False)
        cmd_item(inquiry_menu, tr("Area"), "AREA", icon=False)
        cmd_item(inquiry_menu, tr("List"), "LIST", icon=False)
        cmd_item(inquiry_menu, tr("ID Point"), "ID", icon=False)
        tools_menu.addSeparator()
        lang_menu = tools_menu.addMenu(tr("Language"))
        lang_group = QActionGroup(self)
        # Built from the packs installed under i18n/, so adding a language is
        # dropping a folder — never editing this file. Each is listed in its
        # own name, recognizable no matter which language is active.
        for code in i18n.available_languages():
            act = QAction(i18n.language_name(code), self)
            act.setCheckable(True)
            act.setChecked(i18n.current_language() == code)
            act.triggered.connect(lambda _=False, c=code: self._set_language(c))
            lang_group.addAction(act)
            lang_menu.addAction(act)
        customize_menu = tools_menu.addMenu(tr("Customize"))
        item(customize_menu, tr("Edit Program Parameters (acad.pgp)"),
             self._cmd_edit_pgp)
        tools_menu.addSeparator()
        # Where the classic pre-ribbon AutoCAD kept them, and Options the
        # last entry of the menu as it has always been.
        item(tools_menu, tr("Drafting Settings..."),
             lambda: self._drafting_settings(0))
        item(tools_menu, tr("Options..."), self._cmd_options)

        # -- Window / Help ----------------------------------------------------
        # Owned by the window (see the recent drawings menu above): it is
        # refreshed on every open, switch and close of a drawing tab.
        previous = getattr(self, "_window_documents_menu", None)
        if previous is not None:
            try:
                previous.deleteLater()      # language switch: no leak
            except RuntimeError:
                pass
        window_menu = QMenu(tr("Window"), self)
        menu_bar.addMenu(window_menu)
        # AutoCAD's Window menu: Close, Close All, then the open drawings
        item(window_menu, tr("Close"), lambda: self.close_document())
        item(window_menu, tr("Close All"), lambda: self.close_all_documents())
        window_menu.addSeparator()
        item(window_menu, tr("Layers panel"), self.toggle_layers_panel)
        item(window_menu, tr("Command line"),
             lambda: self.command_line.input.setFocus())
        window_menu.addSeparator()
        self._window_documents_menu = window_menu
        self._window_document_actions = []
        self._refresh_window_menu()

        help_menu = menu_bar.addMenu(tr("Help"))
        item(help_menu, tr("Help (ingecad.org)"), self._cmd_help, QKeySequence("F1"))
        item(help_menu, tr("Report a Problem..."), self._report_problem)
        help_menu.addSeparator()
        # Only as an AppImage: put a launcher in the menu, or take it away.
        from core.appimage import appimage_path

        if appimage_path() is not None:
            item(help_menu, tr("Add to the applications menu"),
                 self.add_appimage_to_menu)
            item(help_menu, tr("Remove from the applications menu"),
                 self.remove_appimage_from_menu)
            help_menu.addSeparator()
        item(help_menu, tr("About IngeCAD"), self._show_about)

        # PySide6 gotcha: QMenus returned by addMenu(title) are Python-owned
        # — without a live reference, gc.collect() DELETES them (menus and
        # submenus would vanish from a running app). Keep them all.
        # And call .menu() ONCE per action: a second call hands back a
        # throwaway wrapper, and the C++ menu dies with it (measured: 1 of
        # 22 menus survived a version that tested `.menu() is not None`
        # and then called it again).
        self._menus = []

        def keep(menu) -> None:
            self._menus.append(menu)
            for sub in menu.actions():
                child = sub.menu()
                if child is not None:
                    keep(child)               # plugin menus nest deeper

        for action in menu_bar.actions():
            menu = action.menu()
            if menu is not None:
                keep(menu)

    # -- plugins: the host side of core/plugins.py --------------------------
    def _fill_plugin_menu(self, menu, items, keep: list) -> None:
        """Build a plugin's menu entries; every submenu goes into ``keep``
        so it outlives this call (see the ownership note in _build_menus)."""
        from PySide6.QtGui import QIcon

        from core.plugins import SEPARATOR, Submenu
        from views.icons import command_icon

        for entry in items:
            if entry == SEPARATOR:
                menu.addSeparator()
            elif isinstance(entry, Submenu):
                sub = menu.addMenu(tr(entry.label))
                keep.append(sub)
                self._fill_plugin_menu(sub, entry.items, keep)
            else:
                act = QAction(tr(entry.label), self)
                act.setIcon(QIcon(str(entry.icon)) if entry.icon
                            else command_icon(entry.command))
                act.triggered.connect(
                    lambda _=False, n=entry.command: self._invoke_command(n))
                menu.addAction(act)

    def _cmd_appload(self, *args) -> None:
        """APPLOAD (p. 125): load and run a Python file over ``actions``
        (Tools > Load Application...). Everything it draws is one undo step."""
        from pathlib import Path

        from core import scripting
        from views import file_dialogs

        if self.document is None:
            self.new_document()
        path = args[0] if args else file_dialogs.get_open_file(
            self, tr("Load Application"), tr("Python files (*.py)"))
        if not path:
            return
        path = Path(path)
        if not path.is_file():
            self.command_line.echo(tr("Cannot find file {path}.", path=str(path)))
            return
        count, error = scripting.run_python(path, self)
        if error:
            self.command_line.echo(tr("{name}: {error}", name=path.name, error=error))
        self.command_line.echo(
            tr("{name} loaded: {count} command(s), one undo step.",
               name=path.name, count=count))
        if count:
            self.tools.changed.emit()

    def _cmd_script(self, *args) -> None:
        """SCRIPT (p. 1699): run an AutoCAD .scr, one command-line entry per
        line, from a timer so the screen keeps up (Tools > Run Script...)."""
        from pathlib import Path

        from PySide6.QtCore import QTimer

        from core import scripting
        from views import file_dialogs

        path = args[0] if args else file_dialogs.get_open_file(
            self, tr("Select Script File"), tr("Script files (*.scr)"))
        if not path:
            return
        path = Path(path)
        if not path.is_file():
            self.command_line.echo(tr("Cannot find file {path}.", path=str(path)))
            return
        runner = scripting.ScriptRunner.from_file(path, self._on_command_submitted)
        self._script_runner = runner

        def step() -> None:
            if getattr(self, "_script_runner", None) is not runner:
                return                      # another script took over, or Esc
            wait = runner.step()
            if wait is None:
                self._script_runner = None
                return
            QTimer.singleShot(wait, step)

        step()

    def run_script_to_end(self) -> None:
        """Headless: finish the running .scr synchronously (tests)."""
        runner = getattr(self, "_script_runner", None)
        while runner is not None and runner.step() is not None:
            pass
        self._script_runner = None

    def _cmd_plugins(self, *args) -> None:
        """PLUGINS: the manager (Tools > Plugins...)."""
        from views.plugins_dialog import PluginsDialog

        PluginsDialog(self).exec()

    def register_command(self, name: str, handler) -> None:
        self.dispatcher.register(name, handler)

    def unregister_command(self, name: str) -> None:
        self.dispatcher.unregister(name)

    def register_tools(self, mapping: dict, owner: str) -> None:
        from views.tool_controller import register_tool_classes

        register_tool_classes(mapping, owner)

    def unregister_tools(self, names, owner: str) -> None:
        from views.tool_controller import unregister_tool_classes

        unregister_tool_classes(names, owner)

    def add_alias(self, alias: str, command: str) -> bool:
        """A plugin alias, unless the user's PGP or the core already answers
        to that token -- an alias always wins over a command name, so a
        plugin must never be able to take one."""
        alias = alias.upper()
        if alias in self.dispatcher.aliases or alias in self.dispatcher._commands:
            return False
        self.dispatcher.aliases[alias] = command.upper()
        return True

    def remove_alias(self, alias: str) -> None:
        self.dispatcher.aliases.pop(alias.upper(), None)

    def add_pack_dir(self, path) -> None:
        i18n.register_pack_dir(path)

    def remove_pack_dir(self, path) -> None:
        i18n.unregister_pack_dir(path)

    def add_toolbar(self, spec) -> None:
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QToolBar

        from core.plugins import SEPARATOR
        from views.icons import command_icon

        bar = QToolBar(tr(spec.name), self)
        bar.setObjectName(f"plugin_{spec.id}_toolbar")
        bar.setMovable(True)
        for entry in spec.toolbar:
            if entry == SEPARATOR:          # as in a plugin's menu
                bar.addSeparator()
                continue
            icon = QIcon(str(entry.icon)) if entry.icon else command_icon(entry.command)
            act = QAction(icon, tr(entry.label), self)
            act.setToolTip(f"{tr(entry.label)} ({entry.command})")
            act.triggered.connect(
                lambda _=False, n=entry.command: self._invoke_command(n))
            bar.addAction(act)
        self.addToolBar(Qt.TopToolBarArea, bar)
        self._plugin_toolbars[spec.id] = bar

    def remove_toolbar(self, plugin_id: str) -> None:
        bar = self._plugin_toolbars.pop(plugin_id, None)
        if bar is not None:
            self.removeToolBar(bar)
            bar.setParent(None)        # gone from findChildren at once,
            bar.deleteLater()          # not at the next event-loop turn

    def menus_changed(self) -> None:
        self._build_menus()

    def echo(self, text: str) -> None:
        """What a plugin says goes to the command window."""
        self.command_line.echo(text)

    def _report_problem(self) -> None:
        """Open the issue chooser: three guided forms, Spanish welcome.

        The forms ask exactly what a report needs (the drawing, what wrote
        it, the version) -- a user finding this menu entry is worth more
        than any of it, so it lives one click under Help.
        """
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(
            QUrl("https://github.com/ingelibre/ingecad/issues/new/choose"))

    def _show_about(self) -> None:
        from core.version import __version__
        from views.about_dialog import AboutDialog

        dialog = AboutDialog(self, __version__)
        dialog.setAttribute(Qt.WA_DeleteOnClose)
        dialog.exec()

    def _set_language(self, code: str) -> None:
        """Switch the UI language, persist it, and retranslate live."""
        if code == i18n.current_language():
            return
        QSettings().setValue("language", code)
        previous = i18n.catalog()
        i18n.set_language(code)
        from views import qt_translations

        qt_translations.install(i18n.current_language())   # Qt's own buttons
        self._retranslate(previous)

    def _retranslate(self, previous: dict | None = None) -> None:
        name = self.document.name if self.document else tr("Untitled")
        self.setWindowTitle(f"IngeCAD — {name}")
        self._build_menus()
        # everything else built with tr() (#74): side tabs, status-bar
        # toggles, palettes, toolbars
        from views.retranslate import retranslate_tree

        retranslate_tree(self, previous or {})
        for panel in ("_layers_panel", "_properties_panel", "_styles_panel",
                      "_xrefs_panel"):
            widget = getattr(self, panel, None)
            refresh = getattr(widget, "refresh", None)
            if callable(refresh):
                refresh()
        self._update_space_button()
        # the property combos (ByLayer...) hold user names too, so they are
        # rebuilt rather than walked: their cache key is dropped
        self._props_combo_key = object()       # never equal: rebuild them
        self._refresh_props_toolbar()

    # -- command line -----------------------------------------------------------
    def _build_command_line(self) -> None:
        self.command_line = CommandLine(self)
        dock = QDockWidget(tr("Command"), self)
        dock.setObjectName("command_dock")
        dock.setWidget(self.command_line)
        dock.setFeatures(QDockWidget.DockWidgetFloatable | QDockWidget.DockWidgetMovable)
        dock.setTitleBarWidget(QWidget(dock))  # slim: no dock title bar
        self.addDockWidget(Qt.BottomDockWidgetArea, dock)
        self._command_dock = dock

        self.history = History()
        # Every mutation of the drawing goes through History; that is where
        # the automatic save's gate belongs, and why no call site had to
        # learn about it.
        self.history.before_mutation = self._autosave_gate
        self.dispatcher = Dispatcher(echo=self.command_line.echo,
                                     echo_prompt=self.command_line.echo_prompt)

        from views.tool_controller import ToolController

        self.tools = ToolController(self)
        self.viewport.tool_delegate = self.tools
        self.tools.changed.connect(self.viewport.update)

        self._register_commands()
        self.command_line.set_completions(self.dispatcher.known_names())
        self.command_line.submitted.connect(self._on_command_submitted)
        # Ctrl+Z in the command line means the drawing, as in AutoCAD.
        self.command_line.undo_requested.connect(self._cmd_undo)
        self.command_line.redo_requested.connect(self._cmd_redo)
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
        if self.tools.active() or self.dispatcher.pending_prompt is not None:
            self.command_line.echo_answer(text)     # "prompt: answer"
        else:
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
        ("snap", "F9", "SNAP", "Snap to grid"),
        ("grid", "F7", "GRID", "Grid display"),
        ("ortho", "F8", "ORTHO", "Ortho mode"),
        ("polar", "F10", "POLAR", "Polar tracking"),
        ("osnap", "F3", "OSNAP", "Object snap"),
        ("otrack", "F11", "OTRACK", "Object snap tracking"),
        ("dyn", "F12", "DYN", "Dynamic input"),
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
            b.setContextMenuPolicy(Qt.CustomContextMenu)
            b.customContextMenuRequested.connect(
                lambda pos, k=key: self._mode_context_menu(k, pos))
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
        self._build_pick_filter(style)
        self._build_annotation_controls(style)
        self._build_statusbar_customization(style)
        self._load_osnap_modes()
        self._load_display_settings()
        self._build_acad_shortcuts()
        # dynamic input echoes what is being typed beside the cursor
        self.command_line.input.textChanged.connect(
            lambda _text: self.viewport.update() if self.tools.dyn_on else None)

    #: AutoCAD's default keyboard shortcuts (Command Reference, "Shortcut
    #: keys"), the ones IngeCAD has something to answer with. F3/F7/F8/F9/F10
    #: live on the status-bar buttons above; F2 on the text window; the
    #: clipboard, Delete and Ctrl+A on the canvas actions of the Edit menu;
    #: Ctrl+N/O/S/P/Q/Z/Y on the menus. Missing on purpose: F11 (object snap
    #: tracking) and F12 (dynamic input), which are features IngeCAD does
    #: not have yet, and F4/F5/F6/Ctrl+D/E/T (3D snap, isoplanes, dynamic
    #: UCS, tablet), which the product's own filter keeps out.
    _ACAD_SHORTCUTS = (
        ("Ctrl+B", "snap"),           # SNAP, like F9
        ("Ctrl+G", "grid"),           # GRID, like F7
        ("Ctrl+L", "ortho"),          # ORTHO, like F8
        ("Ctrl+U", "polar"),          # POLAR, like F10
        ("Ctrl+F", "osnap"),          # OSNAP, like F3
    )

    def _build_acad_shortcuts(self) -> None:
        from PySide6.QtGui import QShortcut

        self._acad_shortcuts = []

        def bind(keys: str, slot) -> None:
            self._acad_shortcuts.append(QShortcut(QKeySequence(keys), self, slot))

        for keys, mode in self._ACAD_SHORTCUTS:
            bind(keys, lambda m=mode: self._toggle_mode(m))
        bind("Ctrl+1", self.toggle_properties_panel)          # PROPERTIES palette
        bind("Ctrl+9", self._toggle_command_line)             # COMMANDLINE / COMMANDLINEHIDE
        bind("Ctrl+W", self._toggle_selection_cycling)        # SELECTIONCYCLING
        bind("Ctrl+I", self._toggle_coords)                   # COORDS
        bind("Ctrl+J", self._repeat_last_command)             # like Enter
        bind("Ctrl+M", self._repeat_last_command)
        bind("Ctrl+[", self._on_prompt_cancelled)             # like Esc
        bind("Ctrl+\\", self._on_prompt_cancelled)
        bind("Ctrl+PgUp", lambda: self._step_layout(-1))      # previous layout tab
        bind("Ctrl+PgDown", lambda: self._step_layout(1))     # next layout tab
        bind("Ctrl+Tab", self._next_drawing)                  # next drawing (tab)
        bind("Ctrl+Shift+Tab", lambda: self._next_drawing(-1))
        bind("Ctrl+F4", self.close_document)                  # CLOSE

    def _toggle_command_line(self) -> None:
        dock = self._command_dock
        if dock.isVisible():
            dock.hide()
        else:
            dock.show()
            self.command_line.input.setFocus()
            self.command_line.echo(tr("Command line shown (Ctrl+9 hides it)."))

    def _toggle_selection_cycling(self) -> None:
        self.tools.cycling_on = not self.tools.cycling_on
        self.tools.reset_pick_cycle()
        self.command_line.echo(tr("Selection cycling: {state}",
                                  state=tr("on") if self.tools.cycling_on else tr("off")))

    def _toggle_coords(self) -> None:
        self._coords_on = not getattr(self, "_coords_on", True)
        self._coords_label.setVisible(self._coords_on)
        self.command_line.echo(tr("Coordinate display: {state}",
                                  state=tr("on") if self._coords_on else tr("off")))

    def _repeat_last_command(self) -> None:
        """Ctrl+J / Ctrl+M: exactly what Enter does at the prompt."""
        if self.tools.active() or self.tools._selecting_for is not None:
            if not self.tools.on_text(""):
                self.dispatcher.submit("")
            return
        self.dispatcher.submit("")

    def _step_layout(self, delta: int) -> None:
        """Ctrl+PgUp / Ctrl+PgDown: the previous / next layout tab."""
        if self.document is None:
            return
        names = list(self._layout_names())
        if len(names) < 2 or self._active_layout not in names:
            return
        index = (names.index(self._active_layout) + delta) % len(names)
        self.switch_layout(names[index])

    def _next_drawing(self, step: int = 1) -> None:
        """Ctrl+Tab: the next drawing tab; with one tab, the next window."""
        if len(self._sessions) > 1:
            self.step_document(step)
        else:
            self._next_window()

    def _next_window(self) -> None:
        """Ctrl+Tab: the next open drawing window."""
        from PySide6.QtWidgets import QApplication

        windows = [w for w in QApplication.topLevelWidgets()
                   if isinstance(w, MainWindow) and w.isVisible()]
        if self in windows and len(windows) > 1:
            other = windows[(windows.index(self) + 1) % len(windows)]
            other.raise_()
            other.activateWindow()

    def _cmd_select_all(self) -> None:
        count = self.tools.select_all()
        self.command_line.echo(tr("{n} object(s) selected.", n=count))
        self.viewport.update()

    def add_appimage_to_menu(self) -> None:
        """Write the launcher + icon for the running AppImage."""
        from core.appimage import appimage_path, integrate

        img = appimage_path()
        if img is None:
            return
        try:
            f = integrate(img)
        except OSError as exc:
            QMessageBox.warning(self, tr("Add to the applications menu"),
                                str(exc))
            return
        self.command_line.echo(tr("Launcher added: {path}", path=str(f)))

    def remove_appimage_from_menu(self) -> None:
        from core.appimage import remove

        remove()
        self.command_line.echo(
            tr("Launcher removed from the applications menu."))

    def _cmd_help(self, *args) -> None:
        """HELP / F1: the product's site, where the documentation lives."""
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        url = "https://ingecad.org"
        QDesktopServices.openUrl(QUrl(url))
        self.command_line.echo(tr("Help: {url}", url=url))

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

    # -- annotation scale (A2 of docs/plan-escala-anotativa.md) ------------------
    #: ANNOAUTOSCALE: a registry setting in AutoCAD (initial -4); negative is
    #: off, remembering which positive value turning it on restores.
    SETTING_ANNOAUTOSCALE = "annotation/annoautoscale"

    def annoautoscale(self) -> int:
        from core.prefs import int_pref

        value = int_pref(self.SETTING_ANNOAUTOSCALE, -4, -4, 4)
        return value if value != 0 else -4

    def _set_annoautoscale(self, value: int) -> None:
        from PySide6.QtCore import QSettings

        QSettings().setValue(self.SETTING_ANNOAUTOSCALE, int(value))
        self._refresh_annotation_controls()

    def _build_pick_filter(self, style: str) -> None:
        """The selection filter by type (core.pickfilter): lit while it
        keeps some types out of every pick."""
        from PySide6.QtWidgets import QToolButton

        self._pick_filter_btn = QToolButton(self)
        self._pick_filter_btn.setText(tr("FILTER"))
        self._pick_filter_btn.setCheckable(True)
        self._pick_filter_btn.setStyleSheet(style)
        self._pick_filter_btn.setFocusPolicy(Qt.NoFocus)
        self._pick_filter_btn.clicked.connect(
            lambda _=False: self._show_pick_filter())
        self.statusBar().addPermanentWidget(self._pick_filter_btn)
        self._refresh_pick_filter_button()

    def _show_pick_filter(self) -> None:
        from views.pick_filter_popup import PickFilterPopup

        self._refresh_pick_filter_button()    # a click must not toggle it
        popup = PickFilterPopup(self)
        popup.setAttribute(Qt.WA_DeleteOnClose)
        button = self._pick_filter_btn
        popup.adjustSize()
        corner = button.mapToGlobal(button.rect().topLeft())
        popup.move(corner.x(), corner.y() - popup.height())
        popup.show()

    def set_pick_filter(self, allowed) -> None:
        """Only these object types (core.pickfilter names) may be picked;
        None switches the filter off."""
        from core import pickfilter

        self.tools.set_pick_filter(allowed)
        self._refresh_pick_filter_button()
        if allowed is None:
            self.command_line.echo(tr("Selection filter off."))
        elif not allowed:
            self.command_line.echo(tr("Selection filter: nothing can be selected."))
        else:
            self.command_line.echo(tr(
                "Selection filter: only {types}.",
                types=", ".join(pickfilter.display(t) for t in sorted(allowed))))

    def _refresh_pick_filter_button(self) -> None:
        button = getattr(self, "_pick_filter_btn", None)
        if button is None:
            return
        from core import pickfilter

        allowed = self.tools.pick_filter
        button.setChecked(allowed is not None)
        if allowed is None:
            button.setToolTip(tr("Selection filter by object type: off"))
        elif not allowed:
            button.setToolTip(tr("Selection filter by object type: nothing"))
        else:
            button.setToolTip(tr(
                "Selection filter by object type: only {types}",
                types=", ".join(pickfilter.display(t) for t in sorted(allowed))))

    def _build_annotation_controls(self, style: str) -> None:
        """AutoCAD's status-bar annotation scale ("Annotation Scale of the
        current view"), with the two toggles beside it: ANNOALLVISIBLE (show
        annotative objects of every scale) and ANNOAUTOSCALE (add the new
        scale to the objects when it changes)."""
        from PySide6.QtWidgets import QComboBox, QToolButton

        self._anno_visible_btn = QToolButton(self)
        self._anno_visible_btn.setText("\u25b2\u2217")
        self._anno_visible_btn.setCheckable(True)
        self._anno_visible_btn.setStyleSheet(style)
        self._anno_visible_btn.setFocusPolicy(Qt.NoFocus)
        self._anno_visible_btn.setToolTip(
            tr("Annotation visibility: show annotative objects of every "
               "scale (ANNOALLVISIBLE)"))
        self._anno_visible_btn.clicked.connect(
            lambda on: self._cmd_annoallvisible("1" if on else "0"))
        self.statusBar().addPermanentWidget(self._anno_visible_btn)

        self._anno_auto_btn = QToolButton(self)
        self._anno_auto_btn.setText("\u25b2+")
        self._anno_auto_btn.setCheckable(True)
        self._anno_auto_btn.setStyleSheet(style)
        self._anno_auto_btn.setFocusPolicy(Qt.NoFocus)
        self._anno_auto_btn.setToolTip(
            tr("Add scales to annotative objects when the annotation scale "
               "changes (ANNOAUTOSCALE)"))
        self._anno_auto_btn.clicked.connect(
            lambda _=False: self._set_annoautoscale(-self.annoautoscale()))
        self.statusBar().addPermanentWidget(self._anno_auto_btn)

        self._anno_scale_combo = QComboBox(self)
        self._anno_scale_combo.setToolTip(
            tr("Annotation scale of the current view"))
        self._anno_scale_combo.setMinimumWidth(80)
        self._anno_scale_combo.setFocusPolicy(Qt.NoFocus)
        self._anno_scale_combo.setStyleSheet(
            "QComboBox { font-size: 11px; combobox-popup: 0; }")
        self._anno_scale_combo.setMaxVisibleItems(16)
        self._anno_scale_combo.activated.connect(self._on_anno_scale_combo)
        self.statusBar().addPermanentWidget(self._anno_scale_combo)
        # One click for the selection (Rafael's review 6: the scale had to
        # reach the selected dimensions through a dialog he never found)
        self._anno_add_btn = QToolButton(self)
        self._anno_add_btn.setText("+")
        self._anno_add_btn.setStyleSheet(style)
        self._anno_add_btn.setFocusPolicy(Qt.NoFocus)
        self._anno_add_btn.setToolTip(
            tr("Add the current annotation scale to the selected annotative "
               "objects (AIOBJECTSCALEADD)"))
        self._anno_add_btn.clicked.connect(
            lambda _=False: self.tools.start_tool("AIOBJECTSCALEADD"))
        self.statusBar().addPermanentWidget(self._anno_add_btn)
        self.tools.changed.connect(self._refresh_annotation_controls)
        self._refresh_annotation_controls()

    def _annotation_target(self):
        """(viewport or None, editable): the space whose annotation scale
        the control shows. Model tab: CANNOSCALE; inside a viewport: its
        own; on the sheet itself annotations are paper, fixed at 1:1."""
        vp = getattr(self, "_active_vp", None)
        if vp is not None and vp.is_alive:
            return vp, True
        return None, getattr(self, "_active_layout", "Model") == "Model"

    def _refresh_annotation_controls(self) -> None:
        combo = getattr(self, "_anno_scale_combo", None)
        if combo is None:
            return
        from core import annotative

        auto = getattr(self, "_anno_auto_btn", None)
        if auto is not None:
            auto.setChecked(self.annoautoscale() > 0)
        document = self.document
        combo.blockSignals(True)
        combo.clear()
        if document is None:
            combo.setEnabled(False)
            combo.blockSignals(False)
            return
        doc = document.doc
        vp, editable = self._annotation_target()
        scales = annotative.scale_list(doc)
        current = (annotative.viewport_scale(vp) if vp is not None
                   else annotative.current_scale(doc))
        current_name = current.name if current is not None else "1:1"
        # the drawing's list plus the standard scales it lacks: a DWG from
        # another program carries none, and Rafael's showed only 1:1
        # (standard_scale() adds one to the drawing when it is chosen)
        from core.units import STANDARD_SCALES, scale_text

        factors = {s.name: s.factor for s in scales}
        for num, den in STANDARD_SCALES:
            factors.setdefault(scale_text(num, den), den / num)
        names = sorted(factors, key=lambda n: (-factors[n], n))
        if current_name not in names:
            names.insert(0, current_name)
        for name in names:
            combo.addItem(name, name)
        combo.setCurrentIndex(max(0, combo.findData(current_name)))
        combo.setEnabled(editable)
        combo.blockSignals(False)
        visible = getattr(self, "_anno_visible_btn", None)
        if visible is not None:
            layout = (doc.modelspace() if self._active_layout == "Model"
                      or vp is not None
                      else doc.layouts.get(self._active_layout))
            visible.setChecked(annotative.all_visible(layout))

    def _on_anno_scale_combo(self, index: int) -> None:
        name = self._anno_scale_combo.itemData(index)
        if name:
            self.set_annotation_scale(name)

    def set_annotation_scale(self, name: str) -> bool:
        """Make ``name`` the annotation scale of the current view: CANNOSCALE
        on the Model tab, the active viewport's own inside one. One undo
        step; ANNOAUTOSCALE > 0 also adds it to the objects that supported
        the old one."""
        from core import annotative

        if self.document is None:
            return False
        doc = self.document.doc
        if annotative.standard_scale(doc, name) is None:
            self.command_line.echo(
                tr("Scale \"{name}\" is not in the drawing's scale list.",
                   name=name))
            self._refresh_annotation_controls()
            return False
        vp, editable = self._annotation_target()
        if not editable:
            self.command_line.echo(
                tr("On the sheet annotations are paper: 1:1. Enter a viewport "
                   "(MSPACE) to set its annotation scale."))
            self._refresh_annotation_controls()
            return False
        self._vp_gesture_commit()
        self.history.execute(annotative.SetAnnotationScaleCommand(
            name, viewport=vp, autoscale=self.annoautoscale() > 0))
        self.command_line.echo(tr("Annotation scale: {name}", name=name))
        self.invalidate_vp_model_cache()
        self.regen_in_memory()
        self._refresh_annotation_controls()
        return True

    def _cmd_cannoscale(self, *args):
        """CANNOSCALE (p. 2176): the name of the current annotation scale;
        only a named scale that exists in the drawing's list is taken."""
        from core import annotative
        from core.actions import Prompt

        if self.document is None:
            return None
        if args and str(args[0]).strip():
            self.set_annotation_scale(str(args[0]).strip())
            return None
        vp, _editable = self._annotation_target()
        current = (annotative.viewport_scale(vp) if vp is not None
                   else annotative.current_scale(self.document.doc))
        name = current.name if current is not None else "1:1"

        def answer(text: str):
            if text.strip():
                self.set_annotation_scale(text.strip())
            return None

        return Prompt(tr("Enter new value for CANNOSCALE <{name}>:", name=name),
                      answer)

    def _cmd_annoautoscale(self, *args):
        """ANNOAUTOSCALE (p. 2151): -4..4, negative = off keeping the mode."""
        from core.actions import Prompt

        def answer(text: str):
            text = text.strip()
            if not text:
                return None
            try:
                value = int(text)
            except ValueError:
                value = None
            if value is None or value == 0 or not -4 <= value <= 4:
                self.command_line.echo(tr("Requires an integer between -4 and 4, "
                                          "not 0."))
                return None
            self._set_annoautoscale(value)
            return None

        if args and str(args[0]).strip():
            return answer(str(args[0]))
        return Prompt(tr("Enter new value for ANNOAUTOSCALE <{v}>:",
                         v=self.annoautoscale()), answer)

    def _cmd_annoallvisible(self, *args):
        """ANNOALLVISIBLE (p. 2150): saved per model space and per layout."""
        from core import annotative
        from core.actions import Prompt

        if self.document is None:
            return None
        doc = self.document.doc
        layout = (doc.modelspace() if self._active_layout == "Model"
                  or getattr(self, "_active_vp", None) is not None
                  else doc.layouts.get(self._active_layout))

        def answer(text: str):
            text = text.strip()
            if not text:
                return None
            if text not in ("0", "1"):
                self.command_line.echo(tr("Requires 0 or 1."))
                self._refresh_annotation_controls()
                return None
            on = text == "1"
            if on != annotative.all_visible(layout):
                self.history.execute(annotative.SetAllVisibleCommand(layout, on))
                self.invalidate_vp_model_cache()
                self.regen_in_memory()
            self._refresh_annotation_controls()
            return None

        if args and str(args[0]).strip():
            return answer(str(args[0]))
        return Prompt(tr("Enter new value for ANNOALLVISIBLE <{v}>:",
                         v=1 if annotative.all_visible(layout) else 0), answer)

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

    def _set_mode_state(self, key: str, value: bool) -> None:
        if key == "grid":
            self.viewport.grid_on = value
        elif key == "lwt":
            self.viewport.lwt_on = value
        else:
            setattr(self.tools, f"{key}_on", value)

    #: The toggles remembered as plain on/off. OSNAP is not one of them: it
    #: lives in its OSMODE bitcode with the running modes (osnap/osmode).
    _PERSISTED_MODES = ("snap", "grid", "ortho", "polar", "otrack", "dyn", "lwt")

    @staticmethod
    def _mode_setting_key(key: str) -> str:
        """Where a status-bar toggle is kept between sessions, per user, as
        AutoCAD keeps them in the profile. Grid and lineweight share Options
        > Display's keys: one question, one place."""
        from views.options_dialog import SETTING_GRID, SETTING_LWT

        return {"grid": SETTING_GRID, "lwt": SETTING_LWT}.get(
            key, f"statusbar/{key}")

    def _save_mode_states(self) -> None:
        """Remember every toggle as it is now, whichever way it was flipped
        (button, F-key, Ctrl shortcut, DSETTINGS, Options, LWDISPLAY).
        Before the saved states are read back nothing is written, or the
        defaults of a starting window would overwrite them."""
        if not getattr(self, "_mode_states_loaded", False):
            return
        saved = self.__dict__.setdefault("_saved_mode_states", {})
        settings = QSettings()
        for key in self._PERSISTED_MODES:
            value = bool(self._mode_state(key))
            if saved.get(key) is not value:
                settings.setValue(self._mode_setting_key(key), value)
                saved[key] = value

    # -- status bar customization (AutoCAD's right-click / Customization) -------
    #: What the status bar shows out of the box: the classic drafting
    #: toggles and the space button. The rest is one right-click away, and
    #: its F-key works either way (F11 still toggles tracking, and says so
    #: on the command line).
    SETTING_STATUSBAR_HIDDEN = "ui/statusbar_hidden"
    _STATUSBAR_HIDDEN_DEFAULT = ("otrack", "dyn", "lwt", "annovis",
                                 "annoauto", "version")

    def _statusbar_items(self) -> list:
        """(key, menu label, widgets) of everything that can be hidden,
        in the order they sit on the bar."""
        items = [("coords", tr("Coordinates"), [self._coords_label]),
                 ("version", tr("IngeCAD version"), [self._version_label]),
                 ("space", tr("Model/Paper space"), [self._space_btn])]
        for key, fkey, _label, tip in self._MODES:
            widgets = [self._mode_buttons[key]]
            if key == "osnap":
                widgets.append(self._osnap_arrow)
            items.append((key, tr(tip) + (f" ({fkey})" if fkey else ""), widgets))
        items += [("pickfilter", tr("Selection filter"), [self._pick_filter_btn]),
                  ("annovis", tr("Annotation visibility"), [self._anno_visible_btn]),
                  ("annoauto", tr("Annotation autoscale"), [self._anno_auto_btn]),
                  ("annoscale", tr("Annotation scale"),
                   [self._anno_scale_combo, self._anno_add_btn])]
        return items

    def _statusbar_hidden(self) -> set:
        from PySide6.QtCore import QSettings

        value = QSettings().value(self.SETTING_STATUSBAR_HIDDEN, None)
        if value is None:
            return set(self._STATUSBAR_HIDDEN_DEFAULT)
        if isinstance(value, str):
            return {v for v in value.split(",") if v}
        return {str(v) for v in value if v}

    def _set_statusbar_hidden(self, hidden: set) -> None:
        from PySide6.QtCore import QSettings

        QSettings().setValue(self.SETTING_STATUSBAR_HIDDEN,
                             ",".join(sorted(hidden)))
        self._apply_statusbar_visibility()

    def _apply_statusbar_visibility(self) -> None:
        hidden = self._statusbar_hidden()
        for key, _label, widgets in self._statusbar_items():
            for w in widgets:
                w.setVisible(key not in hidden)

    def _statusbar_menu(self, global_pos=None) -> None:
        """Right-click on the status bar, or its ≡ button: tick what
        the bar shows, as AutoCAD's and BricsCAD's status bar menus do."""
        from PySide6.QtGui import QCursor
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        hidden = self._statusbar_hidden()
        for key, label, _widgets in self._statusbar_items():
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(key not in hidden)
            action.toggled.connect(
                lambda on, k=key: self._set_statusbar_hidden(
                    (self._statusbar_hidden() - {k}) if on
                    else (self._statusbar_hidden() | {k})))
        menu.addSeparator()
        menu.addAction(tr("Show all"), lambda: self._set_statusbar_hidden(set()))
        menu.addAction(tr("Restore defaults"), lambda: self._set_statusbar_hidden(
            set(self._STATUSBAR_HIDDEN_DEFAULT)))
        menu.exec(global_pos or QCursor.pos())

    def _build_statusbar_customization(self, style: str) -> None:
        from PySide6.QtWidgets import QToolButton

        self._statusbar_custom_btn = QToolButton(self)
        self._statusbar_custom_btn.setText("≡")
        # its own look, not the dim unchecked-toggle grey: it is the way to
        # everything the bar hides, so it has to be found (Marco)
        self._statusbar_custom_btn.setStyleSheet("""
        QToolButton { color: #e8e8e8; font-size: 17px; font-weight: bold;
            padding: 0px 8px; border: 1px solid #4a5a6a; border-radius: 3px;
            background: #2f3a45; }
        QToolButton:hover { background: #3d5063; border-color: #6a8aa8; }
        QToolButton:pressed { background: #4a6480; }
        """)
        self._statusbar_custom_btn.setFocusPolicy(Qt.NoFocus)
        self._statusbar_custom_btn.setToolTip(tr("Customize the status bar"))
        self._statusbar_custom_btn.clicked.connect(
            lambda _=False: self._statusbar_menu())
        self.statusBar().addPermanentWidget(self._statusbar_custom_btn)
        bar = self.statusBar()
        bar.setContextMenuPolicy(Qt.CustomContextMenu)
        bar.customContextMenuRequested.connect(
            lambda pos: self._statusbar_menu(bar.mapToGlobal(pos)))
        self._apply_statusbar_visibility()

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
            if which == "otrack" and not value:
                self.tools.clear_tracking()
            self.viewport.update()
        self._update_mode_buttons()
        names = {"snap": tr("Snap"), "grid": tr("Grid"), "osnap": tr("Object snap"),
                 "ortho": tr("Ortho"), "polar": tr("Polar"),
                 "otrack": tr("Object snap tracking"), "dyn": tr("Dynamic input"),
                 "lwt": tr("Lineweight display")}
        state = tr("on") if value else tr("off")
        self.command_line.echo(f"{names[which]}: {state}")

    # -- running object snaps (the status-bar dropdown) ------------------------
    def _load_display_settings(self) -> None:
        """Restore the status-bar toggles as the user left them. Turning the
        grid, polar and lineweight back on at every start was a tester's
        daily chore (Rafael, 2026-10-18: only OSNAP was remembered). No
        drawing overrides them: IngeCAD reads none of GRIDMODE, ORTHOMODE,
        SNAPMODE... from a file, so the user's choice wins, as in AutoCAD's
        profile."""
        from views.options_dialog import _bool_setting

        for key in self._PERSISTED_MODES:
            self._set_mode_state(key, _bool_setting(
                self._mode_setting_key(key), bool(self._mode_state(key))))
        self._mode_states_loaded = True
        self._update_mode_buttons()

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
        from views.drafting_dialog import TAB_OSNAP

        self._drafting_settings(TAB_OSNAP)

    def refresh_grid_settings(self) -> None:
        """GRIDUNIT / GRIDMAJOR of the drawing on screen, and the grid
        behaviour, into the canvas -- at open, and after DSETTINGS."""
        from core import drafting

        drawing = self.document.doc if self.document is not None else None
        if drawing is None:
            self.viewport.set_grid_settings(10.0, 5, drafting.grid_adaptive(),
                                            drafting.grid_subdivide())
            return
        self.viewport.set_grid_settings(
            drafting.grid_unit(drawing), drafting.grid_major(drawing),
            drafting.grid_adaptive(), drafting.grid_subdivide())

    def _drafting_settings(self, tab: int = 0) -> None:
        """DSETTINGS: Snap and Grid / Polar Tracking / Object Snap."""
        from core import drafting
        from views.drafting_dialog import DraftingSettingsDialog

        dialog = DraftingSettingsDialog(
            self, self.document, osnap_modes=self.tools.osnap_modes,
            osnap_on=self.tools.osnap_on, polar_on=self.tools.polar_on,
            snap_on=self.tools.snap_on, grid_on=self.viewport.grid_on, tab=tab)
        if not dialog.exec():
            return
        # object snap
        self.tools.osnap_modes = set(dialog.modes())
        self.tools.osnap_on = dialog.osnap_on()
        self._save_osnap_modes()
        # polar tracking
        polar = dialog.polar
        drafting.set_polar_increment(polar.increment_value())
        drafting.set_polar_additional(polar.additional_values())
        drafting.set_polar_mode(polar.mode_value())
        self.tools.polar_on = polar.polar_on.isChecked()
        # snap and grid
        values = dialog.snap_grid.values()
        self.tools.snap_on = values["snap_on"]
        self.viewport.grid_on = values["grid_on"]
        drafting.set_grid_behaviour(values["adaptive"], values["subdivide"])
        if self.document is not None:
            drawing = self.document.doc
            changed = {}
            if abs(values["grid"] - drafting.grid_unit(drawing)) > 1e-12:
                changed["grid"] = values["grid"]
            if abs(values["snap"] - drafting.snap_unit(drawing)) > 1e-12:
                changed["snap"] = values["snap"]
            if values["major"] != drafting.grid_major(drawing):
                changed["major"] = values["major"]
            if changed:
                self.history.execute(drafting.SetGridCommand(**changed))
        self.refresh_grid_settings()
        self._update_mode_buttons()
        self.viewport.update()

    @staticmethod
    def _mode_settings_tab(key: str):
        """The Drafting Settings tab a status-bar toggle's Settings...
        opens (AutoCAD: Snap, Grid, Polar, Osnap and Otrack offer it), or
        None for a toggle with no page."""
        from views.drafting_dialog import TAB_OSNAP, TAB_POLAR, TAB_SNAP_GRID

        return {"snap": TAB_SNAP_GRID, "grid": TAB_SNAP_GRID,
                "polar": TAB_POLAR, "otrack": TAB_POLAR,
                "osnap": TAB_OSNAP}.get(key)

    def _mode_context_menu(self, key: str, pos) -> None:
        """Right-click on a status-bar toggle: Settings..., on its tab."""
        tab = self._mode_settings_tab(key)
        if tab is None:
            return
        button = self._mode_buttons[key]
        menu = QMenu(self)
        menu.addAction(tr("Settings..."), lambda: self._drafting_settings(tab))
        menu.exec(button.mapToGlobal(pos))

    def _update_mode_buttons(self) -> None:
        for key, b in self._mode_buttons.items():
            b.setChecked(self._mode_state(key))
        self._save_mode_states()

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

    def _refresh_document_panels(self) -> None:
        """Every panel that shows the drawing, after the drawing changed
        under it (a tab switch)."""
        for name in ("_layers_panel", "_styles_panel", "_properties_panel",
                     "_xrefs_panel"):
            panel = getattr(self, name, None)
            if panel is not None:
                panel.refresh()
        if getattr(self, "_props_toolbar", None) is not None:
            self._refresh_props_toolbar()

    def _drop_block_session(self) -> None:
        """The document a Block Editor session belongs to is being replaced.

        No save/discard question here: maybe_save_changes already asked about
        the whole drawing, and the definition was edited in place, so a saved
        drawing carries the editor's changes. What must not survive is the
        session object itself -- it kept the "Close the Block Editor first"
        guard alive over a NEW document that had no editor open, locking its
        layout tabs (found opening casa bueno over an editing session).
        """
        self._block_session = None
        if getattr(self, "_blockedit_toolbar", None) is not None:
            self._blockedit_toolbar.setVisible(False)

    def new_document(self, template: str | None = None) -> None:
        from core import templates as templates_mod

        document = templates_mod.new_document(template or self.startup_template())
        self._tab_for_new_document(document)      # a tab of its own (#71)
        self.document = document
        self._autosave_arm()          # a new drawing, a new countdown
        self._layout_scenes.clear()   # scenes of the previous drawing
        self._layout_cameras = {}
        self._active_layout = "Model"
        self._deactivate_viewport()
        self._update_space_button()
        self._refresh_layout_tabs()
        self.viewport.set_scene(None)
        self.tools.attach_document(self.document)
        self.refresh_grid_settings()
        self.plugins.document_opened(self.document)
        if self._layers_panel is not None:
            self._layers_panel.refresh()
        if getattr(self, "_styles_panel", None) is not None:
            self._styles_panel.refresh()
        if getattr(self, "_properties_panel", None) is not None:
            self._properties_panel.refresh()
        if getattr(self, "_xrefs_panel", None) is not None:
            self._xrefs_panel.refresh()    # not the last drawing's references
        self.setWindowTitle(f"IngeCAD — {tr('Untitled')}")
        self._refresh_file_tabs()

    # -- classic toolbars (Draw left, Modify top) ------------------------------
    def _build_toolbars(self) -> None:
        from PySide6.QtWidgets import QToolBar

        from views.icons import command_icon

        draw = [("LINE", tr("Line")), ("PLINE", tr("Polyline")),
                ("CIRCLE", tr("Circle")), ("ARC", tr("Arc")),
                ("REVCLOUD", tr("Revision Cloud")),
                ("SPLINE", tr("Spline")),
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
                  ("FILLET", tr("Fillet")), ("EXPLODE", tr("Explode"))]

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
        self._build_standard_toolbar()
        self._build_props_toolbar()
        self._build_blockedit_toolbar()

    def _build_standard_toolbar(self) -> None:
        """The classic Standard toolbar, in AutoCAD's own order (the 2011
        toolbar, filtered to what IngeCAD does): file group, clipboard +
        Match Properties, undo/redo, then the navigation group."""
        from PySide6.QtWidgets import QToolBar

        from views.icons import command_icon

        bar = QToolBar(tr("Standard"), self)
        bar.setObjectName("standard_toolbar")
        bar.setMovable(True)

        def cmd(name: str, label: str) -> None:
            act = QAction(command_icon(name), label, self)
            act.setToolTip(f"{label} ({name})")
            act.triggered.connect(lambda _=False, n=name: self._invoke_command(n))
            bar.addAction(act)

        def direct(icon: str, label: str, slot) -> None:
            act = QAction(command_icon(icon), label, self)
            act.setToolTip(label)
            act.triggered.connect(lambda _=False: slot())
            bar.addAction(act)

        direct("NEW", tr("New"), self.new_document)
        direct("OPEN", tr("Open"), self._open_dialog)
        direct("SAVE", tr("Save"), self.save_document)
        cmd("PLOT", tr("Plot"))
        bar.addSeparator()
        cmd("CUTCLIP", tr("Cut"))
        cmd("COPYCLIP", tr("Copy"))
        cmd("PASTECLIP", tr("Paste"))
        cmd("MATCHPROP", tr("Match Properties"))
        bar.addSeparator()
        direct("UNDO", tr("Undo"), self._cmd_undo)
        direct("REDO", tr("Redo"), self._cmd_redo)
        bar.addSeparator()
        cmd("PAN", tr("Pan"))
        direct("ZOOM_WINDOW", tr("Zoom Window"),
               lambda: self._invoke_command("ZOOM"))
        direct("ZOOM_PREVIOUS", tr("Zoom Previous"),
               self.viewport.zoom_previous)
        direct("ZOOM_EXTENTS", tr("Zoom Extents"), self.viewport.zoom_extents)

        self._standard_toolbar = bar
        # One row with Modify — screens are wide; the user can drag them
        # apart if they prefer AutoCAD's stack.
        self.insertToolBar(self._modify_toolbar, bar)

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
        self.tools.changed.connect(self._refresh_layers_panel_if_tables_changed)
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
                            ("DIMCONTINUE", tr("Continue")),
                            ("MLEADER", tr("Multileader"))):
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
        zoom = layout_ops.xp_zoom_command(vp, num / den)
        # AutoCAD keeps a viewport's annotation scale in step with its scale:
        # left at 1:1, a 1:5 viewport drew its annotative text five times
        # too small next to a 1:1 one (#73). One undo step for both.
        from core import annotative
        from core.commands import CompositeCommand
        from core.units import scale_text

        scale = annotative.standard_scale(self.document.doc, scale_text(num, den))
        if scale is not None:
            command = CompositeCommand("VPSCALE", [
                zoom, annotative.SetAnnotationScaleCommand(
                    scale.name, viewport=vp,
                    autoscale=self.annoautoscale() > 0)])
        else:
            command = zoom
        self.history.execute(command)
        self.command_line.echo(tr("Viewport scale set to {scale}.",
                                  scale=layout_ops.scale_label(num / den)))
        self.invalidate_vp_model_cache()
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

    def _tables_key(self):
        """What the layer-driven controls show, as a value: the layers with
        their colours and the linetypes. Same content, same key -- so a
        refresh keyed on it costs nothing until a table really changes."""
        from core import layers as layer_ops

        if self.document is None:
            return None
        return (id(self.document),
                tuple(layer_ops.layer_names_and_colors(self.document)),
                tuple(layer_ops.available_linetypes(self.document)))

    def _refresh_layers_panel_if_tables_changed(self) -> None:
        """A command that creates or drops a layer (a plugin's grid on its
        own layer, an undo of it) must reach the Layers tab like it reaches
        the layer control -- and, like it, only when the tables changed."""
        if self._layers_panel is None:
            return
        key = self._tables_key()
        if key != getattr(self, "_layers_panel_key", object()):
            self._layers_panel_key = key
            self._layers_panel.refresh()

    def _refresh_props_toolbar(self) -> None:
        from core import layers as layer_ops
        from views.color_dialog import swatch_icon
        from views.layers_panel import fill_color_combo

        self._props_loading = True
        # This runs on EVERY selection change, but the four lists only change
        # when the DRAWING's tables do -- rebuilding them (an icon rendered
        # per row) cost ~39 ms of the stall the user felt on releasing a big
        # selection window. The key is the list CONTENT, not the revision: a
        # layer can be added without any command bumping it, and keying on
        # the revision left such a layer missing from the control.
        key = self._tables_key()
        if key != getattr(self, "_props_combo_key", object()):
            self._layer_combo.clear()
            self._color_combo.clear()
            if self.document is not None:
                for name, color in layer_ops.layer_names_and_colors(self.document):
                    # small colour chip beside each layer name (BricsCAD look)
                    self._layer_combo.addItem(swatch_icon(color), name)
            fill_color_combo(self._color_combo)
            self._fill_linetype_combo()
            self._fill_lineweight_combo()
            self._props_combo_key = key
        if self.document is not None:
            # AutoCAD's Layer control: with a selection it shows the
            # selected object's layer (blank when mixed); with nothing
            # selected, the current layer.
            selection = self.tools._selection_entities() if self.tools else []
            shown = None
            for e in selection:
                name = e.dxf.get("layer", "0")
                if shown is None:
                    shown = name
                elif name != shown:
                    shown = None
                    break
            if not selection:
                shown = layer_ops.current_layer_name(self.document)
            idx = self._layer_combo.findText(shown) if shown else -1
            self._layer_combo.setCurrentIndex(idx)
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
            label = tr(name) if name in ("ByLayer", "ByBlock") else name
            combo.addItem(linetype_icon(name, self.document), label, name)
        # AutoCAD's Linetype control ends in "Other...", the Linetype Manager
        combo.addItem(tr("Other..."), _OTHER_LINETYPE)

    def _fill_lineweight_combo(self) -> None:
        from core import layers as layer_ops
        from views.layers_panel import lineweight_icon

        combo = getattr(self, "_lineweight_combo", None)
        if combo is None:
            return
        combo.clear()
        for value in (-1, -2, *layer_ops.LINEWEIGHTS):
            combo.addItem(lineweight_icon(value),
                          layer_ops.lineweight_label(value), value)

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
                default = layer_ops.CURRENT_DEFAULTS[prop]
                value = _MIXED = object()
                for e in selection:
                    v = e.dxf.get(prop, default)
                    if value is _MIXED:
                        value = v
                    elif v != value:
                        value = None      # mixed: AutoCAD blanks the control
                        break
                if value is _MIXED:
                    value = None
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
        # Marco's rule: picking a layer here means "let the layer drive the
        # look" — the color snaps back to ByLayer in the same gesture, so a
        # ByBlock/explicit override never has to be cleared by hand after.
        if selection:
            from core import actions
            from core.commands import CompositeCommand
            self.history.execute(CompositeCommand(tr("layer"), [
                actions.SetPropertyCommand(selection, "layer", name),
                actions.SetPropertyCommand(selection, "color", 256),
            ]))
            self.regen_in_memory()
        else:
            layer_ops.set_current_layer(self.document, name)
            layer_ops.set_current_property(self.document, "color", 256)
        self._sync_panels()

    def _on_prop_color(self, index: int) -> None:
        self._apply_property("color", self._color_combo.itemData(index))

    def _on_prop_linetype(self, index: int) -> None:
        value = self._linetype_combo.itemData(index)
        if value == _OTHER_LINETYPE:
            self._cmd_linetype()
            return
        self._apply_property("linetype", value)

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
            return layer_ops.lineweight_label(value)
        if prop == "color":
            from views.color_dialog import aci_label

            return aci_label(value)
        return str(value)

    def _sync_panels(self) -> None:
        if self._layers_panel is not None:
            self._layers_panel.refresh()
        if getattr(self, "_properties_panel", None) is not None:
            self._properties_panel.refresh()
        self._refresh_props_toolbar()

    def _ucs_from_menu(self, option: str) -> None:
        """Tools > New UCS > ...: UCS, then the option, as if typed."""
        self._invoke_command("UCS")
        if option and self.tools.active():
            self._on_command_submitted(option)

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
        from views.xrefs_panel import XrefsPanel

        self._xrefs_panel = XrefsPanel(self)     # External References (#33)

        tabs = QTabWidget(self)
        tabs.setObjectName("sidebar_tabs")
        tabs.setTabPosition(QTabWidget.South)   # tabs at the bottom (IngeTrazo)
        tabs.addTab(self._layers_panel, tr("Layers"))
        tabs.addTab(self._properties_panel, tr("Properties"))
        tabs.addTab(self._styles_panel, tr("Palette"))
        tabs.addTab(self._xrefs_panel, tr("Xrefs"))
        self._sidebar_tabs = tabs

        dock = QDockWidget(self)
        dock.setObjectName("sidebar_dock")
        dock.setTitleBarWidget(QWidget(dock))   # no dock chrome
        dock.setFeatures(QDockWidget.NoDockWidgetFeatures)  # fixed, always there
        dock.setWidget(tabs)
        dock.setMinimumWidth(250)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)
        self._layers_dock = dock
        settings = QSettings()
        self._sidebar_width = max(250, int(settings.value(
            SETTING_SIDEBAR_WIDTH, 280)))
        self.resizeDocks([dock], [self._sidebar_width], Qt.Horizontal)
        self._build_sidebar_handle()
        if str(settings.value(SETTING_SIDEBAR_SHOWN, "true")).lower() == "false":
            self._act_sidebar.setChecked(False)

    def _build_sidebar_handle(self) -> None:
        """LibreOffice's sidebar handle, as in IngeTrazo: a slim button
        sitting ON the line where the sidebar is resized, half-way down,
        with a chevron. Click folds the sidebar away; the handle then rests
        at the window's right edge, chevron pointing back in, and click
        brings the sidebar back at the width it had. View > Sidebar
        (Ctrl+F5) is the same toggle."""
        from PySide6.QtCore import QSize
        from PySide6.QtWidgets import QToolButton

        from views.icons import _ACCENT, command_icon

        btn = QToolButton(self)
        btn.setObjectName("sidebar_handle")
        btn.setFixedSize(14, 56)
        btn.setIconSize(QSize(12, 12))
        btn.setIcon(command_icon("SIDEBAR_FOLD"))
        btn.setToolTip(self._act_sidebar.toolTip())
        btn.setCursor(Qt.PointingHandCursor)
        btn.setAutoRaise(True)
        btn.setStyleSheet(
            "QToolButton { background: palette(mid); border: none;"
            " border-radius: 4px; }"
            f"QToolButton:hover {{ background: {_ACCENT.name()}; }}")
        act = self._act_sidebar
        btn.clicked.connect(lambda: act.setChecked(not act.isChecked()))
        self._sidebar_handle = btn
        # Qt restacks the dock above its siblings when it is shown again:
        # every change re-places, and so re-raises, the handle.
        self._layers_dock.visibilityChanged.connect(
            lambda _v: QTimer.singleShot(0, self._place_sidebar_handle))
        self._place_sidebar_handle()

    def _place_sidebar_handle(self) -> None:
        """On the resize line between the drawing and the sidebar, centred
        on the drawing's height; at the window's edge when folded -- inside
        the frameless window's resize margin, which would take the click."""
        btn = getattr(self, "_sidebar_handle", None)
        if btn is None:
            return
        view = self.viewport
        edge = view.mapTo(self, QPoint(view.width(), 0))
        x = edge.x() - btn.width() // 2
        margin = 0 if self.isMaximized() else self.RESIZE_MARGIN
        x = max(0, min(x, self.width() - btn.width() - margin))
        y = edge.y() + (view.height() - btn.height()) // 2
        btn.move(x, max(0, y))
        btn.raise_()
        btn.setVisible(getattr(self, "_clean_screen_saved", None) is None)

    def _sidebar_folded(self) -> bool:
        return not self._act_sidebar.isChecked()

    def _set_sidebar_visible(self, on: bool) -> None:
        """Fold the sidebar away or bring it back at the width it had; the
        chevron turns to point the way. Remembered for the next session."""
        from views.icons import command_icon

        dock = getattr(self, "_layers_dock", None)
        if dock is None:
            return
        if on:
            dock.show()      # Qt gives it back the width it had
        else:
            if dock.isVisible():
                self._sidebar_width = max(250, dock.width())
                QSettings().setValue(SETTING_SIDEBAR_WIDTH, self._sidebar_width)
            dock.hide()
        QSettings().setValue(SETTING_SIDEBAR_SHOWN, bool(on))
        btn = self._sidebar_handle
        btn.setIcon(command_icon("SIDEBAR_FOLD" if on else "SIDEBAR_UNFOLD"))
        btn.setToolTip(self._act_sidebar.toolTip())
        QTimer.singleShot(0, self._place_sidebar_handle)   # after the relayout

    def _show_sidebar(self) -> None:
        """A command that opens a sidebar tab (LA, PROPERTIES, STYLE)
        unfolds the sidebar first."""
        if self._sidebar_folded():
            self._act_sidebar.setChecked(True)

    def toggle_layers_panel(self) -> None:
        # LA / Format>Layers focuses the Layers tab and refreshes it.
        if self._layers_panel is None:
            return
        self._show_sidebar()
        self._sidebar_tabs.setCurrentWidget(self._layers_panel)
        self._layers_panel.refresh()

    def toggle_properties_panel(self) -> None:
        # PROPERTIES / the shortcut menu focuses the Properties tab.
        if getattr(self, "_properties_panel", None) is None:
            return
        self._show_sidebar()
        self._sidebar_tabs.setCurrentWidget(self._properties_panel)
        self._properties_panel.refresh()

    def toggle_styles_panel(self) -> None:
        # STYLE / DIMSTYLE / Format menu focuses the Styles tab.
        if getattr(self, "_styles_panel", None) is None:
            return
        self._show_sidebar()
        self._sidebar_tabs.setCurrentWidget(self._styles_panel)
        self._styles_panel.refresh()

    # -- external references (#33) -------------------------------------------------
    def toggle_xrefs_panel(self) -> None:
        """XREF / EXTERNALREFERENCES / Insert menu: the palette tab."""
        if getattr(self, "_xrefs_panel", None) is None:
            return
        self._show_sidebar()
        self._sidebar_tabs.setCurrentWidget(self._xrefs_panel)
        self._xrefs_panel.refresh()

    def xrefs_changed(self) -> None:
        """An xref was attached, detached, re-pathed, unloaded or reloaded:
        the picture, the pick/snap caches and the palette all follow."""
        if self.document is None:
            return
        self.tools._invalidate_geometry()
        self.invalidate_vp_model_cache()
        self.regen_in_memory()
        panel = getattr(self, "_xrefs_panel", None)
        if panel is not None:
            panel.refresh()

    def _cmd_xref_cli(self, *args) -> Prompt | None:
        """-XREF: the command-line twin of the palette."""
        if self.document is None:
            return None
        if args:
            return self._xref_option(" ".join(str(a) for a in args))
        return Prompt(tr("Enter an option [?/Bind/Detach/Path/Unload/Reload/"
                         "Overlay/Attach] <Attach>:"), self._xref_option)

    def _xref_option(self, text: str) -> Prompt | None:
        from core import xrefs

        option = text.strip().upper()
        if option in ("", "A", "ATTACH", "O", "OVERLAY"):
            self.tools._xref_overlay_next = option in ("O", "OVERLAY")
            self.tools.start_tool("XATTACH")
            return None
        if option == "?":
            refs = xrefs.references(self.document)
            if not refs:
                self.command_line.echo(tr("No external references."))
            for ref in refs:
                self.command_line.echo(
                    f"{ref.name}  {tr(ref.status)}  "
                    f"{tr('Overlay') if ref.overlay else tr('Attach')}  {ref.path}")
            return self._cmd_xref_cli()
        if option in ("B", "BIND"):
            self.command_line.echo(
                tr("Bind is not available yet: the referenced drawing stays "
                   "external. Detach, or insert the file as a block."))
            return self._cmd_xref_cli()
        if option in ("D", "DETACH"):
            return Prompt(tr("Enter xref name(s) to detach:"), self._xref_detach)
        if option in ("P", "PATH"):
            return Prompt(tr("Edit xref path for which xref(s):"), self._xref_path_pick)
        if option in ("U", "UNLOAD"):
            return Prompt(tr("Enter xref name(s) to unload:"), self._xref_unload)
        if option in ("R", "RELOAD"):
            return Prompt(tr("Enter xref name(s) to reload:"), self._xref_reload)
        self.command_line.echo(tr("Invalid option keyword."))
        return self._cmd_xref_cli()

    def _xref_names(self, text: str) -> list[str]:
        from core import xrefs

        names = xrefs.match_names(self.document, text)
        if not names:
            self.command_line.echo(tr("No matching xref names."))
        return names

    def _xref_detach(self, text: str) -> None:
        from core import xrefs

        for name in self._xref_names(text):
            self.tools._execute(xrefs.DetachXrefCommand(name))
            self.command_line.echo(tr("Xref {name} detached.", name=name))
        self.xrefs_changed()

    def _xref_unload(self, text: str) -> None:
        from core import xrefs

        names = self._xref_names(text)
        xrefs.unload(self.document, names)
        for name in names:
            self.command_line.echo(tr("Xref {name} unloaded.", name=name))
        self.xrefs_changed()

    def _xref_reload(self, text: str) -> None:
        from core import xrefs

        names = self._xref_names(text)
        xrefs.reload(self.document, names)
        for name in names:
            self.command_line.echo(tr("Xref {name} reloaded.", name=name))
        self.xrefs_changed()

    def _xref_path_pick(self, text: str) -> Prompt | None:
        from core import xrefs

        names = self._xref_names(text)
        if not names:
            return None
        name = names[0]
        block = self.document.doc.blocks.get(name)
        self.command_line.echo(
            tr("Old path: {path}", path=xrefs.xref_path_of(block)))
        return Prompt(tr("New path:"),
                      lambda new, n=name: self._xref_set_path(n, new))

    def _xref_set_path(self, name: str, new_path: str) -> None:
        from core import xrefs

        new_path = new_path.strip()
        if not new_path:
            return
        self.tools._execute(xrefs.SetXrefPathCommand(name, new_path))
        self.xrefs_changed()

    def regen_in_memory(self, zoom_after: bool = False) -> None:
        """Rebuild the scene in a background thread; adopt when done.

        Never blocks the UI: the old scene keeps showing (edits already
        visible via overlay/surgical display) until the fresh one is ready.
        If a regen is in flight, one rerun is queued instead of stacking.
        """
        if self.document is None:
            return
        # A regen follows every command and every undo, so this is where the
        # projection is picked up when ZOOM nXP, a fit or an undo moved the
        # active viewport's view.
        self.refresh_space_placement()
        self._layout_scenes.clear()   # whoever asks for a regen calls it stale
        self._regen_zoom = self._regen_zoom or zoom_after
        if self._regen_worker is not None:
            self._regen_rerun = True
            return
        self._start_regen()

    def regen_in_background(self) -> None:
        """A big edit shown by a background regen: say so where the
        coordinates go until the new scene lands."""
        self._busy_regen = True
        self._set_busy(tr("Regenerating..."))
        self._loading_begin(tr("Regenerating..."))
        self.regen_in_memory()

    def _start_regen(self) -> None:
        self._regen_rerun = False
        # POINT symbols sized relative to the screen ($PDSIZE <= 0) take the
        # height of the view being regenerated, as in AutoCAD (#69)
        try:
            x0, y0, x1, y1 = self.viewport._view_world_rect()
            self.document.point_view_height = abs(y1 - y0)
        except Exception:                  # noqa: BLE001 - no view yet
            pass
        worker = RegenWorker(self.document, self._active_layout,
                             self.document.revision)
        worker.done.connect(self._on_regen_done)
        self._regen_worker = worker
        gc_guard.start(worker)

    def _on_regen_done(self, document, scene, revision, layout) -> None:
        worker, self._regen_worker = self._regen_worker, None
        if getattr(self, "_busy_regen", False) and not self._regen_rerun:
            self._busy_regen = False
            self._set_busy("")
            self._loading_end()
        if worker is not None:
            worker.wait()   # thread has emitted; joins immediately
            if scene is not None:
                self._regen_ms[layout] = worker.duration_ms
        if document is not self.document:
            # another drawing's tab: keep the scene for when it comes back,
            # and build the one in view if it asked while this ran
            for session in self._sessions:
                if (session.document is document and scene is not None
                        and revision == document.revision
                        and layout == session.active_layout):
                    session.layout_scenes[layout] = (revision, scene)
            if self._regen_rerun and self.document is not None:
                self._start_regen()
            return
        stale = (self._regen_rerun
                 or scene is None
                 or revision != self.document.revision
                 or layout != self._active_layout)
        if stale:
            self._start_regen()
            return
        self.viewport.set_scene(scene)
        self.tools.mark_scene_merged()
        self._layout_scenes[layout] = (revision, scene)
        self._vp_sheet_stale = False          # this bake IS the current view
        if layout != "Model" and getattr(self, "_vp_warm_pending", False):
            # the sheet is up: build the model for navigating its viewports
            # now, so a double-click finds it ready instead of a couple of
            # seconds later (Marco's video: "demora unos segundos")
            self._vp_warm_pending = False
            self._vp_warm_live_scene()
        if self.viewport._live_vp is not None:
            # A viewport gesture was live over the old sheet. If it is still
            # going (a new burst began while this regen ran), the fresh
            # sheet's copy of the model has to hide too or it shows under
            # the live one; if it has settled, this sheet IS the view and
            # the live matrix retires.
            if self._vp_gesture is not None:
                self._vp_content_hidden = False
                self._vp_hide_baked_content()
            else:
                self._vp_live_stop()
        if self._regen_view_for is not None and self._regen_view_for == layout:
            self._regen_view_for = None
            self._regen_zoom = False
            self._show_tab_view(layout)
        elif self._regen_zoom:
            self._regen_zoom = False
            self.viewport.zoom_extents()

    # -- each tab's own view (core/saved_views.py) -------------------------------
    def _current_view(self):
        """((cx, cy, height in units), aspect) of the canvas."""
        v = self.viewport.view
        return (v.cx, v.cy, v.height / v.scale), v.width / max(1, v.height)

    def _remember_tab_view(self) -> None:
        if self._block_session is not None:
            return                       # the editor's view is the block's
        v = self.viewport.view
        self._layout_cameras[self._active_layout] = (v.cx, v.cy, v.scale)

    def _show_tab_view(self, layout: str) -> None:
        """A tab shows the view it was left with; the first time, the view
        the drawing was saved with; failing that, its extents."""
        from core import saved_views

        view = self.viewport.view
        camera = self._layout_cameras.get(layout)
        if camera is not None:
            view.cx, view.cy, view.scale = camera
            self.viewport.update()
            return
        saved = (saved_views.saved_view(self.document.doc, layout)
                 if self.document is not None else None)
        aspect = view.width / max(1, view.height)
        if saved is not None and saved_views.near(
                saved, self.viewport.scene_bounds(), aspect):
            view.cx, view.cy = saved[0], saved[1]
            view.scale = min(max(view.height / saved[2], view.MIN_SCALE),
                             view.MAX_SCALE)
            self.viewport.update()
            return
        self.viewport.zoom_extents()

    def _store_views_for_save(self) -> None:
        """Every tab's view into the drawing, where AutoCAD reads it."""
        from core import saved_views

        if self.document is None:
            return
        self._remember_tab_view()
        height_px = max(1, self.viewport.view.height)
        aspect = self.viewport.view.width / height_px
        names = set(self._layout_names())
        for layout, (cx, cy, scale) in self._layout_cameras.items():
            if layout in names and scale > 0:
                try:
                    saved_views.store_view(self.document.doc, layout,
                                           (cx, cy, height_px / scale), aspect)
                except Exception:  # noqa: BLE001 - a view is never worth a failed save
                    pass

    def _register_commands(self) -> None:
        d = self.dispatcher
        d.register("ZOOM", self._cmd_zoom)
        d.register("PAN", self._cmd_pan)
        d.register("REGEN", self._cmd_regen)
        d.register("OPTIONS", self._cmd_options)
        d.register("APPLOAD", self._cmd_appload)
        d.register("SCRIPT", self._cmd_script)
        d.register("UNISOLATEOBJECTS", self._cmd_unisolate)
        d.register("QSELECT", self._cmd_qselect)
        d.register("FIND", self._cmd_find)
        d.register("GROUP", self._cmd_group)
        d.register("PICKSTYLE", self._cmd_pickstyle)
        d.register("VIEWRES", self._cmd_viewres)
        d.register("CURSORSIZE", self._cmd_cursorsize)
        d.register("PICKBOX", self._cmd_pickbox)
        d.register("DSETTINGS", lambda *a: self._drafting_settings(0))
        d.register("OSNAP", lambda *a: self._osnap_settings())
        for var in ("POLARANG", "POLARADDANG", "POLARMODE",
                    "GRIDUNIT", "SNAPUNIT", "GRIDMAJOR"):
            d.register(var, lambda *a, v=var: self._cmd_drafting_var(v, *a))
        for var in ("CENTEREXE", "CENTERLTYPE", "CENTERCROSSSIZE",
                    "CENTERCROSSGAP", "CENTERLAYER", "CENTERMARKEXE"):
            d.register(var, lambda *a, v=var: self._cmd_center_var(v, *a))
        d.register("PLUGINS", self._cmd_plugins)
        # Commands an AutoCAD user types and found unknown (a YouTuber's
        # drawing session): the sysvars, PROPERTIES and REDRAW
        for var in ("DIMASSOC", "CELTSCALE", "DIMSCALE", "LWDISPLAY",
                    "ZOOMFACTOR"):
            d.register(var, lambda *a, v=var: self._cmd_sysvar(v, *a))
        d.register("LWEIGHT", self._cmd_lweight)
        d.register("SETVAR", self._cmd_setvar)
        d.register("PROPERTIES", lambda *a: self.toggle_properties_panel())
        d.register("REDRAW", lambda *a: self.viewport.update())
        d.register("REDRAWALL", lambda *a: self.viewport.update())
        d.register("HELP", self._cmd_help)
        d.register("BEDIT", self._cmd_bedit)
        d.register("-BEDIT", self._cmd_bedit)
        d.register("BSAVE", self._cmd_bsave)
        d.register("BCLOSE", self._cmd_bclose)
        d.register("QUICKCALC", self._cmd_quickcalc)
        d.register("ADDSELECTED", lambda *a: self._invoke_command("ADDSELECTED"))
        d.register("U", self._cmd_undo)
        d.register("UNDO", self._cmd_undo_count)
        d.register("REDO", self._cmd_redo)
        d.register("OOPS", self._cmd_oops)
        d.register("OPEN", lambda *a: self._open_dialog())
        d.register("CLOSE", lambda *a: self.close_document())
        d.register("CLOSEALL", lambda *a: self.close_all_documents())
        d.register("SAVEAS", lambda *a: self._save_as_dialog())
        d.register("QUIT", lambda *a: self.close())
        d.register("EXIT", lambda *a: self.close())
        d.register("LAYER", lambda *a: self.toggle_layers_panel())
        d.register("STYLE", lambda *a: self.toggle_styles_panel())
        d.register("DIMSTYLE", lambda *a: self._open_dimstyle_manager())
        d.register("-LAYER", self._cmd_layer_cli)
        d.register("CLAYER", self._cmd_clayer)
        d.register("COPYCLIP", lambda *a: self._cmd_copy())
        d.register("CUTCLIP", lambda *a: self._cmd_cut())
        d.register("PASTECLIP", lambda *a: self._cmd_paste())
        d.register("PLOT", lambda *a: self._plot_dialog())
        d.register("PRINT", lambda *a: self._plot_dialog())
        d.register("PUBLISH", lambda *a: self._publish_dialog())
        d.register("DXFOUT", lambda *a: self._cmd_dxfout(*a))
        d.register("LAYOUT", self._cmd_layout)
        d.register("MSPACE", self._cmd_mspace)
        d.register("DRAWINGRECOVERY", self._cmd_drawing_recovery)
        d.register("SAVETIME", self._cmd_savetime)
        d.register("MIRRTEXT", self._cmd_mirrtext)
        d.register("REINIT", self._cmd_reinit)
        d.register("PSPACE", self._cmd_pspace)
        d.register("VPLOCK", self._cmd_vplock)
        d.register("PAGESETUP", self._cmd_pagesetup)
        d.register("MLEADERSTYLE", self._cmd_mleaderstyle)
        # Phase 4 drawing + Phase 5 editing tools.
        for name in ("LINE", "CIRCLE", "ARC", "COPYBASE", "PASTEBLOCK", "PLINE", "RECTANG", "POLYGON",
                     "SPLINE",
                     "ELLIPSE", "POINT", "TEXT", "MTEXT",
                     "ERASE", "MOVE", "COPY", "ROTATE", "SCALE", "MIRROR",
                     "OFFSET", "TRIM", "EXTEND", "FILLET",
                     "BLOCK", "INSERT", "EXPLODE", "HATCH", "-HATCH",
                     "DIMLINEAR", "DIMALIGNED", "DIMRADIUS", "DIMDIAMETER",
                     "DIMANGULAR", "DIMARC", "DIMORDINATE", "DIMCENTER",
                     "CENTERMARK", "CENTERLINE",
                     "DIMCONTINUE", "DIMBASELINE", "DIMTEDIT",
                     "DIM", "QDIM", "DIMBREAK", "DIMJOGGED", "DIMSPACE",
                     "MLEADER", "QLEADER", "LEADER",
                     "MVIEW", "XLINE", "RAY", "DIVIDE", "MEASURE",
                     "REVCLOUD",
                     "DIST", "ID", "AREA", "LIST",
                     "STRETCH", "BREAK", "JOIN",
                     "CHAMFER", "ARRAY", "MATCHPROP", "CHPROP", "PEDIT",
                     "DRAWORDER", "LAYISO", "LAYOFF", "LAYFRZ", "LAYLCK",
                     "LAYULK", "IMAGEATTACH",
                     "TABLE", "PDFATTACH", "IMAGEADJUST", "TRANSPARENCY",
                     "LENGTHEN", "ALIGN", "BOUNDARY", "-BOUNDARY", "DONUT",
                     "OBJECTSCALE", "-OBJECTSCALE",
                     "AIOBJECTSCALEADD", "AIOBJECTSCALEREMOVE",
                     "SCALETEXT", "XATTACH", "UCS"):
            d.register(name, lambda *a, n=name: self.tools.start_tool(n))
        d.register("ADJUST", lambda *a: self.tools.start_tool("IMAGEADJUST"))
        d.register("CANNOSCALE", self._cmd_cannoscale)
        d.register("ANNOAUTOSCALE", self._cmd_annoautoscale)
        d.register("ANNOALLVISIBLE", self._cmd_annoallvisible)
        # Block attributes (#35): ATTDEF, -ATTDEF, EATTEDIT, -ATTEDIT, ATTSYNC,
        # ATTDISP, ATTDIA, ATTREQ as tools; BATTMAN is a dialog.
        from tools.attributes import ATTRIBUTE_TOOL_CLASSES

        for name in ATTRIBUTE_TOOL_CLASSES:
            d.register(name, lambda *a, n=name: self.tools.start_tool(n))
        d.register("BATTMAN", lambda *a: self._cmd_battman())
        # external references (#33): the palette, its command-line twin
        d.register("XREF", lambda *a: self.toggle_xrefs_panel())
        d.register("EXTERNALREFERENCES", lambda *a: self.toggle_xrefs_panel())
        d.register("-XREF", self._cmd_xref_cli)
        d.register("CLEANSCREENON", lambda *a: self._clean_screen(True))
        d.register("CLEANSCREENOFF", lambda *a: self._clean_screen(False))
        d.register("LAYON", lambda *a: self._cmd_layon())
        d.register("LAYTHW", lambda *a: self._cmd_laythw())
        d.register("LAYUNISO", lambda *a: self._cmd_layuniso())
        d.register("SAVE", lambda *a: self.save_document())
        d.register("QSAVE", lambda *a: self.save_document())
        d.register("UNITS", lambda *a: self._units_dialog())
        d.register("DDUNITS", lambda *a: self._units_dialog())
        d.register("-UNITS", self._cmd_units_cli)
        d.register("LTSCALE", self._cmd_ltscale)
        # point style (#69): the dialog and its two system variables
        d.register("DDPTYPE", lambda *a: self._point_style_dialog())
        d.register("PTYPE", lambda *a: self._point_style_dialog())
        d.register("PDMODE", self._cmd_pdmode)
        d.register("PDSIZE", self._cmd_pdsize)
        # drawing cleanup (#37): PURGE has a dialog and a prompt flow; the
        # other two need the mouse and are tools
        d.register("PURGE", self._cmd_purge_dialog)
        d.register("-PURGE", self._cmd_purge_cli)
        for name in ("OVERKILL", "-OVERKILL", "WBLOCK", "-WBLOCK"):
            d.register(name, lambda *a, n=name: self.tools.start_tool(n))
        d.register("LINETYPE", self._cmd_linetype)
        d.register("MULTIPLE", self._cmd_multiple)
        d.register("-LINETYPE", self._cmd_linetype_cli)

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
        self.tools._mspace_exit_hinted = False
        from core import layouts as layout_ops

        placement = layout_ops.viewport_placement(vp)
        if placement is None:
            self.command_line.echo(
                tr("That viewport has no usable view — set its scale first "
                   "(Z + nXP), or fit it."))
            return
        self.tools.cancel()               # a sheet command cannot go on inside
        self.tools.viewport_crossed()     # entering MSPACE deselects (AutoCAD)
        self._active_vp = vp
        self.viewport.active_vp_rect = layout_ops.viewport_rect(vp)
        self.viewport.sync_cursor_shape()
        # Everything the mouse says is paper and everything the model
        # answers is model: the projection goes to the two layers that
        # cross it, the tool controller (points, readout) and the canvas
        # (matrices). No index or snap engine is built for the model: a
        # viewport navigates, it does not edit (ToolController.start_tool).
        self.viewport.space_placement = placement
        self.viewport.update()
        self._vp_warm_live_scene()
        label = layout_ops.scale_label(layout_ops.viewport_scale(vp))
        if layout_ops.is_viewport_locked(vp):
            self.command_line.echo(
                tr("Viewport active (scale {scale}, display LOCKED — "
                   "VPLOCK to unlock). PSPACE returns to paper.", scale=label))
        else:
            self.command_line.echo(
                tr("Viewport active (scale {scale}): wheel and pan move the "
                   "view, Z + nXP sets the exact scale (e.g. 1/100XP), VPLOCK "
                   "locks it. PSPACE returns to paper; edit in the Model tab.",
                   scale=label))
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
        self.refresh_space_placement()
        self._vp_live_regen()
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
        self.refresh_space_placement()
        self._vp_live_regen()
        return True

    def vp_zoom_window(self, x0: float, y0: float,
                       x1: float, y1: float) -> bool:
        """ZOOM Window while a viewport is active: it zooms THAT viewport.

        True when it was handled, so the canvas leaves its own view alone.
        """
        from core import layouts as layout_ops

        vp = self._active_vp
        if vp is None or not vp.is_alive:
            return False
        if layout_ops.is_viewport_locked(vp):
            self.command_line.echo(
                tr("Viewport is view-locked — VPLOCK to unlock."))
            return True
        command = layout_ops.zoom_window_command(vp, x0, y0, x1, y1)
        if command is None:
            return False
        self._vp_gesture_commit()      # settle any wheel burst first
        self.history.execute(command)
        self.refresh_space_placement()
        self._vp_view_changed_by_command()
        return True

    def cycle_active_viewport(self) -> None:
        """Ctrl+R: make the next viewport of the layout current (AutoCAD)."""
        from core import layouts as layout_ops

        if self.document is None or self._active_layout == "Model":
            return
        layout = self.document.doc.layouts.get(self._active_layout)
        viewports = layout_ops.visible_viewports(layout)
        if not viewports:
            return
        current = self._active_vp
        if current is None or current not in viewports:
            self._activate_viewport(viewports[-1])
            return
        nxt = viewports[(viewports.index(current) + 1) % len(viewports)]
        self._activate_viewport(nxt)

    def _vp_live_regen(self) -> None:
        """A pan/zoom tick inside an active viewport.

        The sheet scene has the model content baked in, so the obvious way to
        show the move is to rebuild it — and that is what this used to do,
        207 ms a tick on a plan of 200 entities. The display trailed the
        cursor by a regen or two, and a real drawing would be worse.

        Nothing about the content changes when you pan inside a viewport,
        though: only where it is put. So the model is tessellated once, its
        baked copy in the sheet is hidden, and each tick sets a matrix — the
        very trick the drag ghost uses. The exact sheet comes back with one
        regen when the gesture settles.
        """
        if self._vp_live_draw():
            return
        worker = getattr(self, "_vp_live_worker", None)
        if worker is not None and worker.isRunning():
            # the live scene is on its way (a second or two): the display
            # catches up when it lands, and the gesture's commit regens
            # once -- not a full sheet regen per mouse move meanwhile
            return
        # No model scene yet (still building, or the drawing changed under
        # it): fall back to the old rebuild so the view still tracks.
        import time

        known = self._regen_ms.get(self._active_layout)
        if (known is None or known > self._VP_LIVE_BUDGET_MS
                or self._regen_worker is not None):
            self.regen_in_memory()
            return
        from render.backend import build_scene

        t0 = time.perf_counter()
        try:
            scene = build_scene(self.document, self._active_layout)
        except Exception:
            self.regen_in_memory()
            return
        # Keep the measurement fresh: a sheet that grows past the budget
        # switches back to the threaded path on the next tick.
        self._regen_ms[self._active_layout] = (time.perf_counter() - t0) * 1000.0
        self.viewport.set_scene(scene)
        self.tools.mark_scene_merged()

    def refresh_space_placement(self) -> None:
        """The active viewport's view moved: the canvas needs the new
        projection or the overlay would draw where the model USED to be.

        Called from every path that can change what a viewport shows -- the
        wheel, the pan, ZOOM nXP, fit, and undo of any of them.
        """
        from core import layouts as layout_ops

        vp = self._active_vp
        if vp is None or not vp.is_alive:
            self.viewport.space_placement = None
            return
        self.viewport.space_placement = layout_ops.viewport_placement(vp)

    def apply_layer_visibility(self, layer_name: str, visible: bool) -> bool:
        """Show or hide a layer's geometry without rebuilding the scene.

        AutoCAD turns a layer off instantly; we used to retessellate the
        whole drawing, which on a real plan of 88 000 entities was 7.7 s
        before the change appeared. The vertices are already on the GPU, so
        zeroing their alpha (the same surgical display the eraser uses) is
        all it takes.

        Returns True when the display is now correct on its own. False means
        "regenerate too": either the layer also lives inside a block, where
        the vertices belong to the INSERT and not to the entity, or the
        scene has been rebuilt since it was hidden and no longer carries
        them.
        """
        from core import layers as layer_ops

        document = self.document
        if document is None or self.viewport._scene is None:
            return False
        handles = [e.dxf.handle for e in self._drawn_entities_of_layer(layer_name)
                   if e.dxf.get("handle", None)]
        if not handles:
            return False        # nothing of it is drawn: let the regen decide
        if visible:
            if not self.viewport.unhide_handles(handles):
                return False    # rebuilt without them: only a regen can help
        else:
            self.viewport.hide_handles(handles)
        self.viewport.update()
        return layer_name not in layer_ops.layers_inside_blocks(document)

    def _drawn_entities_of_layer(self, layer_name: str) -> list:
        """The entities of that layer the current scene actually draws."""
        document = self.document
        scene = self.viewport._scene
        if document is None or scene is None:
            return []
        ranges = getattr(scene, "handle_ranges", None)
        if not ranges:
            return []
        db = document.doc.entitydb
        found = []
        for handle in ranges:
            entity = db.get(handle)
            if (entity is not None and entity.is_alive
                    and entity.dxf.get("layer", None) == layer_name):
                found.append(entity)
        return found

    def apply_layer_appearance(self, layer_name: str) -> bool:
        """A layer's colour / linetype / lineweight changed: redraw IT.

        Its geometry is the same, only its look, so the drawing does not
        need rebuilding -- the layer's own entities are re-tessellated and
        swapped in over the hidden originals. Returns False when the layer
        also lives inside a block (that geometry belongs to the INSERT) or
        when nothing of it is on screen, and the caller regenerates.
        """
        from core import layers as layer_ops

        document = self.document
        if document is None:
            return False
        if layer_name in layer_ops.layers_inside_blocks(document):
            return False
        entities = self._drawn_entities_of_layer(layer_name)
        if not entities:
            return False
        return self.tools.redraw_entities(entities)

    def invalidate_vp_model_cache(self) -> None:
        """The model changed: the tessellation kept for live viewport
        navigation is stale. Called from the edit path, NOT from the document
        revision — moving a viewport's view marks the document dirty on every
        wheel tick, and keying on that rebuilt 160 ms of model per tick,
        which is the whole cost this cache exists to avoid."""
        self._vp_model_cache = None
        if getattr(self, "_active_vp", None) is not None:
            # an undo inside a viewport: rebuild the live model now, in the
            # background, so the next pan finds it (or waits, never freezes)
            self._vp_warm_live_scene()

    def _vp_live_key(self):
        """What the live model scene depends on: the document and the
        units of the sheet it is drawn through -- NOT the sheet itself.
        Every sheet is white paper, so the model tessellates the same for
        all of them; keyed per layout, each tab switch rebuilt the whole
        model (2.3 s on Planos Constructivos, with the GUI mute for 0.5 s
        when it landed), for identical vertices."""
        units = 0
        try:
            sheet = self.document.doc.layouts.get(self._active_layout)
            units = int(getattr(sheet, "units", 0) or 0)
        except Exception:      # noqa: BLE001 - the Model tab, or a gone sheet
            pass
        return (self.document, units)

    def _vp_model_scene(self):
        """The model, tessellated once for live viewport navigation --
        with its colours resolved against the SHEET it will be drawn on,
        like the bake it stands in for (ACI 7 black on paper, not the
        model canvas's white)."""
        cached = getattr(self, "_vp_model_cache", None)
        key = self._vp_live_key()
        if cached is not None and cached[0] == key:
            return cached[1]
        worker = getattr(self, "_vp_live_worker", None)
        if worker is not None and worker.isRunning():
            return None                   # being built: this tick waits
        from render.backend import build_scene

        try:
            sheet = self.document.doc.layouts.get(self._active_layout)
            scene = build_scene(self.document, "Model", canvas=sheet)
        except Exception:
            return None
        self._vp_model_cache = (key, scene)
        return scene

    def _vp_model_scene_ready(self):
        """The live model scene if it is cached -- never built here: a pan
        tick after an edit rebuilt it on the GUI thread, 2.4 s frozen on a
        real sheet (Marco: "editar desde la lámina no está bien"). Missing,
        the build starts in the background and this tick draws nothing;
        the display catches up when it lands."""
        cached = getattr(self, "_vp_model_cache", None)
        if cached is not None and cached[0] == self._vp_live_key():
            return cached[1]
        self._vp_warm_live_scene()
        return None

    def _vp_warm_live_scene(self) -> None:
        """Start building the live model scene in the background, unless
        it is cached or already being built."""
        if self.document is None or self._active_layout == "Model":
            return
        key = self._vp_live_key()
        cached = getattr(self, "_vp_model_cache", None)
        if cached is not None and cached[0] == key:
            return
        worker = getattr(self, "_vp_live_worker", None)
        if worker is not None and worker.isRunning():
            return
        worker = _LiveSceneWorker(self.document, self._active_layout, key)
        worker.done.connect(self._on_live_scene_done)
        self._vp_live_worker = worker
        gc_guard.start(worker)

    def _on_live_scene_done(self, key, scene) -> None:
        if scene is None or self.document is None or key != self._vp_live_key():
            return
        if getattr(self, "_vp_model_cache", None) is None:
            self._vp_model_cache = (key, scene)
        # a drag already under way: catch the display up to the cursor
        if self._vp_gesture is not None and self._active_vp is not None:
            if self._vp_live_draw():
                self.viewport.update()

    def _vp_placement(self, vp):
        """Where this viewport puts the model, or None if a matrix cannot say.

        A viewport with its own frozen layers is not the model as it is,
        and a shaped clipping boundary is not a rectangle: those keep the
        baked path, which renders them properly. A twisted view is a turn
        the matrix makes (Planos Constructivos' A-01 has one at 60°, and
        one viewport that cannot go live keeps the whole sheet on the bake:
        every pan tick inside any of them re-baked the sheet).
        """
        from core import layouts as layout_ops

        try:
            if getattr(vp, "frozen_layers", None):
                return None
            clip = layout_ops.viewport_clip(vp)
            if clip is False:
                return None          # a shaped boundary: only the bake clips it
        except Exception:
            return None
        # The live model is tessellated once, at model space's annotation
        # scale: a viewport showing annotations at another scale needs its
        # own representations, which only the baked path draws.
        if self._model_annotative():
            from core import annotative

            doc = self.document.doc
            shown = annotative.viewport_scale(vp)
            if shown is not None and shown != annotative.current_scale(doc):
                return None
        # past those, the placement IS the projection MSPACE edits through
        placement = layout_ops.viewport_placement(vp)
        if placement is not None and clip is not None:
            # a rectangular boundary: scissor to it, within the frame
            x0, y0, x1, y1 = placement["rect"]
            placement["rect"] = (max(x0, clip[0]), max(y0, clip[1]),
                                 min(x1, clip[2]), min(y1, clip[3]))
        return placement

    def _model_annotative(self) -> bool:
        """Does model space hold any annotative object? Cached per revision:
        the live path asks on every gesture."""
        from core import annotative

        key = (id(self.document), self.document.revision)
        cached = getattr(self, "_annotative_cache", None)
        if cached is None or cached[0] != key:
            cached = (key, annotative.has_annotative(
                self.document.doc.modelspace()))
            self._annotative_cache = cached
        return cached[1]

    def _vp_live_draw(self) -> bool:
        """Show EVERY viewport's content live, at its current view.

        Not just the active one: the sheet's baked content is one pool shared
        by all of them (they draw the same model entities), so hiding it for
        the viewport being navigated hides it for the rest too — which blanked
        the other viewports the moment a pan started.
        """
        from core.layouts import visible_viewports

        vp = self._active_vp
        if vp is None or not vp.is_alive or self.document is None:
            return False
        # The placements first, the tessellation second: a sheet with one
        # clipped or twisted viewport cannot go live at all, and paying the
        # model build (5.3 s on a real plan, synchronous) to find that out
        # froze the first pan tick of every gesture on such a sheet.
        layout = self.document.doc.layouts.get(self._active_layout)
        placements = []
        for other in visible_viewports(layout):
            placement = self._vp_placement(other)
            if placement is None:
                return False        # one of them needs the bake: all do
            placements.append(placement)
        if not placements:
            return False
        scene = self._vp_model_scene_ready()
        if scene is None:
            return False
        for placement in placements:
            placement["scene"] = scene
        self._vp_hide_baked_content()
        self.viewport.set_live_viewport(placements)
        return True

    def _vp_hide_baked_content(self) -> None:
        """Hide the sheet's own copy of the model content, once per gesture.

        Without this the old position stays on screen under the live one.
        The handles are the model entities': that is who owns those vertices
        in a sheet scene, the viewport only owns its border.
        """
        if getattr(self, "_vp_content_hidden", False):
            return
        scene = self.viewport._scene
        if scene is None:
            return
        model = {e.dxf.handle for e in self.document.doc.modelspace()}
        hidden = [h for h in scene.handle_ranges if h in model]
        self.viewport.hide_handles(hidden)
        self._vp_content_hidden = True
        self._vp_hidden_handles = hidden

    def _vp_live_stop(self) -> None:
        """Leave live mode: the sheet scene on screen carries the content.

        Only right when it does. The baked copy of the model was hidden for
        the gesture, so this runs when the fresh sheet has landed
        (_on_regen_done) or when the view did not change and the copy has
        been un-hidden -- never in between, or the viewport goes blank
        until something else happens to regenerate. That blank is what a
        tester reported as "al panear dentro de una ventana desaparece el
        dibujo": the commit dropped the live matrix and asked nobody for
        the regen its comment promised.
        """
        self._vp_content_hidden = False
        self._vp_hidden_handles = []
        self.viewport.set_live_viewport(None)

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
        live = self.viewport._live_vp is not None
        if now_center == old_center and now_height == old_height:
            # Nothing moved: the sheet on screen is still exact, its hidden
            # copy of the model just has to come back -- surgically, no
            # regen, and no gap.
            if live:
                hidden = getattr(self, "_vp_hidden_handles", [])
                restored = self.viewport.unhide_handles(hidden)
                self._vp_live_stop()
                if restored < len(hidden):
                    self.regen_in_memory()   # scene rebuilt meanwhile
            return
        # do() re-applies the values already live — recording, not changing.
        self.history.execute(layout_ops.SetViewportViewCommand(
            vp, view_center=now_center, view_height=now_height,
            name=tr("Viewport view"),
            old_center=old_center, old_height=old_height))
        self._vp_sheet_moved()

    def _vp_sheet_moved(self) -> None:
        """The active viewport's view changed and the sheet's bake shows
        the old one. While the live matrix is up it already shows the new
        view exactly, so the re-bake waits until the viewport is left (or
        an edit regenerates anyway): re-baking the whole sheet after every
        wheel burst was a full parallel regen per pause -- 12 in a minute
        of zooming on a real sheet -- and the lag Marco felt. Without the
        live matrix (a shaped clip, a twist) the bake is the only picture,
        so it is rebuilt now; it lands with the live matrix still up, and
        _on_regen_done retires that -- dropping it first would leave the
        viewport empty for as long as the regen takes."""
        if self.viewport._live_vp is not None:
            self._vp_sheet_stale = True
        else:
            self.regen_in_memory()

    def _deactivate_viewport(self, echo: bool = False) -> None:
        self._vp_gesture_commit()       # leaving MSPACE settles the gesture
        had = getattr(self, "_active_vp", None) is not None
        self._active_vp = None
        if getattr(self, "_vp_sheet_stale", False):
            # the bake still shows the view before the navigation: rebuild
            # it now; the live matrix keeps the picture up until it lands
            self._vp_sheet_stale = False
            self.regen_in_memory()
        self.viewport.space_placement = None
        if had:
            self.tools.viewport_crossed()   # back to the sheet's own entities
        if getattr(self.viewport, "active_vp_rect", None) is not None:
            self.viewport.active_vp_rect = None
            self.viewport.sync_cursor_shape()     # the crosshair, sheet-wide
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

        if self.document is None:
            return
        # An object's own double-click action comes first, in either space
        # (DBLCLKEDIT, p. 2207): "Double-click a multiline text object" is
        # how MTEDIT is reached, and a title block's text is a paper-space
        # object like any other. Only when the double-click lands on no
        # object does the layout's enter/leave rule apply.
        #
        # Inside MSPACE that pick goes through the projection, so it is only
        # asked for a point the active viewport shows: on the bare paper it
        # would reach a model object the viewport does not display -- a
        # text out there opened its editor instead of leaving the viewport,
        # which is what a tester met as "me costó salir de la ventana".
        entity = None
        if self._active_vp is None:
            entity = self.tools.pick_entity((wx, wy))
        if entity is not None and entity.dxftype() != "VIEWPORT":
            # A block reference with attributes opens the Enhanced Attribute
            # Editor (EATTEDIT, p. 715) -- before any text rule, because the
            # pick lands on the reference, never on one of its attributes.
            if self.tools.edit_attributes(entity):
                return
            if self.tools.open_text_editor_for(entity):
                return
            # A hatch's double-click action is HATCHEDIT, the same rule that
            # sends a double-clicked MTEXT to MTEDIT (DBLCLKEDIT, p. 2207).
            if entity.dxftype() == "HATCH" and self.tools.edit_hatch(entity):
                return
        if self._active_layout == "Model":
            return
        layout = self.document.doc.layouts.get(self._active_layout)
        vp = layout_ops.viewport_hit(layout, wx, wy)
        if vp is not None:
            self._activate_viewport(vp)
        else:
            self._deactivate_viewport(echo=True)

    def _cmd_battman(self) -> None:
        """BATTMAN (p. 203): the Block Attribute Manager."""
        from views.battman_dialog import open_battman

        if self.document is None:
            return
        open_battman(self)

    def _cmd_pagesetup(self, *args) -> None:
        """PAGESETUP: paper/orientation/margins of the current layout tab."""
        from core import layouts as layout_ops
        from views.page_setup_dialog import PageSetupDialog

        if self.document is None:
            self.new_document()
        name = self._active_layout
        # the Model tab has its page setup too: what PLOT starts from there
        # (Rafael's review 6 tried it first and was sent to a layout)
        layout = (self.document.doc.modelspace() if name == "Model"
                  else self.document.doc.layouts.get(name))
        dialog = PageSetupDialog(self, layout)
        accepted = dialog.exec()
        values = dialog.values() if accepted else None
        dialog.deleteLater()           # a child of the window: free it
        if not accepted:
            return
        width, height = values.pop("width"), values.pop("height")
        self.history.execute(layout_ops.page_setup_command(
            layout, width, height, values.pop("margins"),
            values.pop("size_name"), **values))
        if name != "Model":
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

    def _cmd_clayer(self, *args) -> Prompt | None:
        """CLAYER — the current layer, typed by name (#24)."""
        if self.document is None:
            self.new_document()
        from core import layers as layer_ops

        def refresh() -> None:
            if self._layers_panel is not None:
                self._layers_panel.refresh()
            self._refresh_props_toolbar()
            self.regen_in_memory()
            self.viewport.update()

        return layer_ops.clayer_command(
            self.document, self.history, echo=self.command_line.echo,
            refresh=refresh, args=args)

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

    # -- PURGE (#37) -----------------------------------------------------------
    def _after_purge(self) -> None:
        """Tables changed under the panels: every list that shows one."""
        self.tools._invalidate_geometry()
        if self._layers_panel is not None:
            self._layers_panel.refresh()
        if getattr(self, "_styles_panel", None) is not None:
            self._styles_panel.refresh()
        self._refresh_props_toolbar()
        self.regen_in_memory()
        self.viewport.update()

    def _cmd_purge_cli(self, *args) -> Prompt | None:
        """-PURGE: AutoCAD's prompt flow, one level of reference per run."""
        if self.document is None:
            self.new_document()
        from core import cleanup

        return cleanup.purge_command(
            self.document, self.history, echo=self.command_line.echo,
            refresh=self._after_purge, args=args)

    def apply_purge(self, items: dict) -> int:
        """Purge these items as ONE undoable step; how many went."""
        from core import cleanup

        command = cleanup.PurgeCommand(items)
        if command.count == 0:
            self.command_line.echo(tr("No unreferenced named objects found."))
            return 0
        self.history.execute(command)
        self._after_purge()
        self.command_line.echo(tr("{count} item(s) purged.", count=command.count))
        return command.count

    def _cmd_purge_dialog(self, *args) -> None:
        if self.document is None:
            self.new_document()
        from views.purge_dialog import PurgeDialog

        dialog = PurgeDialog(self, self.document)
        if dialog.exec() and dialog.result_items is not None:
            self.apply_purge(dialog.result_items)

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

    def _point_style_dialog(self) -> None:
        """DDPTYPE: Format > Point Style... (#69)."""
        from core import points
        from views.point_style_dialog import PointStyleDialog

        if self.document is None:
            self.new_document()
        dialog = PointStyleDialog(self, self.document.doc)
        if not dialog.exec():
            return
        mode, size = dialog.values()
        self.history.execute(points.set_point_style_command(mode, size))
        self.regen_in_memory()

    def _cmd_pdmode(self, *args):
        from core import points

        if self.document is None:
            self.new_document()
        return points.pdmode_command(
            self.document, self.history.execute, self.command_line.echo,
            self.regen_in_memory, args=args)

    def _cmd_pdsize(self, *args):
        from core import points

        if self.document is None:
            self.new_document()
        return points.pdsize_command(
            self.document, self.history.execute, self.command_line.echo,
            self.regen_in_memory, args=args)

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

    def _cmd_multiple(self, *args) -> Prompt | None:
        """MULTIPLE: repeat the next command until Esc (AutoCAD's prefix,
        e.g. MULTIPLE DIMRADIUS to dimension radius after radius)."""
        def on_name(text: str):
            text = text.strip()
            if not text:
                return None
            name = self.dispatcher.resolve_name(text.split()[0])
            self.tools.repeat_name = name
            self.dispatcher.submit(name)
            if self.tools.tool is None:
                # not a command that stays running (a dialog, a prompt
                # flow): it ran once
                self.tools.repeat_name = None
            return None

        if args:
            return on_name(" ".join(args))
        return Prompt(tr("Enter command name to repeat:"), on_name)

    def _cmd_linetype(self, *args) -> None:
        """LINETYPE (Format > Linetype, LT): the Linetype Manager."""
        if self.document is None:
            self.new_document()
        from views.linetype_dialog import LinetypeManagerDialog

        dialog = LinetypeManagerDialog(self, self.document, self.tools._execute)
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()
        self._props_combo_key = None          # loaded/renamed linetypes
        self._refresh_props_toolbar()
        self._sync_panels()

    def _cmd_linetype_cli(self, *args) -> Prompt | None:
        """-LINETYPE: AutoCAD's prompt flow (?/Create/Load/Set)."""
        if self.document is None:
            self.new_document()
        from core import linetypes as lt_ops

        def pick_file(caption: str, save: bool) -> str:
            standard = lt_ops.standard_lin_file(self.document)
            name_filter = tr("Linetype files (*.lin)")
            if save:
                path, _selected = file_dialogs.get_save_file(
                    self, caption, "custom.lin", name_filter)
                return path
            return file_dialogs.get_open_file(self, caption, name_filter,
                                              select_file=standard)

        def execute(command) -> None:
            self.tools._execute(command)
            self._props_combo_key = None
            self._refresh_props_toolbar()

        return lt_ops.linetype_command(
            self.document, execute, echo=self.command_line.echo,
            pick_file=pick_file, args=args)

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
    def _cmd_mleaderstyle(self, *args) -> None:
        """MLEADERSTYLE: no manager yet -- say which style MLEADER uses."""
        from core import leaders

        if self.document is None:
            return
        name = leaders.mleader_style_name(self.document.doc)
        self.command_line.echo(
            tr("MLEADER uses the multileader style \"{name}\"; the style "
               "manager is not available yet.", name=name))

    def _cmd_zoom(self, *args) -> Prompt | None:
        if args:
            return self._zoom_option(args[0])
        if getattr(self, "_active_vp", None) is not None:
            return Prompt(tr("ZOOM [Extents/Window/Previous] or scale nXP:"),
                          self._zoom_option)
        return Prompt(tr("ZOOM [Extents/Window/Previous] <Extents>:"),
                      self._zoom_option)

    def _vp_view_changed_by_command(self) -> None:
        """A command moved the active viewport's view (ZOOM E, nXP, W):
        show the new view NOW through the live matrix, as a pan tick does,
        and let the sheet's regen land behind it. Waiting for the regen
        alone showed the fit 5.7 s later on a real sheet (Marco)."""
        self.refresh_space_placement()
        self._vp_live_draw()
        self._vp_sheet_moved()

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
            self._vp_view_changed_by_command()
            return
        # Both ZOOM prompts offer the same options, so either source resolves
        # "Ventana" and "_W" to the W the branches below expect.
        opt = (i18n.keywords.match(option, "ZOOM [Extents/Window/Previous] "
                                           "<Extents>:")
               or option.strip().upper() or "E")
        if opt in ("E", "EXTENTS"):
            if active_vp is not None:
                # inside a viewport, Extents fits the MODEL in it
                self.history.execute(
                    layout_ops.viewport_fit_command(self.document, active_vp))
                self._vp_view_changed_by_command()
                return
            self.viewport.zoom_extents()
        elif opt in ("W", "WINDOW"):
            if self.tools.tool is None and active_vp is None:
                # two corners at the prompt, with object snaps, in the Model
                # tab and on a sheet (#80)
                self.tools.start_tool("ZOOMWINDOW")
            else:
                # transparent 'ZOOM inside a command keeps that command's
                # prompt; inside a viewport there are no model snaps on
                # purpose (MSPACE is for navigating): a drag, as before
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

    def toggle_clean_screen(self) -> None:
        """Ctrl+0 / CLEANSCREENON / CLEANSCREENOFF.

        AutoCAD's rule (Command Reference p. 331): clears toolbars and
        dockable windows EXCLUDING the command window; the menu bar, the
        layout tabs and the status bar stay. Toggling back restores each
        bar to the visibility it had — one the user had already hidden
        stays hidden.
        """
        from PySide6.QtWidgets import QDockWidget, QToolBar

        saved = getattr(self, "_clean_screen_saved", None)
        if saved is None:
            bars = [w for w in (
                        list(self.findChildren(
                            QToolBar, options=Qt.FindDirectChildrenOnly))
                        + list(self.findChildren(
                            QDockWidget, options=Qt.FindDirectChildrenOnly)))
                    if w is not self._command_dock]
            self._clean_screen_saved = [(w, w.isVisible()) for w in bars]
            for w in bars:
                w.hide()
            self.command_line.echo(tr("Clean screen ON (Ctrl+0 restores)."))
            self._place_sidebar_handle()
        else:
            self._clean_screen_saved = None
            for w, visible in saved:
                w.setVisible(visible)
            self.command_line.echo(tr("Clean screen off."))
            self._place_sidebar_handle()

    def _clean_screen(self, on: bool) -> None:
        """CLEANSCREENON / CLEANSCREENOFF force a state; Ctrl+0 toggles."""
        active = getattr(self, "_clean_screen_saved", None) is not None
        if on != active:
            self.toggle_clean_screen()

    def _cmd_layon(self) -> None:
        """LAYON: turn on every layer, one undo step."""
        from core.commands import CompositeCommand
        from core.layers import LayerPropertyCommand

        if self.document is None:
            return
        commands = [LayerPropertyCommand(layer.dxf.name, "on", True)
                    for layer in self.document.doc.layers
                    if not layer.is_on()]
        if not commands:
            self.command_line.echo(tr("All layers are already on."))
            return
        self.history.execute(CompositeCommand(tr("all layers on"), commands))
        self.command_line.echo(tr("All layers have been turned on."))
        self.regen_in_memory()

    def _cmd_laythw(self) -> None:
        """LAYTHW: thaw every layer, one undo step (p. 1019)."""
        from core.commands import CompositeCommand
        from core.layers import LayerPropertyCommand

        if self.document is None:
            return
        commands = [LayerPropertyCommand(layer.dxf.name, "frozen", False)
                    for layer in self.document.doc.layers
                    if layer.is_frozen()]
        if not commands:
            self.command_line.echo(tr("No layers are frozen."))
            return
        self.history.execute(CompositeCommand(tr("thaw all layers"), commands))
        self.command_line.echo(tr("All layers have been thawed."))
        self.regen_in_memory()

    def _cmd_layuniso(self) -> None:
        """LAYUNISO: restore the state LAYISO saved (session-scoped)."""
        from core.commands import CompositeCommand
        from core.layers import LayerPropertyCommand

        if self.document is None:
            return
        prev = getattr(self.document, "_layiso_prev", None)
        if not prev:
            self.command_line.echo(
                tr("No LAYISO state to restore in this session."))
            return
        commands = []
        for layer in self.document.doc.layers:
            name = layer.dxf.name
            if name in prev and layer.is_on() != prev[name]:
                commands.append(LayerPropertyCommand(name, "on", prev[name]))
        self.document._layiso_prev = None
        if commands:
            self.history.execute(
                CompositeCommand(tr("unisolate layers"), commands))
        self.command_line.echo(
            tr("Layers isolated by LAYISO have been restored."))
        self.regen_in_memory()

    # -- Block Editor (BEDIT / BSAVE / BCLOSE, reference pp. 215-273) ----------
    def _cmd_bedit(self, *args) -> None:
        """Open a block definition in the Block Editor.

        The three access methods the reference documents: a name typed with
        the command (the -BEDIT path), a selected block reference (the
        shortcut-menu path), or the pick-a-block dialog. A new name creates
        a new definition, exactly like the Edit Block Definition dialog.
        """
        from core import blockedit

        if self.document is None:
            return
        if self._block_session is not None:
            self.command_line.echo(
                tr("Already editing block \"{name}\" — BSAVE saves it, "
                   "BCLOSE leaves the editor.", name=self._block_session.name))
            return
        name = " ".join(str(a) for a in args).strip() if args else ""
        if name == "?":
            names = blockedit.editable_blocks(self.document)
            self.command_line.echo(
                tr("Blocks: {names}", names=", ".join(names))
                if names else tr("No blocks defined."))
            return
        if not name:
            # noun-verb: one selected reference edits its own definition
            picked = [e for h in self.tools.selection
                      if (e := self.tools.index.entity(h)) is not None
                      and e.is_alive and e.dxftype() == "INSERT"]
            if len(picked) == 1:
                name = picked[0].dxf.name
        if not name:
            from PySide6.QtWidgets import QInputDialog

            names = blockedit.editable_blocks(self.document)
            name, ok = QInputDialog.getItem(
                self, tr("Block Editor"),
                tr("Block to create or edit:"), names, 0, True)
            if not ok or not name.strip():
                return
            name = name.strip()
        self._bedit_return_tab = None
        if self._active_layout != "Model":
            # AutoCAD opens the editor from a layout too; our editor renders
            # through the Model path, so land there first -- and come back
            # to the sheet when the editor closes, which is where the user
            # was working.
            self._bedit_return_tab = self._active_layout
            self.switch_layout("Model")
        try:
            self._block_session = blockedit.BlockEditSession.begin(
                self.document, self.history, name)
        except ValueError as exc:
            self.command_line.echo(str(exc))
            return
        self.tools.cancel()
        self.tools.selection = set()
        self.viewport.push_view()
        self.tools._invalidate_geometry()
        self.invalidate_vp_model_cache()
        self.regen_in_memory(zoom_after=True)
        self.setWindowTitle(
            f"IngeCAD — {self.document.name} — "
            + tr("Block Editor: {name}", name=name))
        self._blockedit_label.setText(tr("Block: {name}", name=name))
        self._blockedit_toolbar.setVisible(True)
        self.command_line.echo(
            tr("Editing block \"{name}\". BSAVE saves the definition, "
               "BCLOSE closes the editor.", name=name))

    def _cmd_bsave(self, *args) -> None:
        session = self._block_session
        if session is None:
            self.command_line.echo(
                tr("BSAVE only works inside the Block Editor."))
            return
        session.save()
        self.command_line.echo(
            tr("Block \"{name}\" saved.", name=session.name))

    def _cmd_bclose(self, *args) -> None:
        session = self._block_session
        if session is None:
            self.command_line.echo(
                tr("BCLOSE only works inside the Block Editor."))
            return
        save = True
        if session.dirty:
            # The reference: "you are prompted to save or discard the
            # changes" (BCLOSE, p. 215). Same three-way dialog here.
            from PySide6.QtWidgets import QMessageBox

            box = QMessageBox(self)
            box.setWindowTitle(tr("Block Editor"))
            box.setText(tr("Save the changes to block \"{name}\"?",
                           name=session.name))
            box.setStandardButtons(QMessageBox.Save | QMessageBox.Discard
                                   | QMessageBox.Cancel)
            box.setDefaultButton(QMessageBox.Save)
            answer = box.exec()
            if answer == QMessageBox.Cancel:
                return
            save = answer == QMessageBox.Save
        self._end_block_session(save)

    def _end_block_session(self, save: bool) -> None:
        session, self._block_session = self._block_session, None
        self._blockedit_toolbar.setVisible(False)
        name = session.name
        session.close(save)
        self.tools.cancel()
        self.tools.selection = set()
        self.tools._invalidate_geometry()
        self.invalidate_vp_model_cache()
        self.regen_in_memory()
        if not self.viewport.zoom_previous():
            self.viewport.zoom_extents()
        self.setWindowTitle(f"IngeCAD — {self.document.name}")
        self.command_line.echo(
            tr("Block \"{name}\" saved — every insert shows the change.",
               name=name)
            if save else
            tr("Changes to block \"{name}\" discarded.", name=name))
        back, self._bedit_return_tab = getattr(
            self, "_bedit_return_tab", None), None
        if back is not None and back in self._layout_names():
            self.switch_layout(back)

    def _cmd_undo_count(self, *args) -> Prompt | None:
        """UNDO asks how many operations, <1> by default (UNDO, Command
        Reference); it undid one at once and the number typed next ran as
        an unknown command. U stays the one-step undo."""
        def commit(text: str):
            text = text.strip()
            if not text:
                count = 1
            else:
                try:
                    count = int(text)
                except ValueError:
                    self.command_line.echo(tr("Requires an integer."))
                    return ask()
                if count < 1:
                    self.command_line.echo(tr("Value must be positive."))
                    return ask()
            for _ in range(count):
                if not self.history.can_undo:
                    break
                self._cmd_undo()
            return None

        def ask():
            return Prompt(
                tr("Enter the number of operations to undo <1>:"), commit)

        if args:
            return commit(str(args[0]))
        return ask()

    def _cmd_undo(self, *args) -> None:
        session = self._block_session
        if session is not None and session.undo_blocked():
            self.command_line.echo(
                tr("Nothing to undo inside the Block Editor."))
            return
        command = self.history.undo()
        self.command_line.echo(
            tr("Undo: {name}", name=command.name) if command else tr("Nothing to undo"))
        if command is not None:
            self.tools.after_history_change(command)
            self._sync_layout_tabs()
            # an undo is a change like any click: the layer control, the
            # Layers tab and the Properties tab hear it the same way
            self.tools.changed.emit()

    def _cmd_oops(self, *args) -> None:
        """OOPS: restore what the last ERASE erased, even after other
        commands (it was an unknown command)."""
        from core.actions import EraseCommand, OopsCommand

        erase = next((c for c in reversed(self.history._undo)
                      if isinstance(c, EraseCommand)), None)
        command = OopsCommand(erase) if erase is not None else None
        if command is None or not command.entities:
            self.command_line.echo(tr("Nothing to restore."))
            return
        self.tools._execute(command)
        self.command_line.echo(
            tr("{count} restored.", count=len(command.entities)))

    def _cmd_redo(self, *args) -> None:
        command = self.history.redo()
        self.command_line.echo(
            tr("Redo: {name}", name=command.name) if command else tr("Nothing to redo"))
        if command is not None:
            self.tools.after_history_change(command)
            self._sync_layout_tabs()
            self.tools.changed.emit()

    def _build_blockedit_toolbar(self) -> None:
        """The classic Block Editor toolbar, shown only during a session.

        The reference is explicit for the pre-ribbon interface: when the
        editor opens, "the Block Editor toolbar is displayed" (p. 223). It
        exists so nobody has to already know that BSAVE saves and BCLOSE
        leaves -- which is exactly how the gap surfaced: Marco edited his
        first block and had no visible way out.
        """
        from PySide6.QtWidgets import QLabel, QToolBar

        bar = QToolBar(tr("Block Editor"), self)
        bar.setObjectName("blockedit_toolbar")
        bar.setMovable(True)
        self._blockedit_label = QLabel("", bar)
        self._blockedit_label.setStyleSheet(
            "padding: 0 8px; font-weight: bold;")
        bar.addWidget(self._blockedit_label)
        save = QAction(tr("Save Block (BSAVE)"), self)
        save.triggered.connect(lambda: self._invoke_command("BSAVE"))
        bar.addAction(save)
        close = QAction(tr("Close Block Editor (BCLOSE)"), self)
        close.triggered.connect(lambda: self._invoke_command("BCLOSE"))
        bar.addAction(close)
        bar.setVisible(False)
        self.addToolBarBreak(Qt.TopToolBarArea)
        self.addToolBar(Qt.TopToolBarArea, bar)
        self._blockedit_toolbar = bar

    def _build_status_bar(self) -> None:
        from PySide6.QtWidgets import QHBoxLayout, QToolButton

        # Model / layout tabs, bottom-left on the coordinates row (BricsCAD).
        self._active_layout = "Model"
        self._block_session = None     # the open Block Editor, if any
        self._layout_tab_host = _LayoutTabHost(self)
        self._layout_tab_bar = QHBoxLayout(self._layout_tab_host)
        self._layout_tab_bar.setContentsMargins(0, 0, 6, 0)
        self._layout_tab_bar.setSpacing(1)
        self.statusBar().addWidget(self._layout_tab_host)
        self._layout_tab_host.installEventFilter(self)    # fit on resize

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
        self._version_label = QLabel(f"IngeCAD {__version__}")
        self.statusBar().addPermanentWidget(self._version_label)
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
            # never narrower than its name: a crowded status bar squeezed the
            # first tab down to an elided "..." (Marco's screenshot)
            b.setMinimumWidth(b.sizeHint().width())
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _=False, n=name: self.switch_layout(n))
            b.setContextMenuPolicy(Qt.CustomContextMenu)
            b.customContextMenuRequested.connect(
                lambda pos, n=name, btn=b: self._layout_tab_menu(
                    n, btn.mapToGlobal(pos)))
            self._tab_buttons[b] = name
            b.installEventFilter(self)          # double-click renames
            self._layout_tab_bar.addWidget(b)
        # AutoCAD's overflow: the tabs that do not fit leave the row and
        # this button lists every layout (a narrow window stacked them on
        # top of each other, unreadable -- the release tour, 2026-10-10).
        more = QToolButton(self._layout_tab_host)
        more.setText("…")
        more.setToolTip(tr("All layouts"))
        more.setStyleSheet(self._TAB_STYLE)
        more.setFocusPolicy(Qt.NoFocus)
        more.clicked.connect(self._layout_overflow_menu)
        self._layout_tab_bar.addWidget(more)
        self._layout_more = more
        plus = QToolButton(self._layout_tab_host)
        plus.setText("+")
        plus.setToolTip(tr("New layout"))
        plus.setStyleSheet(self._TAB_STYLE)
        plus.setFocusPolicy(Qt.NoFocus)
        plus.clicked.connect(self._new_layout_tab)
        self._layout_tab_bar.addWidget(plus)
        self._layout_plus = plus
        self._fit_layout_tabs()

    def _fit_layout_tabs(self) -> None:
        """Show the tabs that fit the row; Model and the active layout
        always, the rest in order while there is room, "…" for the others."""
        host = self._layout_tab_host
        buttons = list(getattr(self, "_tab_buttons", {}))
        more = getattr(self, "_layout_more", None)
        plus = getattr(self, "_layout_plus", None)
        if more is None or plus is None or not buttons:
            return
        spacing = self._layout_tab_bar.spacing()
        width = lambda b: b.sizeHint().width() + spacing  # noqa: E731
        margins = self._layout_tab_bar.contentsMargins()
        room = host.width() - margins.left() - margins.right() - width(plus)
        names = self._tab_buttons
        must = [b for b in buttons
                if names[b] in ("Model", self._active_layout)]
        # Never smaller than Model, the active tab, "…" and "+".
        host.setMinimumWidth(sum(width(b) for b in must) + width(more)
                             + width(plus) + margins.left() + margins.right())
        if sum(width(b) for b in buttons) <= room:
            shown = set(buttons)
        else:
            room -= width(more)
            used = sum(width(b) for b in must)
            shown = set(must)
            for b in buttons:
                if b in shown:
                    continue
                if used + width(b) > room:
                    break
                shown.add(b)
                used += width(b)
        for b in buttons:
            b.setVisible(b in shown)
        more.setVisible(len(shown) < len(buttons))
        # Ask the status bar for room for every tab, hidden ones included,
        # or a row that once overflowed would never grow back.
        full = (sum(width(b) for b in buttons) + width(plus)
                + margins.left() + margins.right())
        if host.full_width != full:
            host.full_width = full
            host.updateGeometry()

    def _layout_overflow_menu(self) -> None:
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        for name in self._layout_names():
            action = menu.addAction(tr("Model") if name == "Model" else name)
            action.setCheckable(True)
            action.setChecked(name == self._active_layout)
            action.setData(name)
        more = self._layout_more
        chosen = menu.exec(more.mapToGlobal(more.rect().topLeft()))
        if chosen is not None:
            self.switch_layout(chosen.data())

    def switch_layout(self, name: str) -> None:
        """Model/Layout tabs: re-render the chosen space (AutoCAD tabs)."""
        self._vp_warm_pending = name != "Model"
        if self._block_session is not None:
            # AutoCAD hides the tabs entirely while the Block Editor is
            # open; refusing the switch is the same rule, said out loud.
            self.command_line.echo(
                tr("Close the Block Editor first (BCLOSE)."))
            self._refresh_layout_tabs()
            return
        if (self.document is None or name == self._active_layout
                or name not in self._layout_names()):
            self._refresh_layout_tabs()   # re-sync checked states
            return
        from core import layouts as layout_ops

        self.tools.cancel()               # drop tool/selection across spaces
        self._deactivate_viewport()       # MSPACE state is per-tab
        self._remember_tab_view()         # the tab left keeps its view
        # $TILEMODE + the *Paper_Space block dance, so the file reopens on
        # this tab in AutoCAD too (ezdxf does not touch the header itself).
        layout_ops.switch_active(self.document, name)
        self._active_layout = name        # ... and the document's space
        first = layout_ops.first_visit_viewport(self.document, name)
        if first is not None:
            self.history.execute(first)
        # Pick, snap and the overlay's curve tolerance all describe ONE
        # space; crossing tabs makes every one of them stale.
        self.tools.space_changed()
        cached = self._layout_scenes.get(name)
        if (cached is not None and cached[0] == self.document.revision
                and self._regen_worker is None):
            # Coming back to a tab already built at this revision: adopt the
            # kept scene instead of re-tessellating the whole drawing (which
            # made every Model/Layout switch cost seconds on a real plan).
            self.viewport.set_scene(cached[1])
            self.tools.mark_scene_merged()
            self._show_tab_view(name)
        else:
            self._regen_view_for = name
            if self._regen_worker is not None:
                self._regen_rerun = True
            else:
                self._start_regen()
        self._refresh_layout_tabs()
        self._update_space_button()
        if name != "Model":
            self.command_line.echo(
                tr("Layout \"{n}\" — draw and edit on the sheet; MVIEW adds "
                   "a viewport, MSPACE works inside it, PSPACE returns.",
                   n=name))

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
            menu.addAction(tr("Move or Copy..."),
                           lambda: self._move_or_copy_layout_tab(name))
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

    def _move_or_copy_layout_tab(self, name: str) -> None:
        """The tab menu's Move or Copy..., as in AutoCAD."""
        from core import layouts as layout_ops
        from views.layout_move_dialog import MoveOrCopyDialog

        dialog = MoveOrCopyDialog(self, layout_ops.layout_names(self.document),
                                  name)
        if dialog.exec():
            self.move_or_copy_layout(name, dialog.before(),
                                     dialog.copy.isChecked())

    def move_or_copy_layout(self, name: str, before, copy: bool) -> None:
        from core import layouts as layout_ops

        if copy:
            new = layout_ops.copy_name(self.document, name)
            self.history.execute(
                layout_ops.CopyLayoutCommand(name, new, before=before))
            self.command_line.echo(tr('Layout "{source}" copied to "{name}".',
                                      source=name, name=new))
        elif before != name:
            self.history.execute(layout_ops.MoveLayoutCommand(name, before))
        self._refresh_layout_tabs()

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

    #: Milliseconds a wait must last before the loading window appears
    #: (tests set 0). A small file must never flash it.
    _loading_min_ms = 400

    def _loading_begin(self, title: str, on_cancel=None) -> None:
        """The "Loading…" window (views/loading_window.py, issue #50): file
        name, phase, elapsed time, Cancel when the work can be abandoned."""
        from views.loading_window import LoadingWindow

        window = getattr(self, "_loading_window", None)
        if window is None:
            window = LoadingWindow(self)
            self._loading_window = window
        window.begin(title, on_cancel, min_ms=self._loading_min_ms)

    def _loading_phase(self, text: str) -> None:
        window = getattr(self, "_loading_window", None)
        if window is not None and window.active:
            window.phase(text)

    def _loading_end(self) -> None:
        window = getattr(self, "_loading_window", None)
        if window is not None:
            window.finish()

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
        vp = self._active_vp
        if vp is not None and vp.is_alive:
            # Inside a viewport the readout is the MODEL coordinate under
            # the pointer, not the millimetre of paper it lands on.
            from core import layouts as layout_ops

            point = layout_ops.paper_to_model(vp, wx, wy)
            if point is not None:
                wx, wy = point
        else:
            from core import ucs

            wx, wy = ucs.current(self.document).to_ucs(wx, wy)
        units = self.display_units()
        self._coords_label.setText(f"{units.length(wx)}, {units.length(wy)}")

    # -- documents -------------------------------------------------------------
    def _open_dialog(self) -> None:
        filename = file_dialogs.get_open_file(
            self,
            tr("Open Drawing"),
            tr("Drawings (*.dwg *.dxf);;All files (*)"),
            preferred=self.document.path if self.document else None,
        )
        if filename:
            self.open_path(Path(filename))

    def _save_as_dialog(self) -> bool:
        if self.document is None:
            self.command_line.echo(tr("Nothing to save yet"))
            return False
        filename, selected = file_dialogs.get_save_file(
            self,
            tr("Save Drawing As"),
            self.document.name,
            self._save_filters(),
            preferred=self.document.path,
        )
        if not filename:
            return False
        path = Path(filename)
        if path.suffix.lower() not in (".dwg", ".dxf"):
            path = path.with_suffix(".dwg" if "dwg" in selected.lower() else ".dxf")
        return self._write_document(path, "r2000")

    def _save_filters(self) -> str:
        """DWG r2000 (LibreDWG, bundled); DXF, always exact."""
        return ";;".join([tr("DWG (*.dwg)"), tr("DXF (*.dxf)")])

    def save_document(self) -> bool:
        """SAVE / QSAVE / Ctrl+S — write over the file that is open.

        A drawing that has never been written has nowhere to go, so it falls
        through to Save As, which is what AutoCAD does with an unnamed
        drawing. Returns True when the drawing actually reached disk, so the
        close-time prompt knows whether it is safe to go.
        """
        if self.document is None:
            self.command_line.echo(tr("Nothing to save yet"))
            return False
        if self.document.path is None:
            return self._save_as_dialog()
        return self._write_document(self.document.path)

    def maybe_save_changes(self) -> bool:
        """True when it is safe to replace or discard the current drawing.

        AutoCAD's rule (CLOSE, Command Reference p. 335): "If you modified
        the drawing since it was last saved, you are prompted to save or
        discard the changes." Cancel keeps the drawing as it was.
        """
        if self.document is None or not self.document.dirty:
            return True
        answer = QMessageBox.warning(
            self,
            tr("IngeCAD"),
            tr("Save changes to {name}?", name=self.document.name),
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save,
        )
        if answer == QMessageBox.Save:
            return self.save_document()
        return answer == QMessageBox.Discard

    def _cmd_drawing_recovery(self, *args) -> None:
        """DRAWINGRECOVERY — the Drawing Recovery Manager (p. 659)."""
        from views.recovery_dialog import DrawingRecoveryDialog, offer_recovery
        from core import autosave

        if not autosave.recoverable():
            self.command_line.echo(
                tr("No drawings to recover — nothing was left by a crash."))
            return
        if not self.maybe_save_changes():
            return
        offer_recovery(self)

    def _cmd_edit_pgp(self, *args) -> None:
        """Tools > Customize > Edit Program Parameters (acad.pgp): open the
        user's alias file in the system editor, creating it the first time."""
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        from core import aliases as aliases_mod

        path = aliases_mod.user_pgp_path()
        try:
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(aliases_mod.starter_pgp(), encoding="utf-8")
        except OSError as exc:
            self.command_line.echo(
                tr("Cannot create {path}: {error}", path=str(path),
                   error=str(exc)))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        self.command_line.echo(
            tr("Editing {path}. Type REINIT after saving it to use the "
               "changes.", path=str(path)))

    def _cmd_reinit(self, *args) -> None:
        """REINIT: the Re-initialization dialog; with PGP File ticked,
        acad.pgp is read again so edited aliases work at once."""
        from views.reinit_dialog import ReinitDialog

        dialog = ReinitDialog(self)
        if dialog.exec() and dialog.pgp.isChecked():
            self._reload_pgp()

    def _reload_pgp(self) -> None:
        from core import aliases as aliases_mod

        self.dispatcher.aliases = aliases_mod.load_aliases()
        self.command_line.echo(
            tr("Program parameters (acad.pgp) reloaded: {n} aliases.",
               n=len(self.dispatcher.aliases)))

    def _cmd_mirrtext(self, *args) -> Prompt | None:
        """MIRRTEXT — 0 keeps mirrored text readable, 1 mirrors it (saved in
        the drawing, initial value 0)."""
        if self.document is None:
            self.new_document()
        from core import mirrtext

        current = 0 if mirrtext.keeps_text_readable(self.document) else 1
        if args and str(args[0]).strip():
            return self._set_mirrtext(str(args[0]))
        return Prompt(
            tr("Enter new value for MIRRTEXT <{v}>:", v=current),
            self._set_mirrtext)

    def _set_mirrtext(self, text: str) -> None:
        text = str(text).strip()
        if not text:
            return
        try:
            value = int(text)
        except ValueError:
            self.command_line.echo(tr("Requires an integer value."))
            return
        if value not in (0, 1):
            self.command_line.echo(
                tr("Value must be between {min} and {max}.", min=0, max=1))
            return
        self.document.doc.header["$MIRRTEXT"] = value
        self.document.dirty = True

    def _cmd_savetime(self, *args) -> Prompt | None:
        """SAVETIME — minutes between automatic saves; 0 turns them off."""
        from core import autosave

        current = autosave.savetime()
        if args and str(args[0]).strip():
            return self._set_savetime(str(args[0]))
        return Prompt(
            tr("Enter new value for SAVETIME <{v}>:", v=current),
            self._set_savetime)

    def _set_savetime(self, text: str) -> None:
        from core import autosave

        try:
            minutes = int(float(str(text).strip()))
        except (TypeError, ValueError):
            self.command_line.echo(tr("Requires an integer value."))
            return
        value = autosave.set_savetime(minutes)
        self._autosave_arm()
        if value:
            self.command_line.echo(
                tr("Automatic save every {n} minutes.", n=value))
        else:
            self.command_line.echo(tr("Automatic save is off."))

    # -- automatic save (SAVETIME) and recovery --------------------------------
    def _autosave_arm(self) -> None:
        """Start the SAVETIME countdown; a save or a new drawing resets it."""
        from core import autosave

        minutes = autosave.savetime()
        self._autosave_timer.stop()
        if minutes > 0 and self.document is not None:
            self._autosave_timer.start(minutes * 60 * 1000)

    def _autosave_idle(self) -> bool:
        """Is this a moment where writing the drawing is safe and unfelt?

        Not while a command is collecting points, not while a regen or an
        open is in flight, and not while the mouse is dragging something --
        AutoCAD postpones its automatic save the same way.
        """
        if self.document is None or not self.document.dirty:
            return False
        if self._autosave_worker is not None:
            return False
        if self._save_worker is not None:
            return False        # the drawing is being saved for real
        # A regen does NOT stand in the way: it reads the document, and so
        # does the autosave -- two readers. Waiting for it was measured to
        # mean "almost never save", because on a real plan a regen is in
        # flight for seconds after every single edit.
        opening = getattr(self, "_open_thread", None)
        if opening is not None and opening.isRunning():
            return False        # the document itself is being replaced
        import time as _time

        if _time.monotonic() - self._last_mutation < self.AUTOSAVE_QUIET_S:
            return False        # still drawing: wait for a pause
        tools = getattr(self, "tools", None)
        if tools is not None:
            # active() = a command is collecting input. NOT
            # in_selection_mode(), which is True whenever no command runs --
            # that is the idle state, and testing it here meant the
            # automatic save never fired at all (measured: the file was
            # never written).
            if tools.active():
                return False
            if getattr(tools, "_grip_drag", None) is not None:
                return False
        return True

    def _autosave_tick(self) -> None:
        from core import autosave

        if autosave.savetime() <= 0:
            return
        if not self._autosave_idle():
            self._autosave_timer.start(30 * 1000)   # busy: ask again shortly
            return
        sv_path, info_path = self._autosave_paths()
        worker = _AutoSaveWorker(self.document, sv_path, info_path)
        worker.done.connect(self._on_autosave_done)
        self._autosave_worker = worker
        gc_guard.start(worker)

    def _on_autosave_done(self, ok: bool, message: str) -> None:
        worker = self._autosave_worker
        self._autosave_worker = None
        if worker is not None:
            worker.wait()
        if ok:
            self.command_line.echo(
                tr("Automatic save to {path}", path=message))
        self._autosave_arm()

    #: How long the drawing must sit still before an automatic save starts.
    AUTOSAVE_QUIET_S = 15.0

    def _autosave_gate(self) -> None:
        """Let a running automatic save finish before the drawing changes.

        The only moment the app can stall. Measured on a plan of 88 897
        entities, an edit that lands right at the start of a write waits
        2.3 s -- which is why the save only starts after the drawing has
        been still for AUTOSAVE_QUIET_S.
        """
        import time as _time

        self._last_mutation = _time.monotonic()
        worker = self._autosave_worker
        if worker is not None and worker.isRunning():
            worker.wait()

    def _autosave_discard(self) -> None:
        """A real save (or a clean exit) makes the automatic one moot."""
        from core import autosave

        if self.document is None:
            return
        self._autosave_gate()
        autosave.discard(*self._autosave_paths())

    def _autosave_paths(self, session=None):
        """This drawing's .sv$ pair; each tab its own (#71)."""
        from core import autosave

        session = session or self._session
        document = session.document if session is not None else self.document
        slot = session.slot if session is not None else 1
        return autosave.autosave_paths(document.path, slot)

    def _autosave_discard_all(self) -> None:
        from core import autosave

        self._autosave_discard()
        for session in self._sessions:
            if session is not self._session and session.document is not None:
                autosave.discard(*self._autosave_paths(session))

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        if getattr(self, "_save_worker", None) is not None:
            event.ignore()             # the window closes after the save
            return
        if not self.maybe_save_all():      # every open drawing (#71)
            event.ignore()
            return
        self._drain_workers()
        # A normal exit leaves nothing behind: what the Drawing Recovery
        # Manager lists is, by definition, what a crash left.
        self._autosave_discard_all()
        if self.isVisible():                 # a never-shown window has none
            QSettings().setValue(SETTING_WINDOW_GEOMETRY, self.saveGeometry())
        event.accept()

    def restore_window_geometry(self) -> bool:
        """The size, place and maximized state the window was closed with
        (#72: it always came back at 1280 x 800). Called by the application
        at start-up, before show(); a window made in a test keeps its
        default. On Wayland the compositor places the window, so only the
        size and the maximized state come back there."""
        geometry = QSettings().value(SETTING_WINDOW_GEOMETRY)
        if not geometry:
            return False
        return bool(self.restoreGeometry(geometry))

    def _drain_workers(self) -> None:
        """Join every background thread before the window dies.

        Qt aborts the whole process ("QThread: Destroyed while thread is
        still running") when a live worker's owner is destroyed — closing
        the app with a regen in flight was a guaranteed SIGABRT on exit.
        The results are not wanted any more, only the joins.
        """
        saving = getattr(self, "_save_worker", None)
        if saving is not None:
            saving.wait()
        live = getattr(self, "_vp_live_worker", None)
        if live is not None:
            try:
                live.done.disconnect(self._on_live_scene_done)
            except (RuntimeError, TypeError):
                pass
            live.wait()
        worker = self._regen_worker
        if worker is not None:
            self._regen_worker = None
            try:
                worker.done.disconnect(self._on_regen_done)
            except (RuntimeError, TypeError):
                pass          # already disconnected
            worker.wait()
        thread = getattr(self, "_open_thread", None)
        if thread is not None:
            thread.wait()
            self._open_thread = None
        timer = getattr(self, "_autosave_timer", None)
        if timer is not None:
            timer.stop()
        auto = getattr(self, "_autosave_worker", None)
        if auto is not None:
            auto.wait()
            self._autosave_worker = None
        from views import startup_dialog as _startup

        _startup.drain_orphans()    # thumbnail workers the dialog left behind
        tools = getattr(self, "tools", None)
        if tools is not None:
            timer = getattr(tools, "_merge_timer", None)
            if timer is not None:
                timer.stop()
            for attr in ("_warmers", "_ghost_workers", "_clip_writers"):
                for w in list(getattr(tools, attr, ()) or ()):
                    w.wait()

    def _save_off_the_ui_thread(self, path: Path, version: str):
        """Save, keeping the window alive: the whole save runs on a
        _SaveWorker while a local event loop keeps painting. Keyboard and
        mouse are held until it ends (eventFilter), as AutoCAD holds them
        while it saves -- nothing can edit, open or close the drawing
        halfway through, which is also what lets the worker read it.
        Returns (engine, warnings)."""
        from PySide6.QtCore import QEventLoop

        self._store_views_for_save()     # opens where it was left (AutoCAD)
        document = self.document
        worker = _SaveWorker(lambda: document.prepare_save(path, version)())
        loop = QEventLoop()
        worker.finished.connect(loop.quit)
        self._save_worker = worker
        self.command_line.echo(tr("Saving {name}...", name=path.name))
        self._loading_begin(tr("Saving {name}...", name=path.name))
        if path.suffix.lower() == ".dwg":
            self._loading_phase(tr("Writing the DXF, converting with LibreDWG "
                                   "and checking the result..."))
        QApplication.setOverrideCursor(Qt.BusyCursor)
        # a modal window takes the focus off the windows it blocks and does
        # not hand it back: remember who typed, and give it back after
        focused = QApplication.focusWidget()
        hold = _InputHold(self)
        hold.show()
        try:
            gc_guard.start(worker)
            if not worker.isFinished():
                loop.exec()
            worker.wait()
        finally:
            hold.close()
            if focused is not None and focused.isVisible():
                focused.activateWindow()
                focused.setFocus()
            QApplication.restoreOverrideCursor()
            self._save_worker = None
            self._loading_end()
        if worker.error is not None:
            raise worker.error
        return worker.result

    def _write_document(self, path: Path, version: str = "r2000") -> bool:
        """The shared tail of SAVE and SAVEAS: write, report, warn."""
        if self.document is None:
            return False
        if self._save_worker is not None:
            return False           # one save at a time (input is held meanwhile)
        self._autosave_gate()      # never write while the .sv$ is being made
        try:
            engine, warnings = self._save_off_the_ui_thread(path, version)
        except Exception as exc:
            QMessageBox.warning(
                self,
                tr("Save Drawing"),
                tr("Cannot save {name}: {error}", name=path.name, error=str(exc)),
            )
            return False
        self.document.saved_to(path)
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
        # "It is reset and restarted by a manual QSAVE, SAVE, or SAVEAS"
        # (SAVETIME) -- and what the drawing was rescued into is now moot.
        self._autosave_discard()
        self._autosave_arm()
        return True

    def open_paths(self, paths) -> None:
        """Several drawings, each in a tab of its own, one after another --
        the file manager's double-clicks handed over by a second IngeCAD
        (core/single_instance.py), or several files on the command line.
        An open runs one at a time, so the rest wait their turn."""
        self._pending_opens.extend(Path(p) for p in paths)
        self._open_next_pending()

    def _open_next_pending(self) -> None:
        while self._pending_opens and self._open_thread is None:
            self.open_path(self._pending_opens.pop(0))

    def open_path(self, path: Path, as_template: bool = False) -> None:
        """OS file associations, argv[1], and File > Open land here.

        ``as_template`` keeps the content and drops the origin, so the drawing
        becomes an unnamed new one.
        """
        if not as_template:
            # AutoCAD brings the drawing already open to the front rather
            # than opening it a second time (two tabs, two sets of edits,
            # one file).
            session = self._session_for_path(path)
            if session is not None:
                self.switch_document(session)
                self.command_line.echo(
                    tr("{name} is already open.", name=path.name))
                return
        self._open_as_template = bool(as_template)
        if path.suffix.lower() == ".dwg":
            from formats.dwg_bridge import have_dwg_support

            if not have_dwg_support():
                QMessageBox.warning(
                    self,
                    tr("Open Drawing"),
                    tr("DWG support needs LibreDWG's converter (dwg2dxf), "
                       "and it was not found."),
                )
                return
        if self._open_thread is not None:
            self.command_line.echo(tr("Still opening the previous drawing..."))
            return
        self._opening_name = path.name
        self._open_cancelled = False
        self._set_busy(tr("Opening {name}...", name=path.name))
        self._loading_begin(tr("Loading {name}...", name=path.name),
                            on_cancel=self._cancel_open)
        worker = _OpenWorker(path)
        # a bound method of this window, never a lambda: PySide runs a plain
        # callable in the EMITTER's thread, and the loading window's label
        # was being set from the open thread (the CI's segfaults and bus
        # errors in test_cancel_abandons_the_open)
        worker.phase.connect(self._on_open_phase)
        worker.done.connect(self._on_open_done)
        worker.failed.connect(self._on_open_failed)
        worker.finished.connect(self._on_open_thread_finished)
        self._open_thread = worker  # "an open is running", and its owner
        self._open_worker = worker
        gc_guard.start(worker)

    def _on_open_phase(self, text: str) -> None:
        self._loading_phase(tr(text))

    def _cancel_open(self) -> None:
        """Cancel on the loading window: the worker cannot be stopped
        mid-parse, so its result is abandoned when it lands."""
        self._open_cancelled = True
        self._set_busy("")
        self.command_line.echo(
            tr("Opening {name} cancelled.", name=self._opening_name))

    def _on_open_done(self, document: Document, scene) -> None:
        from core import recent as recent_mod

        self._set_busy("")
        self._loading_end()
        if getattr(self, "_open_cancelled", False):
            self._open_cancelled = False
            return
        if getattr(self, "_open_as_template", False):
            document.path = None          # a template has no file of its own
            document.dirty = True
        elif document.path is not None:
            recent_mod.add(document.path)
            self._refresh_recent_menu()
        self._open_as_template = False
        self._tab_for_new_document(document)      # a tab of its own (#71)
        self.document = document
        self._autosave_arm()          # a new drawing, a new countdown
        self._layout_scenes.clear()   # scenes of the previous drawing
        self._deactivate_viewport()
        # the open may have fallen back to a paper layout (empty modelspace)
        self._active_layout = scene.layout_name or "Model"
        self._refresh_layout_tabs()
        self._update_space_button()
        self.viewport.set_scene(scene)
        # The open built this tab's scene: keep it, so the first switch away
        # and back does not re-tessellate an untouched drawing.
        self._layout_scenes[self._active_layout] = (document.revision, scene)
        self._layout_cameras = {}
        # where its author left it, as AutoCAD opens a drawing
        self._show_tab_view(self._active_layout)
        self.tools.attach_document(document, flatten=scene.flatten)
        self.refresh_grid_settings()
        self.plugins.document_opened(document)
        if self._layers_panel is not None:
            self._layers_panel.refresh()   # show the opened drawing's layers
        if getattr(self, "_styles_panel", None) is not None:
            self._styles_panel.refresh()   # and its text/dimension styles
        if getattr(self, "_xrefs_panel", None) is not None:
            self._xrefs_panel.refresh()    # and its external references
        if getattr(self, "_props_toolbar", None) is not None:
            self._refresh_props_toolbar()
        self.setWindowTitle(f"IngeCAD — {document.name}")
        self._refresh_file_tabs()
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
        self._loading_end()
        if getattr(self, "_open_cancelled", False):
            self._open_cancelled = False
            return
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
            # ONE owner for the worker: Python, here, on the GUI thread, once
            # run() has truly returned. A `finished -> worker.deleteLater`
            # had Qt delete it on the open thread while this line dropped
            # the Python reference -- both destroyed it (the CI's SIGBUS in
            # Shiboken::Object::destroy, on the "open-drawing" thread).
            self._open_thread.wait()
        self._open_thread = None
        self._open_worker = None
        self._open_next_pending()     # the next drawing handed over, if any
