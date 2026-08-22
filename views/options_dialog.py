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

Everything here is stored through ``QSettings``, so it outlives the session;
the drawing itself is never touched. OK applies and closes, Cancel discards,
Apply applies and stays — the three buttons the dialog has always had.
"""
from __future__ import annotations

from PySide6.QtCore import QSettings
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
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.i18n import tr

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


def right_click_mode() -> str:
    """What the right button does on an idle canvas."""
    value = str(QSettings().value(SETTING_RIGHT_CLICK, RIGHT_CLICK_MENU))
    return value if value in (RIGHT_CLICK_MENU, RIGHT_CLICK_ENTER) \
        else RIGHT_CLICK_MENU


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
        self.tabs.addTab(self._display_tab(), tr("Display"))
        self.tabs.addTab(self._drafting_tab(), tr("Drafting"))
        self.tabs.addTab(self._user_tab(), tr("User Preferences"))
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

        # AutoCAD's own group name for the Display tab's toggles; its
        # "Display resolution" is arc smoothness, which we do not have.
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
        outer.addStretch(1)
        return page

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
        viewport.update()

        tools = self.window.tools
        tools.osnap_modes = set(self.osnap_panel.modes())
        tools.osnap_on = self.osnap_panel.osnap_on()
        self.window._save_osnap_modes()

        settings.setValue(SETTING_RIGHT_CLICK, self.right_click.currentData())

        if self.language.currentData() != i18n.current_language():
            # last: it rebuilds the menus, and the reference's own note is
            # that a language change needs a restart to reach everything
            self.window._set_language(self.language.currentData())
        self.window._update_mode_buttons()

    def _ok(self) -> None:
        self.apply()
        self.accept()
