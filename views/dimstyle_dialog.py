# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""AutoCAD's Dimension Style Manager (DIMSTYLE) and the tabbed style editor.

Faithful to the classic dialog (Command Reference pp. 612-641, contract in
docs/reference/dim/autocad-dimstyle-dialog.md): the manager window with the
styles list, live preview, description-vs-current and Set Current / New /
Modify buttons; the Create New Dimension Style dialog (name + Start With);
and the New/Modify editor with the Lines / Symbols and Arrows / Text / Fit /
Primary Units tabs, every control mapped to its DIMVAR. The preview is a real
render: a sample drawing dimensioned with the edited style through the ezdxf
drawing pipeline. Override/Compare, Alternate Units and Tolerances are out of
v0.2 scope (recorded in the reference).
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core import styles as style_ops
from core.i18n import tr

_PREVIEW_BG = QColor(33, 34, 38)

# ACI colors the dialog offers (AutoCAD's short list; the full 255 via number).
_ACI = [("ByBlock", 0), ("ByLayer", 256), ("Red", 1), ("Yellow", 2),
        ("Green", 3), ("Cyan", 4), ("Blue", 5), ("Magenta", 6), ("White", 7)]

# Arrowhead names (ezdxf ARROWS constants; "" = AutoCAD's Closed filled).
_ARROWS = [("Closed filled", ""), ("Closed blank", "CLOSEDBLANK"),
           ("Closed", "CLOSED"), ("Dot", "DOT"),
           ("Architectural tick", "ARCHTICK"), ("Oblique", "OBLIQUE"),
           ("Open 30", "OPEN30"), ("None", "NONE")]

_VERTICAL = [("Centered", 0), ("Above", 1), ("Outside", 2), ("JIS", 3),
             ("Below", 4)]
_HORIZONTAL = [("Centered", 0), ("At ext line 1", 1), ("At ext line 2", 2),
               ("Over ext line 1", 3), ("Over ext line 2", 4)]
_UNIT_FORMATS = [("Scientific", 1), ("Decimal", 2), ("Engineering", 3),
                 ("Architectural", 4), ("Fractional", 5)]
_ANG_FORMATS = [("Decimal degrees", 0), ("Degrees minutes seconds", 1),
                ("Gradians", 2), ("Radians", 3)]


#: The style attributes that name an arrowhead block.
_ARROW_KEYS = ("dimblk", "dimblk1", "dimblk2", "dimldrblk")


def _preview_arrow(value: str):
    """The arrowhead name the sample document can actually draw, or None.

    AutoCAD stores its built-in arrowheads with a leading underscore
    (``_ARCHTICK``) and ezdxf wants them without it, creating the block on
    demand. Handing ezdxf the stored name means "a user block called
    _ARCHTICK", which the sample document does not have — the render then
    raises DXFUndefinedBlockError and the preview came out with the sample
    geometry and no dimensions at all, which is what every architectural
    style in a real drawing looks like. A custom block we cannot draw
    returns None, so the preview falls back to the default arrow instead of
    showing nothing.
    """
    from ezdxf.render.arrows import ARROWS

    if not value:
        return value            # "" is the default closed-filled arrow
    name = ARROWS.arrow_name(str(value))     # "_ARCHTICK" -> "ARCHTICK"
    return name if name in ARROWS else None


#: The sample is 40 drawing units wide; aim for that many text heights across.
_PREVIEW_TEXT_HEIGHTS = 20.0


def _preview_scale(attribs: dict) -> float:
    """How much to scale the 40-unit sample so this style reads.

    Driven by the style's effective text height (``dimtxt`` × ``dimscale``),
    with the arrow size as a fallback for a style that draws no text.
    """
    scale = attribs.get("dimscale") or 1.0
    height = (attribs.get("dimtxt") or 0.0) * scale
    if height <= 0:
        height = (attribs.get("dimasz") or 0.0) * scale * 2.0
    if height <= 0:
        return 1.0
    return (height * _PREVIEW_TEXT_HEIGHTS) / 40.0


