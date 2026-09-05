# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""OPTIONS — the program settings, under AutoCAD's own tab names.

The reference (p. 1314) lists ten tabs: Files, Display, Open and Save, Plot
and Publish, System, User Preferences, Drafting, 3D Modeling, Selection and
Profiles. IngeCAD shows the four it can fill honestly, keeping AutoCAD's
names so a setting is where the muscle memory expects it, and leaves the
rest out rather than showing empty pages:

* **Files** — the units of the template a new drawing starts from.
* **Display** — language, the startup window, lineweight display, the grid.
* **Drafting** — the running object snaps (AutoCAD's Object Snap options).
* **User Preferences** — what the right button does in the drawing area,
  which is AutoCAD's Right-click Customization (SHORTCUTMENU, p. 2509).
* **Selection** — the object-count past which grips stop being drawn
  (GRIPOBJLIMIT, p. 2339).

Everything here is stored through ``QSettings``, so it outlives the session;
the drawing itself is never touched. OK applies and closes, Cancel discards,
Apply applies and stays — the three buttons the dialog has always had.
"""
from __future__ import annotations

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.i18n import tr
from render import backend
from views import apertures
from views import viewport as viewport_prefs

#: Right-click in the drawing area with nothing selected and no command
#: running: AutoCAD lets it be either the shortcut menu or Enter, and a great
#: many drafters set it to Enter to repeat the last command.
SETTING_RIGHT_CLICK = "input/right_click"
RIGHT_CLICK_MENU = "menu"
RIGHT_CLICK_ENTER = "enter"

#: Persisted display toggles that were session-only before.
SETTING_LWT = "display/lineweight"
SETTING_GRID = "display/grid"
#: Wait for the vertical refresh before showing a frame. On costs a frame of
#: latency and cannot tear; off is the other way round.
SETTING_VSYNC = "display/vsync"
#: Line smoothing = multisampling in the widget's own framebuffer. Fixed
#: when the canvas is created, so it takes effect on the next start.
SETTING_MSAA = "display/msaa"


def right_click_mode() -> str:
    """What the right button does on an idle canvas."""
    value = str(QSettings().value(SETTING_RIGHT_CLICK, RIGHT_CLICK_MENU))
    return value if value in (RIGHT_CLICK_MENU, RIGHT_CLICK_ENTER) \
        else RIGHT_CLICK_MENU


def _int_setting(key: str, default: int) -> int:
    try:
        return int(QSettings().value(key, default))
    except (TypeError, ValueError):
        return default


def _bool_setting(key: str, default: bool) -> bool:
    return str(QSettings().value(key, "true" if default else "false")
               ).lower() not in ("false", "0")


class OptionsDialog(QDialog):
    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self.setWindowTitle(tr("Options"))
        root = QVBoxLayout(self)

        # AutoCAD shows the current drawing above the tabs.
        name = getattr(window.document, "name", None) if window.document else None
        root.addWidget(QLabel(tr("Current drawing: {name}",
                                 name=name or tr("Untitled"))))

        self.tabs = QTabWidget(self)
        self.tabs.addTab(self._files_tab(), tr("Files"))
        self.tabs.addTab(self._open_save_tab(), tr("Open and Save"))
        self.tabs.addTab(self._display_tab(), tr("Display"))
        self.tabs.addTab(self._drafting_tab(), tr("Drafting"))
        self.tabs.addTab(self._user_tab(), tr("User Preferences"))
        self.tabs.addTab(self._selection_tab(), tr("Selection"))
        # A plugin may add a page of its own (docs/plugins.md): built with
        # (dialog, window), and its apply() runs with the others on OK.
        self._plugin_pages: list = []
        manager = getattr(window, "plugins", None)
        for spec in (manager.active_specs() if manager is not None else []):
            if spec.options_page is None:
                continue
            page = spec.options_page(self, window)
            self.tabs.addTab(page, tr(spec.name))
            self._plugin_pages.append(page)
        root.addWidget(self.tabs, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
            | QDialogButtonBox.Apply, self)
        buttons.accepted.connect(self._ok)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.Apply).clicked.connect(self.apply)
        root.addWidget(buttons)
        self.resize(520, 420)

    # -- tabs -----------------------------------------------------------------
    def _files_tab(self) -> QWidget:
        from views.startup_dialog import SETTING_TEMPLATE

        page = QWidget(self)
        form = QFormLayout(page)
        self.template = QComboBox(page)
        for label, code in ((tr("Millimeters"), "mm"), (tr("Centimeters"), "cm"),
                            (tr("Meters"), "m")):
            self.template.addItem(label, code)
        current = str(QSettings().value(SETTING_TEMPLATE, "mm"))
        index = self.template.findData(current)
        self.template.setCurrentIndex(index if index >= 0 else 0)
        form.addRow(tr("New drawings start in:"), self.template)
        note = QLabel(tr("The template a new drawing is created from — the "
                         "same choice the startup window offers."), page)
        note.setWordWrap(True)
        form.addRow(note)
        return page

    def _open_save_tab(self) -> QWidget:
        """AutoCAD's Open and Save tab, with its File Safety Precautions
        group: the automatic save and how often it runs (SAVETIME)."""
        from core import autosave

        page = QWidget(self)
        outer = QVBoxLayout(page)

        box = QGroupBox(tr("File Safety Precautions"), page)
        inner = QVBoxLayout(box)
        minutes = autosave.savetime()
        self.autosave_on = QCheckBox(tr("Automatic save"), box)
        self.autosave_on.setChecked(minutes > 0)
        inner.addWidget(self.autosave_on)

        row = QHBoxLayout()
        row.addSpacing(20)
        row.addWidget(QLabel(tr("Minutes between saves:"), box))
        self.autosave_minutes = QSpinBox(box)
        self.autosave_minutes.setRange(1, autosave.MAX_SAVETIME)
        self.autosave_minutes.setValue(minutes or autosave.DEFAULT_SAVETIME)
        self.autosave_minutes.setEnabled(minutes > 0)
        self.autosave_on.toggled.connect(self.autosave_minutes.setEnabled)
        row.addWidget(self.autosave_minutes)
        row.addStretch(1)
        inner.addLayout(row)

        note = QLabel(
            tr("The drawing is copied to a recovery file while you work; a "
               "real save clears it. The copy is written in the background, "
               "so it does not interrupt what you are doing. What a crash "
               "leaves behind is offered at the next start, and in File ▸ "
               "Drawing Utilities ▸ Drawing Recovery."), box)
        note.setWordWrap(True)
        inner.addWidget(note)

        folder = QHBoxLayout()
        folder.addWidget(QLabel(tr("Recovery files are kept in:"), box))
        self.autosave_path = QLabel(str(autosave.save_file_path()), box)
        self.autosave_path.setTextInteractionFlags(
            Qt.TextSelectableByMouse)
        self.autosave_path.setWordWrap(True)
        folder.addWidget(self.autosave_path, 1)
        inner.addLayout(folder)
        outer.addWidget(box)
        outer.addStretch(1)
        return page

    def _display_tab(self) -> QWidget:
        from core import i18n
        from views.startup_dialog import SETTING_SHOW

        page = QWidget(self)
        outer = QVBoxLayout(page)
        form = QFormLayout()
        self.language = QComboBox(page)
        # Each language in its own name: recognizable whichever is active.
        # The list comes from the packs in i18n/ — see core/i18n/packs.py.
        for code in i18n.available_languages():
            self.language.addItem(i18n.language_name(code), code)
        index = self.language.findData(i18n.current_language())
        self.language.setCurrentIndex(index if index >= 0 else 0)
        form.addRow(tr("Language:"), self.language)
        outer.addLayout(form)

        box = QGroupBox(tr("Window Elements"), page)
        inner = QVBoxLayout(box)
        self.show_startup = QCheckBox(tr("Show the startup window"), box)
        self.show_startup.setChecked(_bool_setting(SETTING_SHOW, True))
        inner.addWidget(self.show_startup)
        self.show_lwt = QCheckBox(tr("Display lineweights"), box)
        self.show_lwt.setChecked(bool(self.window.viewport.lwt_on))
        inner.addWidget(self.show_lwt)
        self.show_grid = QCheckBox(tr("Display grid"), box)
        self.show_grid.setChecked(bool(self.window.viewport.grid_on))
        inner.addWidget(self.show_grid)
        self.vsync = QCheckBox(
            tr("Wait for the screen refresh (no tearing)"), box)
        self.vsync.setChecked(_bool_setting(SETTING_VSYNC, True))
        self.vsync.setToolTip(
            tr("On, a frame waits for the monitor: nothing ever tears, and "
               "the pointer runs up to one refresh ahead of the drawing. "
               "Off, the canvas answers sooner and may show a seam while "
               "panning. Takes effect the next time IngeCAD starts."))
        inner.addWidget(self.vsync)
        outer.addWidget(box)

        # AutoCAD's own group on this tab (p.1348): how smooth curves and
        # edges are drawn.
        box = QGroupBox(tr("Window Elements"), page)
        elements_row = QHBoxLayout(box)
        self.colors_button = QPushButton(tr("Colors..."), box)
        self.colors_button.setToolTip(
            tr("Background of the model, sheets and the Block Editor — "
               "AutoCAD's Drawing Window Colors."))
        self.colors_button.clicked.connect(self._open_window_colors)
        elements_row.addWidget(self.colors_button)
        elements_row.addStretch(1)
        outer.addWidget(box)

        box = QGroupBox(tr("Display resolution"), page)
        grid = QFormLayout(box)
        self.msaa = QComboBox(box)
        self.msaa.addItem(tr("Off (fastest)"), 0)
        self.msaa.addItem(tr("Smooth (4x)"), 4)
        self.msaa.addItem(tr("Smoothest (8x)"), 8)
        index = self.msaa.findData(_int_setting(SETTING_MSAA, 4))
        self.msaa.setCurrentIndex(index if index >= 0 else 1)
        self.msaa.setToolTip(
            tr("Softens the staircase on slanted lines and text. Measured on "
               "a real sheet: 4x costs about 0.7 ms of a frame, 8x about "
               "1.8 ms. Takes effect the next time IngeCAD starts."))
        grid.addRow(tr("Line smoothing:"), self.msaa)

        self.viewres = QSpinBox(box)
        self.viewres.setRange(backend.VIEWRES_MIN, backend.VIEWRES_MAX)
        self.viewres.setValue(backend.viewres())
        self.viewres.setToolTip(
            tr("VIEWRES: how many short vectors a circle or arc is drawn "
               "with. A small circle can look like a polygon when you zoom "
               "in; raising this smooths it, and may slow the regen down."))
        grid.addRow(tr("Arc and circle smoothness:"), self.viewres)
        outer.addWidget(box)

        # AutoCAD's Display tab also owns the cursor: Crosshair Size
        # (CURSORSIZE) and, through its Colors dialog, the crosshair colour.
        box = QGroupBox(tr("Crosshair"), page)
        grid = QFormLayout(box)
        self.cursorsize = QSpinBox(box)
        self.cursorsize.setRange(1, 100)
        self.cursorsize.setValue(viewport_prefs.cursorsize())
        self.cursorsize.setSuffix(" %")
        self.cursorsize.setToolTip(
            tr("The crosshair length as a percentage of the screen, like "
               "AutoCAD's CURSORSIZE. 100 reaches every edge; AutoCAD's own "
               "default is 5."))
        grid.addRow(tr("Crosshair size:"), self.cursorsize)

        row = QHBoxLayout()
        self._crosshair_color = viewport_prefs.crosshair_color()
        self.crosshair_swatch = QPushButton(box)
        self.crosshair_swatch.setFixedWidth(70)
        self.crosshair_swatch.clicked.connect(self._pick_crosshair_color)
        row.addWidget(self.crosshair_swatch)
        self.crosshair_auto = QPushButton(tr("Automatic"), box)
        self.crosshair_auto.setToolTip(
            tr("Light over the dark model, dark over a white sheet — what "
               "the canvas did before there was a choice."))
        self.crosshair_auto.clicked.connect(self._reset_crosshair_color)
        row.addWidget(self.crosshair_auto)
        row.addStretch(1)
        holder = QWidget(box)
        holder.setLayout(row)
        grid.addRow(tr("Crosshair color:"), holder)
        self._show_crosshair_swatch()
        outer.addWidget(box)
        outer.addStretch(1)
        return page

    def _show_crosshair_swatch(self) -> None:
        color = self._crosshair_color
        if color is None:
            self.crosshair_swatch.setText(tr("Automatic"))
            self.crosshair_swatch.setStyleSheet("")
        else:
            self.crosshair_swatch.setText("")
            self.crosshair_swatch.setStyleSheet(
                f"background-color: {color.name()};")

    def _open_window_colors(self) -> None:
        from views.window_colors_dialog import WindowColorsDialog

        dialog = WindowColorsDialog(self)
        if dialog.exec() != WindowColorsDialog.Accepted:
            return
        # the Display tab's own swatch mirrors the dialog's crosshair edit
        from views import viewport as viewport_prefs

        self._crosshair_color = viewport_prefs.crosshair_color()
        self._show_crosshair_swatch()
        if dialog.changed_backgrounds():
            # ACI 7 flips and text masks refill against the new canvas:
            # only a regen re-resolves those colours.
            window = self.parent()
            if window is not None and hasattr(window, "regen_in_memory"):
                window.regen_in_memory()

    def _pick_crosshair_color(self) -> None:
        from PySide6.QtWidgets import QColorDialog

        start = self._crosshair_color
        chosen = QColorDialog.getColor(
            start if start is not None else QColor(215, 215, 215), self,
            tr("Crosshair color"))
        if chosen.isValid():
            self._crosshair_color = chosen
            self._show_crosshair_swatch()

    def _reset_crosshair_color(self) -> None:
        self._crosshair_color = None
        self._show_crosshair_swatch()

    def _drafting_tab(self) -> QWidget:
        """The very list the Drafting Settings dialog shows — same widget,
        so the two can never disagree about what a snap is called."""
        from views.osnap_dialog import OsnapModesPanel

        page = QWidget(self)
        layout = QVBoxLayout(page)
        self.osnap_panel = OsnapModesPanel(page, self.window.tools.osnap_modes,
                                           self.window.tools.osnap_on)
        layout.addWidget(self.osnap_panel, 1)
        return page

    def _user_tab(self) -> QWidget:
        page = QWidget(self)
        outer = QVBoxLayout(page)
        box = QGroupBox(tr("Right-click Customization"), page)
        inner = QVBoxLayout(box)
        inner.addWidget(QLabel(
            tr("Right-click in the drawing area, with no command running "
               "and nothing selected:"), box))
        self.right_click = QComboBox(box)
        self.right_click.addItem(tr("Show the shortcut menu"), RIGHT_CLICK_MENU)
        self.right_click.addItem(tr("Repeat the last command (Enter)"),
                                 RIGHT_CLICK_ENTER)
        index = self.right_click.findData(right_click_mode())
        self.right_click.setCurrentIndex(index if index >= 0 else 0)
        inner.addWidget(self.right_click)
        outer.addWidget(box)
        outer.addStretch(1)
        return page

    def _selection_tab(self) -> QWidget:
        """AutoCAD's Selection tab, the one row IngeCAD honours (p.1348)."""
        from views.tool_controller import gripobjlimit

        page = QWidget(self)
        outer = QVBoxLayout(page)
        box = QGroupBox(tr("Grips"), page)
        form = QFormLayout(box)
        self.gripobjlimit = QSpinBox(box)
        self.gripobjlimit.setRange(0, 32767)
        self.gripobjlimit.setValue(gripobjlimit())
        self.gripobjlimit.setSpecialValueText(tr("Always show grips"))
        form.addRow(tr("Object selection limit for display of grips:"),
                    self.gripobjlimit)
        self.pickbox = QSpinBox(box)
        self.pickbox.setRange(1, 50)
        self.pickbox.setValue(apertures.pickbox())
        self.pickbox.setSuffix(" px")
        self.pickbox.setToolTip(
            tr("AutoCAD's PICKBOX: the little square at the cursor that "
               "picks objects. It sets what you SEE and what actually "
               "catches, together."))
        form.addRow(tr("Pickbox size:"), self.pickbox)
        note = QLabel(
            tr("Grips are hidden when the selection holds more objects than "
               "this. Drawing thousands of them costs a frame; 0 always "
               "shows them."), box)
        note.setWordWrap(True)
        note.setStyleSheet("color: #9aa0a6;")
        form.addRow(note)
        outer.addWidget(box)
        outer.addStretch(1)
        return page

    # -- applying -------------------------------------------------------------
    def apply(self) -> None:
        from core import i18n, osnap as osnap_modes
        from views.startup_dialog import SETTING_SHOW, SETTING_TEMPLATE

        settings = QSettings()
        settings.setValue(SETTING_TEMPLATE, self.template.currentData())
        settings.setValue(SETTING_SHOW, self.show_startup.isChecked())

        viewport = self.window.viewport
        viewport.lwt_on = self.show_lwt.isChecked()
        viewport.grid_on = self.show_grid.isChecked()
        settings.setValue(SETTING_LWT, viewport.lwt_on)
        settings.setValue(SETTING_GRID, viewport.grid_on)
        settings.setValue(SETTING_VSYNC, self.vsync.isChecked())
        settings.setValue(SETTING_MSAA, self.msaa.currentData())
        settings.setValue(viewport_prefs.SETTING_CURSORSIZE,
                          self.cursorsize.value())
        settings.setValue(viewport_prefs.SETTING_CROSSHAIR_COLOR,
                          "" if self._crosshair_color is None
                          else self._crosshair_color.name())
        settings.setValue(apertures.SETTING_PICKBOX, self.pickbox.value())
        from core import autosave

        autosave.set_savetime(self.autosave_minutes.value()
                              if self.autosave_on.isChecked() else 0)
        arm = getattr(self.window, "_autosave_arm", None)
        if arm is not None:
            arm()          # the new interval starts counting now
        viewport.refresh_cursor_prefs()
        if self.viewres.value() != backend.viewres():
            settings.setValue(backend.SETTING_VIEWRES, self.viewres.value())
            # "The model is regenerated" (VIEWRES, p.2049) -- the tolerance
            # is baked into the tessellation, so only a regen can show it.
            # The overlay tessellates at the same tolerance, so it has to
            # follow or a freshly drawn arc would not match the base scene.
            self.window.refresh_curve_tolerance()
        viewport.update()

        tools = self.window.tools
        tools.osnap_modes = set(self.osnap_panel.modes())
        tools.osnap_on = self.osnap_panel.osnap_on()
        self.window._save_osnap_modes()

        settings.setValue(SETTING_RIGHT_CLICK, self.right_click.currentData())

        from views.tool_controller import SETTING_GRIPOBJLIMIT

        settings.setValue(SETTING_GRIPOBJLIMIT, self.gripobjlimit.value())
        tools._grips_cache = None       # the limit just moved: re-decide
        self.window.viewport.update()

        if self.language.currentData() != i18n.current_language():
            # last: it rebuilds the menus, and the reference's own note is
            # that a language change needs a restart to reach everything
            self.window._set_language(self.language.currentData())
        self.window._update_mode_buttons()
        # a plugin's page applies with the core ones -- on Apply as much as
        # on OK, or the button would silently skip half the dialog
        for page in self._plugin_pages:
            if hasattr(page, "apply"):
                page.apply()

    def _ok(self) -> None:
        self.apply()
        self.accept()
