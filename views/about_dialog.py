# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Help ▸ About IngeCAD, with the contributors rolling like film credits.

The same dialog as IngeTrazo's (Marco, 2026-10-09: "al mismo estilo que
hicimos en IngeTrazo"): the people whose work is IN the program -- filmed
reviews, translations, reports that changed how it works -- roll up
slowly in a band a few lines tall, round and round; the pointer stops
them and the wheel scrolls them. AUTHORS says what each one gave.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from core.i18n import tr

#: (name, what they gave — English source for tr(), link or "").
CONTRIBUTORS = [
    ("Rafael García Rodríguez",
     "Draftsman and reviewer. Filmed reviews of the whole program and the "
     "drafting standards behind its dimensions, annotative scales and "
     "plotting.",
     "https://youtube.com/@Rafa3D"),
    ("Arthur Emmanuel de Medeiros Nóbrega",
     "Reports and requests from daily drafting: plotting, layouts, layers, "
     "grips, text styles and justification, copying between drawings.",
     "https://github.com/arthurarquitetoamb"),
    ("Michal Josef Špaček",
     "Czech translation of the interface, and the first reports on "
     "translations and keyboard shortcuts.",
     "https://github.com/michal-josef-spacek"),
    ("Yann Steffan",
     "French translation of the interface.",
     "https://github.com/YannFR81"),
    ("John Donovan",
     "Asked for any map projection: georeferencing by EPSG code with PROJ.",
     "https://github.com/GeoSpark"),
    ("Riccardo Gagliarducci",
     "The polyline OFFSET report that rebuilt how offsets are cleaned up.",
     "https://github.com/canonex"),
    ("batoceragaming",
     "Asked for a Window plot area and for the AppImage of every release.",
     "https://github.com/batoceragaming"),
    ("javierrondont",
     "Asked for DXF export.",
     "https://github.com/javierrondont"),
    ("Jozsef",
     "Reported the AppImage that would not start.",
     "https://github.com/jozsefk9"),
]

#: Roll speed: pixels per tick, and the tick.
ROLL_PX = 1
ROLL_MS = 45


def _credits_html(people) -> str:
    rows = []
    for name, role, link in people:
        who = (f"<a href='{link}'><b>{name}</b></a>" if link
               else f"<b>{name}</b>")
        rows.append(f"<p style='margin:0 0 10px 0'>{who}<br>{tr(role)}</p>")
    return "".join(rows)


class _Fade(QWidget):
    """Soft top and bottom edges over the roll, in the window's colour."""

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def paintEvent(self, event) -> None:  # noqa: N802
        from PySide6.QtGui import QColor, QLinearGradient, QPainter
        bg = self.palette().window().color()
        clear = QColor(bg)
        clear.setAlpha(0)
        p = QPainter(self)
        edge = min(22, self.height() // 4)
        for y0, y1, a, b in ((0, edge, bg, clear),
                             (self.height() - edge, self.height(), clear, bg)):
            g = QLinearGradient(0, y0, 0, y1)
            g.setColorAt(0.0, a)
            g.setColorAt(1.0, b)
            p.fillRect(0, y0, self.width(), y1 - y0, g)
        p.end()


class _Credits(QWidget):
    """Every contributor, rolling up slowly and looping, like film credits.
    Two copies of the list sit one above the other; when the first has
    rolled out of view the roll starts over, seamlessly. The pointer over
    it stops the roll and the wheel scrolls it by hand, both ways (Marco:
    «me gustaría poder scrollear para saber qué usuarios hay apoyando»);
    it rolls on again when the pointer leaves."""

    LINES = 11

    def __init__(self, people, parent=None) -> None:
        super().__init__(parent)
        self._people = list(people)
        html = _credits_html(self._people)
        self._copies = []
        for _ in range(2):
            lab = QLabel(html, self)
            lab.setWordWrap(True)
            lab.setTextFormat(Qt.RichText)
            lab.setOpenExternalLinks(True)
            lab.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            self._copies.append(lab)
        self._fade = _Fade(self)
        self.setFixedHeight(self.fontMetrics().lineSpacing() * self.LINES + 8)
        self._offset = 0.0
        self._span = 1
        self._timer = QTimer(self)
        self._timer.setInterval(ROLL_MS)
        self._timer.timeout.connect(self.tick)
        self._timer.start()

    @property
    def running(self) -> bool:
        return self._timer.isActive()

    @property
    def offset(self) -> float:
        return self._offset

    @property
    def span(self) -> int:
        return self._span

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        w = self.width()
        self._span = max(1, self._copies[0].heightForWidth(w))
        for lab in self._copies:
            lab.resize(w, self._span)
        self._fade.setGeometry(0, 0, w, self.height())
        self._place()

    def tick(self) -> None:
        self._offset = (self._offset + ROLL_PX) % self._span
        self._place()

    def scroll_by(self, pixels: float) -> None:
        """Move the roll by hand (positive = on down the list), looping."""
        self._offset = (self._offset + pixels) % self._span
        self._place()

    def wheelEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()
        steps = event.angleDelta().y() / 120.0
        self.scroll_by(-steps * self.fontMetrics().lineSpacing() * 3)
        event.accept()

    def enterEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()                  # read a name without it moving
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._timer.start()
        super().leaveEvent(event)

    def _place(self) -> None:
        y = -int(self._offset)
        self._copies[0].move(0, y)
        self._copies[1].move(0, y + self._span)
        self._fade.raise_()


class AboutDialog(QDialog):
    def __init__(self, parent, version: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("About IngeCAD"))
        self.setMinimumWidth(480)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 14)
        outer.setSpacing(16)
        from PySide6.QtWidgets import QApplication
        icon = QApplication.windowIcon()
        if not icon.isNull():
            pic = QLabel(self)
            pic.setPixmap(icon.pixmap(64, 64))
            pic.setAlignment(Qt.AlignTop)
            outer.addWidget(pic, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(4)
        outer.addLayout(col, 1)

        def para(html: str) -> QLabel:
            lab = QLabel(html, self)
            lab.setWordWrap(True)
            lab.setTextFormat(Qt.RichText)
            lab.setOpenExternalLinks(True)
            col.addWidget(lab)
            return lab

        para("<b style='font-size:15px'>IngeCAD</b> "
             f"{tr('Version')} {version}<br>"
             f"{tr('Free 2D CAD in the spirit of classic AutoCAD.')}<br>"
             f"{tr('Created by')} <b>Marco Sumari Tellez</b> — "
             f"{tr('Civil Engineer — Arequipa, Peru')}")
        head = para(f"<b>{tr('With contributions from')}</b>")
        head.setContentsMargins(0, 8, 0, 0)
        self.credits = _Credits(CONTRIBUTORS, self)
        col.addWidget(self.credits)
        para(f"<small>{tr('And thanks to everyone who tries IngeCAD and reports what they find.')}</small>")
        para(f"<small>{tr('Licensed under GPL-3.0-or-later.')} · "
             "<a href='https://github.com/ingelibre/ingecad'>"
             "github.com/ingelibre/ingecad</a> · "
             "<a href='https://ingecad.org'>ingecad.org</a></small>")
        buttons = QDialogButtonBox(QDialogButtonBox.Ok, self)
        buttons.accepted.connect(self.accept)
        col.addWidget(buttons)