def render_dim_preview(attribs: dict, w: int = 300, h: int = 190) -> QPixmap:
    """A real sample render of the style: linear + angular + radius dims."""
    import ezdxf
    from ezdxf.addons.drawing import Frontend, RenderContext
    from ezdxf.addons.drawing.pyqt import PyQtBackend
    from PySide6.QtWidgets import QGraphicsScene

    pm = QPixmap(w, h)
    pm.fill(_PREVIEW_BG)
    try:
        doc = ezdxf.new(setup=False)
        txsty = attribs.get("dimtxsty") or "Standard"
        if txsty not in doc.styles:
            try:
                doc.styles.add(txsty, font="txt")
            except Exception:
                txsty = "Standard"
        style = doc.dimstyles.new("PREV")
        for key, value in attribs.items():
            if key in ("name", "handle", "owner") or value is None:
                continue
            if key in _ARROW_KEYS:
                value = _preview_arrow(value)
                if value is None:
                    continue
            try:
                style.dxf.set(key, value)
            except Exception:
                pass
        msp = doc.modelspace()
        white = {"color": 7}
        # Size the sample to the style, not the other way round. A style meant
        # for a drawing in metres carries dimtxt = 0.1, and against a sample
        # 40 units wide its text is a quarter of one per cent of the preview:
        # invisible. Twenty text heights across is what makes every style
        # legible while keeping its own text/arrow proportions intact.
        s = _preview_scale(attribs)
        p = lambda x, y: (x * s, y * s)          # noqa: E731 - local shorthand
        msp.add_line(p(0, 0), p(40, 0), dxfattribs=white)
        msp.add_line(p(0, 0), p(14, 18), dxfattribs=white)
        msp.add_circle(p(58, 9), 8 * s, dxfattribs=white)
        for build in (
            lambda: msp.add_linear_dim(base=p(20, -10), p1=p(0, 0), p2=p(40, 0),
                                       dimstyle="PREV"),
            lambda: msp.add_angular_dim_3p(base=p(17, 7), center=p(0, 0),
                                           p1=p(16, 0), p2=p(11, 14),
                                           dimstyle="PREV"),
            lambda: msp.add_radius_dim(center=p(58, 9), radius=8 * s, angle=35,
                                       dimstyle="PREV"),
        ):
            try:
                build().render()
            except Exception:
                pass
        scene = QGraphicsScene()
        backend = PyQtBackend(scene)
        Frontend(RenderContext(doc), backend).draw_layout(msp, finalize=False)
        backend.finalize()
        source = scene.itemsBoundingRect()
        if source.isEmpty():
            return pm
        margin = 8
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.Antialiasing)
        # DXF is y-up, the pixmap y-down: flip the painter and hand render()
        # a target rect expressed in the flipped coordinate system (the same
        # idiom the plot pipeline uses).
        painter.translate(0.0, h)
        painter.scale(1.0, -1.0)
        scene.render(painter,
                     QRectF(margin, margin, w - 2 * margin, h - 2 * margin),
                     source, Qt.KeepAspectRatio)
        painter.end()
    except Exception:
        pass
    return pm


def _combo(pairs, value, translate: bool = True) -> QComboBox:
    box = QComboBox()
    for label, data in pairs:
        box.addItem(tr(label) if translate else label, data)
    idx = next((i for i in range(box.count())
                if box.itemData(i) == value), 0)
    box.setCurrentIndex(idx)
    return box


def _dspin(value, lo=0.0, hi=1e6, dec=3, step=0.1) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(dec)
    s.setSingleStep(step)
    s.setValue(float(value))
    return s


