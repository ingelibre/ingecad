# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""TABLE (plain-geometry grid) and the PDF page rasterizer path."""
from __future__ import annotations

import pytest

from core import tables
from core.commands import History
from core.document import Document


def test_a_table_is_lines_and_centered_texts_in_one_undo_step():
    doc = Document.new()
    history = History(doc)
    cmd = tables.insert_table((100.0, 200.0), cols=3, col_width=40.0,
                              data_rows=2, row_height=8.0, text_height=2.5,
                              title="CUADRO", headers=["P", "ESTE", "NORTE"],
                              data=[["1", "100.00", "200.00"]])
    history.execute(cmd)
    msp = doc.modelspace()
    lines = msp.query("LINE")
    texts = msp.query("TEXT")
    # 4 rows (title+header+2 data) -> 5 horizontals; 2 borders + 2 internals
    assert len(lines) == 5 + 4
    # title + 3 headers + 3 filled cells
    assert len(texts) == 1 + 3 + 3
    # the title is centered on the full width, first row band
    title = next(t for t in texts if t.dxf.text == "CUADRO")
    assert title.dxf.align_point.x == pytest.approx(100.0 + 60.0)
    assert title.dxf.align_point.y == pytest.approx(200.0 - 4.0)
    # internal verticals stop below the title band
    internal = [ln for ln in lines
                if ln.dxf.start.x == ln.dxf.end.x
                and ln.dxf.start.x not in (100.0, 220.0)]
    assert all(max(ln.dxf.start.y, ln.dxf.end.y) == pytest.approx(192.0)
               for ln in internal)
    history.undo()
    assert len(msp.query("LINE")) == 0 and len(msp.query("TEXT")) == 0


def test_a_table_without_title_or_headers_is_a_bare_grid():
    doc = Document.new()
    History(doc).execute(tables.insert_table(
        (0.0, 0.0), cols=2, col_width=10.0, data_rows=3, row_height=5.0,
        text_height=2.5))
    msp = doc.modelspace()
    assert len(msp.query("TEXT")) == 0
    assert len(msp.query("LINE")) == 4 + 3   # 4 horizontals, 3 verticals


def test_qtpdf_rasterizes_a_page(qapp, tmp_path):
    """The PDFATTACH substrate: page -> pixels at 150 dpi."""
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QPageSize, QPainter
    from PySide6.QtPdf import QPdfDocument

    pdf_path = tmp_path / "plano.pdf"
    from PySide6.QtGui import QPdfWriter

    writer = QPdfWriter(str(pdf_path))
    writer.setPageSize(QPageSize(QPageSize.A4))
    painter = QPainter(writer)
    painter.drawText(100, 100, "PLANO")
    painter.end()

    pdf = QPdfDocument()
    pdf.load(str(pdf_path))
    assert pdf.pageCount() == 1
    points = pdf.pagePointSize(0)
    px = QSize(round(points.width() / 72.0 * 150),
               round(points.height() / 72.0 * 150))
    image = pdf.render(0, px)
    assert image.width() == px.width() and not image.isNull()
