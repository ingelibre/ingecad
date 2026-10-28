# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""What tools/qa_scenarios.py borrows from the tests, without pytest or
QtTest: the tour also runs inside the Flatpak, which ships neither."""
from __future__ import annotations

import time

import numpy as np


def drive_modal(cls, action, errors, timeout=5.0):
    """Run ``action`` on the modal dialog of class ``cls`` once it is up
    (tests/modal.py)."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    started = time.monotonic()

    def poll():
        modal = QApplication.activeModalWidget()
        if isinstance(modal, cls):
            try:
                action(modal)
            except BaseException as exc:      # noqa: BLE001
                errors.append(exc)
                if modal.isVisible():
                    modal.reject()
        elif time.monotonic() - started < timeout:
            QTimer.singleShot(20, poll)

    QTimer.singleShot(0, poll)


def load_linetypes(dialog, *names, reload=False):
    """Press Load..., pick ``names``, accept (tests/test_linetype_manager_dialog)."""
    from PySide6.QtCore import QItemSelectionModel

    from views.linetype_dialog import LoadLinetypesDialog

    inner: list[BaseException] = []

    def pick(load):
        load.ask_reload = lambda _name: reload
        rows = [load.table.item(r, 0).text() for r in range(load.table.rowCount())]
        model = load.table.selectionModel()
        for name in names:
            model.select(load.table.model().index(rows.index(name), 0),
                         QItemSelectionModel.Select | QItemSelectionModel.Rows)
        load.accept()

    drive_modal(LoadLinetypesDialog, pick, inner)
    dialog.load_button.click()
    if inner:
        raise inner[0]


def annotative_sheet():
    """Rafael's case (tests/test_annotative_viewports._sheet("born")):
    annotative dimensions in red, a 1:1 and a 2:1 viewport."""
    from core import actions
    from core import annotative as A
    from core import layouts as L
    from core.commands import CompositeCommand
    from core.document import Document

    def run(document, command):
        command.do(document)
        return command

    document = Document.new()
    doc = document.doc
    iso = doc.dimstyles.get("ISO-25")
    iso.dxf.dimclrt = 1
    iso.dxf.dimclrd = 3
    iso.dxf.dimclre = 3
    doc.header["$DIMSTYLE"] = "ISO-25"
    iso.dxf.dimtxt = 2.5
    A.set_style_annotative(iso, True)
    dims = []
    for cmd in (actions.dim_linear((-20, -20), (30, -20), (5, -30)),
                actions.dim_aligned((-20, 0), (20, 20), (-25, 10)),
                actions.dim_radius((15, 2), 6.0, (21, 8)),
                actions.dim_diameter((-10, 12), 4.0, (-17, 17))):
        run(document, cmd)
        dims.append(cmd.dim)
    run(document, A.ObjectScaleCommand(dims, "2:1", add=True))
    vp_a = run(document, L.AddViewportCommand(
        "Layout1", (75, 100), (130, 120), (5, -5), 120)).entity
    vp_b = run(document, L.AddViewportCommand(
        "Layout1", (225, 100), (130, 120), (5, -5), 120)).entity
    for vp, ratio, name in ((vp_a, 1.0, "1:1"), (vp_b, 2.0, "2:1")):
        run(document, CompositeCommand("VPSCALE", [
            L.xp_zoom_command(vp, ratio),
            A.SetAnnotationScaleCommand(A.standard_scale(doc, name).name,
                                        viewport=vp)]))
    return document, dims


def red_pixels(document) -> tuple[int, int]:
    """Red (dimension text) pixels of Layout1, left half and right half."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QImage, QPainter

    from formats.pdf_out import build_graphics_scene

    scene = build_graphics_scene(document, "Layout1", ctb="")
    k = 6
    img = QImage(300 * k, 200 * k, QImage.Format_RGB32)
    img.fill(QColor("white"))
    painter = QPainter(img)
    scene.render(painter, QRectF(0, 0, img.width(), img.height()),
                 QRectF(0, 0, 300, 200))
    painter.end()
    arr = np.frombuffer(img.constBits(), np.uint8).reshape(img.height(), img.width(), 4)
    red = (arr[:, :, 2] > 180) & (arr[:, :, 1] < 90) & (arr[:, :, 0] < 90)
    half = img.width() // 2
    return int(red[:, :half].sum()), int(red[:, half:].sum())