class DimStyleEditorDialog(QDialog):
    """The New/Modify Dimension Style dialog: 5 tabs + live preview."""

    def __init__(self, parent, title: str, attribs: dict,
                 text_styles: list[str]) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self._attribs = dict(attribs)
        a = self._attribs.get

        root = QVBoxLayout(self)
        body = QHBoxLayout()
        root.addLayout(body)
        self.tabs = QTabWidget(self)
        body.addWidget(self.tabs, 1)

        side = QVBoxLayout()
        side.addWidget(QLabel(tr("Preview")))
        self.preview = QLabel(self)
        self.preview.setFixedSize(300, 190)
        self.preview.setStyleSheet("border: 1px solid #444;")
        side.addWidget(self.preview)
        side.addStretch(1)
        body.addLayout(side)

        # ---- Lines tab ------------------------------------------------------
        lines = QWidget()
        lv = QVBoxLayout(lines)
        dim_group = QGroupBox(tr("Dimension lines"))
        f = QFormLayout(dim_group)
        self.dimclrd = _combo(_ACI, a("dimclrd", 0))
        f.addRow(tr("Color"), self.dimclrd)
        self.dimdle = _dspin(a("dimdle", 0.0))
        f.addRow(tr("Extend beyond ticks"), self.dimdle)
        self.dimdli = _dspin(a("dimdli", 3.75))
        f.addRow(tr("Baseline spacing"), self.dimdli)
        sup = QHBoxLayout()
        self.dimsd1 = QCheckBox(tr("Dim line 1"))
        self.dimsd1.setChecked(bool(a("dimsd1", 0)))
        self.dimsd2 = QCheckBox(tr("Dim line 2"))
        self.dimsd2.setChecked(bool(a("dimsd2", 0)))
        sup.addWidget(self.dimsd1)
        sup.addWidget(self.dimsd2)
        f.addRow(tr("Suppress"), sup)
        lv.addWidget(dim_group)

        ext_group = QGroupBox(tr("Extension lines"))
        f = QFormLayout(ext_group)
        self.dimclre = _combo(_ACI, a("dimclre", 0))
        f.addRow(tr("Color"), self.dimclre)
        self.dimexe = _dspin(a("dimexe", 1.25))
        f.addRow(tr("Extend beyond dim lines"), self.dimexe)
        self.dimexo = _dspin(a("dimexo", 0.625))
        f.addRow(tr("Offset from origin"), self.dimexo)
        sup = QHBoxLayout()
        self.dimse1 = QCheckBox(tr("Ext line 1"))
        self.dimse1.setChecked(bool(a("dimse1", 0)))
        self.dimse2 = QCheckBox(tr("Ext line 2"))
        self.dimse2.setChecked(bool(a("dimse2", 0)))
        sup.addWidget(self.dimse1)
        sup.addWidget(self.dimse2)
        f.addRow(tr("Suppress"), sup)
        self.dimfxlon = QCheckBox(tr("Fixed length extension lines"))
        self.dimfxlon.setChecked(bool(a("dimfxlon", 0)))
        f.addRow(self.dimfxlon)
        self.dimfxl = _dspin(a("dimfxl", 1.0))
        f.addRow(tr("Length"), self.dimfxl)
        lv.addWidget(ext_group)
        lv.addStretch(1)
        self.tabs.addTab(lines, tr("Lines"))

        # ---- Symbols and Arrows tab ----------------------------------------
        sym = QWidget()
        sv = QVBoxLayout(sym)
        arr_group = QGroupBox(tr("Arrowheads"))
        f = QFormLayout(arr_group)
        blk1 = a("dimblk1", a("dimblk", ""))
        blk2 = a("dimblk2", a("dimblk", ""))
        self.dimblk1 = _combo(_ARROWS, blk1)
        f.addRow(tr("First"), self.dimblk1)
        self.dimblk2 = _combo(_ARROWS, blk2)
        f.addRow(tr("Second"), self.dimblk2)
        self.dimldrblk = _combo(_ARROWS, a("dimldrblk", ""))
        f.addRow(tr("Leader"), self.dimldrblk)
        self.dimasz = _dspin(a("dimasz", 2.5))
        f.addRow(tr("Arrow size"), self.dimasz)
        # Official behavior: changing First syncs Second.
        self.dimblk1.currentIndexChanged.connect(
            lambda i: self.dimblk2.setCurrentIndex(i))
        sv.addWidget(arr_group)

        cen_group = QGroupBox(tr("Center marks"))
        f = QFormLayout(cen_group)
        dimcen = float(a("dimcen", 2.5))
        mode = "none" if dimcen == 0 else ("line" if dimcen < 0 else "mark")
        self.cen_mode = _combo([("None", "none"), ("Mark", "mark"),
                                ("Line", "line")], mode)
        f.addRow(tr("Type"), self.cen_mode)
        self.cen_size = _dspin(abs(dimcen) or 2.5)
        f.addRow(tr("Size"), self.cen_size)
        sv.addWidget(cen_group)

        arc_group = QGroupBox(tr("Arc length symbol"))
        f = QFormLayout(arc_group)
        self.dimarcsym = _combo(
            [("Preceding dimension text", 0), ("Above dimension text", 1),
             ("None", 2)], int(a("dimarcsym", 0)))
        f.addRow(self.dimarcsym)
        sv.addWidget(arc_group)
        sv.addStretch(1)
        self.tabs.addTab(sym, tr("Symbols and Arrows"))

        # ---- Text tab -------------------------------------------------------
        text = QWidget()
        tv = QVBoxLayout(text)
        app_group = QGroupBox(tr("Text appearance"))
        f = QFormLayout(app_group)
        self.dimtxsty = QComboBox()
        self.dimtxsty.addItems(text_styles or ["Standard"])
        cur = a("dimtxsty", "Standard")
        if cur and self.dimtxsty.findText(cur) < 0:
            self.dimtxsty.insertItem(0, cur)
        self.dimtxsty.setCurrentText(cur or "Standard")
        f.addRow(tr("Text style"), self.dimtxsty)
        self.dimclrt = _combo(_ACI, a("dimclrt", 0))
        f.addRow(tr("Text color"), self.dimclrt)
        self.dimtxt = _dspin(a("dimtxt", 2.5), lo=0.01)
        f.addRow(tr("Text height"), self.dimtxt)
        gap = float(a("dimgap", 0.625))
        self.frame_text = QCheckBox(tr("Draw frame around text"))
        self.frame_text.setChecked(gap < 0)
        f.addRow(self.frame_text)
        tv.addWidget(app_group)

        place_group = QGroupBox(tr("Text placement"))
        f = QFormLayout(place_group)
        self.dimtad = _combo(_VERTICAL, int(a("dimtad", 0)))
        f.addRow(tr("Vertical"), self.dimtad)
        self.dimjust = _combo(_HORIZONTAL, int(a("dimjust", 0)))
        f.addRow(tr("Horizontal"), self.dimjust)
        self.dimgap = _dspin(abs(gap))
        f.addRow(tr("Offset from dim line"), self.dimgap)
        tv.addWidget(place_group)

        align_group = QGroupBox(tr("Text alignment"))
        f = QFormLayout(align_group)
        tih, toh = int(a("dimtih", 0)), int(a("dimtoh", 0))
        mode = "h" if tih else ("iso" if toh else "aligned")
        self.text_align = _combo(
            [("Horizontal", "h"), ("Aligned with dimension line", "aligned"),
             ("ISO standard", "iso")], mode)
        f.addRow(self.text_align)
        tv.addWidget(align_group)
        tv.addStretch(1)
        self.tabs.addTab(text, tr("Text"))

        # ---- Fit tab --------------------------------------------------------
        fit = QWidget()
        fv = QVBoxLayout(fit)
        fit_group = QGroupBox(tr("Fit options"))
        f = QFormLayout(fit_group)
        self.dimatfit = _combo(
            [("Either text or arrows (best fit)", 3), ("Arrows", 1),
             ("Text", 2), ("Both text and arrows", 0)], int(a("dimatfit", 3)))
        f.addRow(self.dimatfit)
        self.dimtix = QCheckBox(tr("Always keep text between ext lines"))
        self.dimtix.setChecked(bool(a("dimtix", 0)))
        f.addRow(self.dimtix)
        self.dimsoxd = QCheckBox(
            tr("Suppress arrows if they don't fit inside extension lines"))
        self.dimsoxd.setChecked(bool(a("dimsoxd", 0)))
        f.addRow(self.dimsoxd)
        fv.addWidget(fit_group)

        move_group = QGroupBox(tr("Text placement when moved"))
        f = QFormLayout(move_group)
        self.dimtmove = _combo(
            [("Beside the dimension line", 0),
             ("Over the dimension line, with leader", 1),
             ("Over the dimension line, without leader", 2)],
            int(a("dimtmove", 0)))
        f.addRow(self.dimtmove)
        fv.addWidget(move_group)

        scale_group = QGroupBox(tr("Scale for dimension features"))
        f = QFormLayout(scale_group)
        self.dimscale = _dspin(a("dimscale", 1.0) or 1.0, lo=0.001)
        f.addRow(tr("Use overall scale of"), self.dimscale)
        fv.addWidget(scale_group)

        fine_group = QGroupBox(tr("Fine tuning"))
        f = QFormLayout(fine_group)
        self.dimupt = QCheckBox(tr("Place text manually"))
        self.dimupt.setChecked(bool(a("dimupt", 0)))
        f.addRow(self.dimupt)
        self.dimtofl = QCheckBox(tr("Draw dim line between ext lines"))
        self.dimtofl.setChecked(bool(a("dimtofl", 0)))
        f.addRow(self.dimtofl)
        fv.addWidget(fine_group)
        fv.addStretch(1)
        self.tabs.addTab(fit, tr("Fit"))

        # ---- Primary Units tab ---------------------------------------------
        units = QWidget()
        uv = QVBoxLayout(units)
        lin_group = QGroupBox(tr("Linear dimensions"))
        f = QFormLayout(lin_group)
        self.dimlunit = _combo(_UNIT_FORMATS, int(a("dimlunit", 2)))
        f.addRow(tr("Unit format"), self.dimlunit)
        self.dimdec = QSpinBox()
        self.dimdec.setRange(0, 8)
        self.dimdec.setValue(int(a("dimdec", 2)))
        f.addRow(tr("Precision"), self.dimdec)
        dsep = a("dimdsep", ord(","))
        dsep = chr(dsep) if isinstance(dsep, int) and dsep else str(dsep or ",")
        self.dimdsep = _combo([(",", ","), (".", ".")], dsep, translate=False)
        f.addRow(tr("Decimal separator"), self.dimdsep)
        self.dimrnd = _dspin(a("dimrnd", 0.0))
        f.addRow(tr("Round off"), self.dimrnd)
        post = str(a("dimpost", "") or "")
        prefix, _, suffix = post.partition("<>")
        if "<>" not in post:
            prefix, suffix = "", post
        self.prefix = QLineEdit(prefix)
        f.addRow(tr("Prefix"), self.prefix)
        self.suffix = QLineEdit(suffix)
        f.addRow(tr("Suffix"), self.suffix)
        self.dimlfac = _dspin(a("dimlfac", 1.0) or 1.0, lo=0.0001)
        f.addRow(tr("Measurement scale factor"), self.dimlfac)
        zin = int(a("dimzin", 8))
        zsup = QHBoxLayout()
        self.zin_lead = QCheckBox(tr("Leading"))
        self.zin_lead.setChecked(bool(zin & 4))
        self.zin_trail = QCheckBox(tr("Trailing"))
        self.zin_trail.setChecked(bool(zin & 8))
        zsup.addWidget(self.zin_lead)
        zsup.addWidget(self.zin_trail)
        f.addRow(tr("Zero suppression"), zsup)
        uv.addWidget(lin_group)

        ang_group = QGroupBox(tr("Angular dimensions"))
        f = QFormLayout(ang_group)
        self.dimaunit = _combo(_ANG_FORMATS, int(a("dimaunit", 0)))
        f.addRow(tr("Units format"), self.dimaunit)
        self.dimadec = QSpinBox()
        self.dimadec.setRange(0, 8)
        self.dimadec.setValue(max(0, int(a("dimadec", 0))))
        f.addRow(tr("Precision"), self.dimadec)
        azin = int(a("dimazin", 0))
        zsup = QHBoxLayout()
        self.azin_lead = QCheckBox(tr("Leading"))
        self.azin_lead.setChecked(bool(azin & 1))
        self.azin_trail = QCheckBox(tr("Trailing"))
        self.azin_trail.setChecked(bool(azin & 2))
        zsup.addWidget(self.azin_lead)
        zsup.addWidget(self.azin_trail)
        f.addRow(tr("Zero suppression"), zsup)
        uv.addWidget(ang_group)
        uv.addStretch(1)
        self.tabs.addTab(units, tr("Primary Units"))

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        # Live preview, debounced.
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._render_preview)
        for widget in self.findChildren(QWidget):
            for signal in ("currentIndexChanged", "valueChanged",
                           "toggled", "textChanged"):
                sig = getattr(widget, signal, None)
                if sig is not None and widget is not self.tabs:
                    try:
                        sig.connect(lambda *_: self._timer.start())
                    except Exception:
                        pass
        self._render_preview()

    def _render_preview(self) -> None:
        self.preview.setPixmap(render_dim_preview(self.result_props()))

    def result_props(self) -> dict:
        """The DIMVARS the dialog controls, as one dict."""
        gap = self.dimgap.value()
        cen_mode = self.cen_mode.currentData()
        cen = 0.0 if cen_mode == "none" else self.cen_size.value()
        if cen_mode == "line":
            cen = -cen
        align = self.text_align.currentData()
        post = ""
        if self.prefix.text() or self.suffix.text():
            post = f"{self.prefix.text()}<>{self.suffix.text()}"
        return {
            # Lines
            "dimclrd": self.dimclrd.currentData(),
            "dimdle": self.dimdle.value(),
            "dimdli": self.dimdli.value(),
            "dimsd1": int(self.dimsd1.isChecked()),
            "dimsd2": int(self.dimsd2.isChecked()),
            "dimclre": self.dimclre.currentData(),
            "dimexe": self.dimexe.value(),
            "dimexo": self.dimexo.value(),
            "dimse1": int(self.dimse1.isChecked()),
            "dimse2": int(self.dimse2.isChecked()),
            "dimfxlon": int(self.dimfxlon.isChecked()),
            "dimfxl": self.dimfxl.value(),
            # Symbols and arrows
            "dimsah": 1,
            "dimblk1": self.dimblk1.currentData(),
            "dimblk2": self.dimblk2.currentData(),
            "dimldrblk": self.dimldrblk.currentData(),
            "dimasz": self.dimasz.value(),
            "dimcen": cen,
            "dimarcsym": self.dimarcsym.currentData(),
            # Text
            "dimtxsty": self.dimtxsty.currentText(),
            "dimclrt": self.dimclrt.currentData(),
            "dimtxt": self.dimtxt.value(),
            "dimtad": self.dimtad.currentData(),
            "dimjust": self.dimjust.currentData(),
            "dimgap": -gap if self.frame_text.isChecked() else gap,
            "dimtih": 1 if align == "h" else 0,
            "dimtoh": 1 if align in ("h", "iso") else 0,
            # Fit
            "dimatfit": self.dimatfit.currentData(),
            "dimtix": int(self.dimtix.isChecked()),
            "dimsoxd": int(self.dimsoxd.isChecked()),
            "dimtmove": self.dimtmove.currentData(),
            "dimscale": self.dimscale.value(),
            "dimupt": int(self.dimupt.isChecked()),
            "dimtofl": int(self.dimtofl.isChecked()),
            # Primary units
            "dimlunit": self.dimlunit.currentData(),
            "dimdec": self.dimdec.value(),
            "dimdsep": ord(self.dimdsep.currentData()),
            "dimrnd": self.dimrnd.value(),
            "dimpost": post,
            "dimlfac": self.dimlfac.value(),
            "dimzin": (4 if self.zin_lead.isChecked() else 0)
                      | (8 if self.zin_trail.isChecked() else 0),
            "dimaunit": self.dimaunit.currentData(),
            "dimadec": self.dimadec.value(),
            "dimazin": (1 if self.azin_lead.isChecked() else 0)
                       | (2 if self.azin_trail.isChecked() else 0),
        }


class CreateNewDimStyleDialog(QDialog):
    """AutoCAD's Create New Dimension Style dialog (name + Start With)."""

    def __init__(self, parent, styles: list[str], start_with: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Create New Dimension Style"))
        form = QFormLayout(self)
        self.name = QLineEdit(tr("Copy of {name}", name=start_with))
        form.addRow(tr("New style name"), self.name)
        self.start_with = QComboBox()
        self.start_with.addItems(styles)
        self.start_with.setCurrentText(start_with)
        form.addRow(tr("Start with"), self.start_with)
        buttons = QDialogButtonBox(self)
        cont = buttons.addButton(tr("Continue"), QDialogButtonBox.AcceptRole)
        buttons.addButton(QDialogButtonBox.Cancel)
        cont.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


class DimStyleManagerDialog(QDialog):
    """The Dimension Style Manager window (what DIMSTYLE opens)."""

    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self.setWindowTitle(tr("Dimension Style Manager"))
        root = QVBoxLayout(self)
        self.current_label = QLabel(self)
        root.addWidget(self.current_label)

        body = QHBoxLayout()
        root.addLayout(body)

        left = QVBoxLayout()
        left.addWidget(QLabel(tr("Styles:")))
        self.list = QListWidget(self)
        self.list.setMinimumSize(170, 240)
        self.list.currentItemChanged.connect(lambda *_: self._on_select())
        self.list.itemDoubleClicked.connect(lambda *_: self._set_current())
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        left.addWidget(self.list, 1)
        left.addWidget(QLabel(tr("List:")))
        self.filter = QComboBox(self)
        self.filter.addItem(tr("All styles"), "all")
        self.filter.addItem(tr("Styles in use"), "used")
        self.filter.currentIndexChanged.connect(lambda *_: self.refresh())
        left.addWidget(self.filter)
        body.addLayout(left)

        mid = QVBoxLayout()
        self.preview_label = QLabel(self)
        mid.addWidget(self.preview_label)
        self.preview = QLabel(self)
        self.preview.setFixedSize(300, 190)
        self.preview.setStyleSheet("border: 1px solid #444;")
        mid.addWidget(self.preview)
        mid.addWidget(QLabel(tr("Description")))
        # A read-only text box, not a wrapped label: a label's height depends
        # on its width, which the layout cannot satisfy at the dialog's own
        # minimum size — the long descriptions real styles produce pushed it
        # over the preview. This one scrolls instead of growing.
        self.description = QTextEdit(self)
        self.description.setReadOnly(True)
        self.description.setFixedHeight(96)
        self.description.setStyleSheet(
            "border: 1px solid #444; padding: 3px; color: #c8c8c8;")
        mid.addWidget(self.description)
        mid.addStretch(1)
        body.addLayout(mid, 1)

        btns = QVBoxLayout()
        self.set_current_btn = QPushButton(tr("Set Current"), self)
        self.set_current_btn.clicked.connect(self._set_current)
        btns.addWidget(self.set_current_btn)
        new_btn = QPushButton(tr("New..."), self)
        new_btn.clicked.connect(self._new)
        btns.addWidget(new_btn)
        self.modify_btn = QPushButton(tr("Modify..."), self)
        self.modify_btn.clicked.connect(self._modify)
        btns.addWidget(self.modify_btn)
        btns.addStretch(1)
        body.addLayout(btns)

        close = QDialogButtonBox(QDialogButtonBox.Close, self)
        close.rejected.connect(self.reject)
        close.clicked.connect(lambda *_: self.accept())
        root.addWidget(close)
        self.refresh()

    # -- data helpers ----------------------------------------------------------
    @property
    def document(self):
        return self.window.document

    def _styles_in_use(self) -> set[str]:
        used = set()
        for e in self.document.doc.entitydb.values():
            if e.is_alive and e.dxftype() in ("DIMENSION", "ARC_DIMENSION"):
                used.add(e.dxf.get("dimstyle", ""))
        return used

    def selected(self) -> str | None:
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def refresh(self, select: str | None = None) -> None:
        if self.document is None:
            return
        current = style_ops.current_dim_style(self.document)
        self.current_label.setText(
            tr("Current dimension style: {name}", name=current))
        keep = select or self.selected() or current
        names = style_ops.dim_style_names(self.document)
        if self.filter.currentData() == "used":
            used = self._styles_in_use()
            names = [n for n in names if n in used or n == current]
        self.list.blockSignals(True)
        self.list.clear()
        for name in names:
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, name)
            if name == current:
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            self.list.addItem(item)
            if name == keep:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self._on_select()

    def _on_select(self) -> None:
        name = self.selected()
        if name is None:
            self.preview.clear()
            return
        self.preview_label.setText(tr("Preview of: {name}", name=name))
        attribs = style_ops.dim_style_attribs(self.document, name)
        self.preview.setPixmap(render_dim_preview(attribs))
        current = style_ops.current_dim_style(self.document)
        if name == current:
            self.description.setText(name)
        else:
            cur = style_ops.dim_style_attribs(self.document, current)
            diffs = [f"{k} = {v}" for k, v in sorted(attribs.items())
                     if cur.get(k) != v]
            text = current + (" + " + ", ".join(diffs[:12]) if diffs else "")
            self.description.setText(text)

    # -- actions ---------------------------------------------------------------
    def _set_current(self) -> None:
        name = self.selected()
        if name and name != style_ops.current_dim_style(self.document):
            self.window.history.execute(
                style_ops.SetCurrentDimStyleCommand(name))
            self.window.after_style_change()
        self.refresh()

    def _new(self) -> None:
        start = self.selected() or style_ops.current_dim_style(self.document)
        styles = style_ops.dim_style_names(self.document)
        dlg = CreateNewDimStyleDialog(self, styles, start)
        if not dlg.exec():
            return
        name = dlg.name.text().strip()
        if not name:
            return
        if name in styles:
            QMessageBox.warning(self, tr("Dimension Style Manager"),
                                tr("A style named {name} already exists.",
                                   name=name))
            return
        attribs = style_ops.dim_style_attribs(
            self.document, dlg.start_with.currentText())
        editor = DimStyleEditorDialog(
            self, tr("New Dimension Style: {name}", name=name), attribs,
            style_ops.text_style_names(self.document))
        if not editor.exec():
            return
        attribs.update(editor.result_props())
        self.window.history.execute(
            style_ops.NewDimStyleCommand(name, attribs))
        self.window.after_style_change()
        self.refresh(select=name)

    def _modify(self) -> None:
        name = self.selected()
        if name is None:
            return
        attribs = style_ops.dim_style_attribs(self.document, name)
        editor = DimStyleEditorDialog(
            self, tr("Modify Dimension Style: {name}", name=name), attribs,
            style_ops.text_style_names(self.document))
        if not editor.exec():
            return
        props = editor.result_props()
        changed = {k: v for k, v in props.items() if attribs.get(k) != v}
        if changed:
            self.window.history.execute(
                style_ops.SetDimStylePropsCommand(name, changed))
            self.window.after_style_change()
        self.refresh()

    def _rename(self) -> None:
        name = self.selected()
        if name is None or name == "Standard":
            return
        new, ok = QInputDialog.getText(
            self, tr("Rename style"), tr("Name:"), text=name)
        new = new.strip()
        if not ok or not new or new == name:
            return
        if new in style_ops.dim_style_names(self.document):
            QMessageBox.warning(self, tr("Dimension Style Manager"),
                                tr("A style named {name} already exists.",
                                   name=new))
            return
        self.window.history.execute(style_ops.RenameDimStyleCommand(name, new))
        self.window.after_style_change()
        self.refresh(select=new)

    def _delete(self) -> None:
        name = self.selected()
        if name is None or name == "Standard":
            return
        if name == style_ops.current_dim_style(self.document):
            QMessageBox.warning(self, tr("Dimension Style Manager"),
                                tr("Cannot delete the current style."))
            return
        if name in self._styles_in_use():
            QMessageBox.warning(self, tr("Dimension Style Manager"),
                                tr("Cannot delete a style that is in use."))
            return
        self.window.history.execute(style_ops.DeleteDimStyleCommand(name))
        self.window.after_style_change()
        self.refresh()

    def _menu(self, pos) -> None:
        if self.selected() is None:
            return
        menu = QMenu(self)
        menu.addAction(tr("Set current"), self._set_current)
        menu.addAction(tr("Rename"), self._rename)
        menu.addAction(tr("Delete"), self._delete)
        menu.exec(self.list.mapToGlobal(pos))
