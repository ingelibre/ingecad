# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""External references (issue #33): a colleague's drawing attached to ours.

The host drawing keeps an EMPTY block flagged as an xref with the other
file's path; every INSERT of it means "draw that file's modelspace here".
So: the picture has to show the referenced geometry through the insert's
transformation, the pick index and the snap engine have to see it (and
hand back the INSERT, the only thing the host can select), the file has to
round-trip untouched, and XATTACH / -XREF / the palette manage them.
"""
from __future__ import annotations

import time

import ezdxf
import pytest

from core import xrefs
from core.document import Document


# -- fixtures ------------------------------------------------------------------

def _referenced(tmp_path, name="topo.dxf"):
    """The colleague's drawing: a wall (line) and a manhole (circle), plus a
    block reference of its own, on layer WALLS."""
    doc = ezdxf.new("R2018")
    doc.layers.add("WALLS", color=1)
    msp = doc.modelspace()
    msp.add_line((0, 0), (100, 0), dxfattribs={"layer": "WALLS"})
    msp.add_circle((50, 20), 5, dxfattribs={"layer": "WALLS"})
    block = doc.blocks.new("MH")
    block.add_line((-2, -2), (2, 2))
    msp.add_blockref("MH", (80, 30))
    path = tmp_path / name
    doc.saveas(path)
    return path


def _host(tmp_path, xref_path="topo.dxf", insert=(1000, 500), overlay=False,
          name="topo", own_line=True):
    from ezdxf import xref as ezxref

    doc = ezdxf.new("R2018")
    if own_line:
        doc.modelspace().add_line((0, 0), (10, 10))
    ezxref.attach(doc, block_name=name, filename=xref_path, insert=insert,
                  overlay=overlay)
    path = tmp_path / "host.dxf"
    doc.saveas(path)
    return path


def _wait(qapp, win, timeout_s=30.0):
    t0 = time.monotonic()
    while (win._open_thread is not None or win._regen_worker is not None) \
            and time.monotonic() - t0 < timeout_s:
        qapp.processEvents()
    qapp.processEvents()


def _line_vertices(scene) -> int:
    return len(scene.lines.data)


# -- resolving and loading -------------------------------------------------------

def test_the_saved_path_resolves_like_autocad(tmp_path):
    ref = _referenced(tmp_path)
    host = tmp_path / "host.dxf"
    assert xrefs.resolve_path(host, str(ref)) == ref              # absolute
    assert xrefs.resolve_path(host, "topo.dxf") == ref             # bare name in the folder
    assert xrefs.resolve_path(host, ".\\topo.dxf") == ref          # AutoCAD's relative
    sub = tmp_path / "refs"
    sub.mkdir()
    ref2 = _referenced(sub, "plan.dxf")
    assert xrefs.resolve_path(host, "refs/plan.dxf") == ref2       # relative folder
    assert xrefs.resolve_path(host, "nowhere/topo.dxf") == ref     # the bare name, then
    assert xrefs.resolve_path(host, "nowhere/plan.dxf") is None    # not in the host's folder
    assert xrefs.resolve_path(host, "topo.dwg") == ref             # the other extension
    assert xrefs.resolve_path(host, "missing.dxf") is None
    assert xrefs.resolve_path(host, "") is None


def test_the_referenced_drawing_loads_once_and_reload_sees_an_edit(tmp_path):
    ref = _referenced(tmp_path)
    first = xrefs.load(ref)
    assert first is not None and len(first.doc.modelspace()) == 3
    assert xrefs.load(ref) is first, "loaded twice"
    # the file changes: the cache notices by mtime
    doc = ezdxf.readfile(ref)
    doc.modelspace().add_line((0, 50), (100, 50))
    doc.saveas(ref)
    import os
    os.utime(ref, (time.time() + 5, time.time() + 5))
    second = xrefs.load(ref)
    assert second is not first and len(second.doc.modelspace()) == 4
    # a missing file answers None without raising
    assert xrefs.load(tmp_path / "nope.dxf") is None


def test_references_lists_status_type_and_path(tmp_path):
    _referenced(tmp_path)
    host = _host(tmp_path)
    document = Document.load(host)
    refs = xrefs.references(document)
    assert [r.name for r in refs] == ["topo"]
    assert refs[0].status == "Loaded" and refs[0].path == "topo.dxf"
    assert refs[0].overlay is False and refs[0].inserts == 1
    # not found
    broken = _host(tmp_path, xref_path="gone.dxf", name="gone")
    assert xrefs.references(Document.load(broken))[0].status == "Not found"
    # unloaded
    xrefs.unload(document, ["topo"])
    assert xrefs.references(document)[0].status == "Unloaded"
    xrefs.reload(document, ["topo"])
    assert xrefs.references(document)[0].status == "Loaded"
    assert xrefs.match_names(document, "T*") == ["topo"]
    assert xrefs.match_names(document, "zzz") == []


# -- the picture ---------------------------------------------------------------------

def test_the_regen_draws_the_referenced_geometry_through_the_insert(qapp, tmp_path):
    from render.backend import build_scene

    _referenced(tmp_path)
    document = Document.load(_host(tmp_path, own_line=False))
    scene = build_scene(document, "Model")
    drawn = _line_vertices(scene)
    assert drawn > 0, "the xref drew nothing"
    # placed by the INSERT: the wall (0,0)-(100,0) lands at x = 1000..1100
    xs = scene.lines.data["pos"][:, 0] + scene.origin[0]
    assert xs.min() >= 995 and xs.max() <= 1105, (xs.min(), xs.max())
    # the whole picture is owned by the INSERT's handle (picking, hiding)
    insert = document.doc.modelspace().query("INSERT")[0]
    assert insert.dxf.handle in scene.handle_ranges

    # the inverse: unload it and the picture goes; reload and it is back
    xrefs.unload(document, ["topo"])
    assert _line_vertices(build_scene(document, "Model")) == 0
    xrefs.reload(document, ["topo"])
    assert _line_vertices(build_scene(document, "Model")) == drawn


def test_a_missing_xref_draws_nothing_and_the_drawing_still_opens(qapp, tmp_path):
    from render.backend import build_scene

    document = Document.load(_host(tmp_path, xref_path="gone.dxf", name="gone"))
    scene = build_scene(document, "Model")
    assert _line_vertices(scene) == 2          # the host's own line only


def test_the_hosts_xref_layer_can_switch_the_referenced_geometry_off(qapp, tmp_path):
    from render.backend import build_scene

    _referenced(tmp_path)
    document = Document.load(_host(tmp_path, own_line=False))
    full = _line_vertices(build_scene(document, "Model"))
    layer = document.doc.layers.add("topo|WALLS")
    layer.off()
    less = _line_vertices(build_scene(document, "Model"))
    assert 0 < less < full, "the host's xref|layer did not hide the wall"


# -- round trip --------------------------------------------------------------------

def test_the_xref_definition_round_trips_untouched(tmp_path):
    _referenced(tmp_path)
    host = _host(tmp_path, overlay=True)
    document = Document.load(host)
    block = document.doc.blocks.get("topo")
    before = (block.block.dxf.flags, block.block.dxf.xref_path,
              len(list(block)), block.block_record.dxf.handle)
    # touch ONE unrelated entity, save, reload
    document.doc.modelspace().add_circle((5, 5), 1)
    out = tmp_path / "saved.dxf"
    document.doc.saveas(out)
    back = ezdxf.readfile(out)
    block2 = back.blocks.get("topo")
    assert (block2.block.dxf.flags, block2.block.dxf.xref_path,
            len(list(block2)), block2.block_record.dxf.handle) == before
    assert block2.block_record.is_xref and block2.block.is_xref_overlay
    inserts = back.modelspace().query("INSERT")
    assert len(inserts) == 1 and inserts[0].dxf.name == "topo"



def test_the_xref_survives_save_as_dwg_and_reopen(tmp_path):
    # #66: a DWG title block attached, saved as DWG, reopened -- the xref
    # was gone. LibreDWG's DXF import dropped the BLOCK entity's 70 (xref
    # bits) and 1 (path), which a DWG keeps in the BLOCK_HEADER.
    from formats.dwg_bridge import find_dwg2dxf, find_dxf2dwg, load_dwg

    if find_dxf2dwg() is None or find_dwg2dxf() is None:
        pytest.skip("LibreDWG not available")
    _referenced(tmp_path)
    document = Document.load(_host(tmp_path, overlay=True))
    out = tmp_path / "host.dwg"
    document.save_as(out)
    back = load_dwg(out)
    found = {b.name: b for b in xrefs.xref_blocks(back.doc)}
    assert "topo" in found
    assert found["topo"].block.dxf.xref_path == "topo.dxf"
    assert found["topo"].block.is_xref_overlay
    assert [e.dxf.name for e in back.doc.modelspace().query("INSERT")] == ["topo"]


# -- commands ------------------------------------------------------------------------

def test_attach_and_detach_are_exact_undo_steps(tmp_path):
    from core.commands import History

    ref = _referenced(tmp_path)
    document = Document.new()
    document.path = tmp_path / "host.dxf"
    history = History(document)
    saved = xrefs.saved_path_for(document.path, ref, "Relative")
    assert saved in ("./topo.dxf", ".\\topo.dxf", "topo.dxf") or saved.startswith(".")
    assert xrefs.saved_path_for(document.path, ref, "No path") == "topo.dxf"
    assert xrefs.saved_path_for(document.path, ref, "Full") == str(ref.resolve())

    history.execute(xrefs.AttachXrefCommand("topo", saved, (10, 20), 2.0,
                                            rotation=45.0))
    doc = document.doc
    assert "topo" in doc.blocks and xrefs.is_xref_block(doc.blocks.get("topo"))
    insert = doc.modelspace().query("INSERT")[0]
    assert (insert.dxf.insert.x, insert.dxf.xscale, insert.dxf.rotation) == (10, 2.0, 45.0)
    assert xrefs.references(document)[0].status == "Loaded"
    history.undo()
    assert "topo" not in doc.blocks and not doc.modelspace().query("INSERT")
    history.redo()
    assert "topo" in doc.blocks and len(doc.modelspace().query("INSERT")) == 1

    # a second attach of the same file adds an INSERT, not a definition
    history.execute(xrefs.AttachXrefCommand("topo", saved, (500, 500)))
    assert len(doc.modelspace().query("INSERT")) == 2
    history.undo()
    assert "topo" in doc.blocks and len(doc.modelspace().query("INSERT")) == 1

    history.execute(xrefs.DetachXrefCommand("topo"))
    assert "topo" not in doc.blocks and not doc.modelspace().query("INSERT")
    history.undo()
    assert "topo" in doc.blocks and len(doc.modelspace().query("INSERT")) == 1
    assert xrefs.xref_path_of(doc.blocks.get("topo")) == saved

    history.execute(xrefs.SetXrefPathCommand("topo", "elsewhere/topo.dxf"))
    assert xrefs.xref_path_of(doc.blocks.get("topo")) == "elsewhere/topo.dxf"
    history.undo()
    assert xrefs.xref_path_of(doc.blocks.get("topo")) == saved
    history.execute(xrefs.SetXrefOverlayCommand("topo", True))
    assert xrefs.is_overlay(doc.blocks.get("topo"))
    history.undo()
    assert not xrefs.is_overlay(doc.blocks.get("topo"))


# -- through the window ----------------------------------------------------------------

def _window(qapp, tmp_path):
    from views.main_window import MainWindow

    _referenced(tmp_path)
    host = _host(tmp_path, own_line=False)
    win = MainWindow()
    win.show()
    win.open_path(host)
    _wait(qapp, win)
    while win.tools._warmers:
        qapp.processEvents()
    return win


def test_opening_a_host_shows_the_xref_and_the_palette_lists_it(qapp, tmp_path):
    win = _window(qapp, tmp_path)
    try:
        scene = win.viewport._scene
        assert scene is not None and _line_vertices(scene) > 0
        panel = win._xrefs_panel
        assert panel.table.rowCount() == 1
        assert panel.table.item(0, 0).text() == "topo"
        # XR opens the tab
        win._on_command_submitted("XR")
        assert win._sidebar_tabs.currentWidget() is panel
    finally:
        win.document.dirty = False
        win.close()


def test_snapping_finds_the_referenced_wall_and_picking_selects_the_insert(qapp, tmp_path):
    win = _window(qapp, tmp_path)
    t = win.tools
    try:
        t.start_tool("LINE")
        t.osnap_on = True
        t.osnap_modes = {"END"}
        # the wall's far end (100, 0) sits at (1100, 500) through the insert
        t.on_hover(1100.4, 500.3, 2.0)
        assert t.snap_hit is not None, "no snap on the xref's geometry"
        assert (t.snap_hit.x, t.snap_hit.y) == pytest.approx((1100.0, 500.0))
        t.cancel()
        t._pick_tolerance = 2.0
        t.on_click(1050.0, 500.0)               # the middle of the wall
        assert t.selection, "the xref did not pick"
        picked = t.index.entity(next(iter(t.selection)))
        assert picked.dxftype() == "INSERT" and picked.dxf.name == "topo"
    finally:
        win.document.dirty = False
        win.close()


def test_xattach_through_the_command_line_and_minus_xref_manage_it(qapp, tmp_path):
    from views.main_window import MainWindow

    ref = _referenced(tmp_path)
    win = MainWindow()
    win.show()
    win.new_document()
    win.document.path = tmp_path / "new.dxf"
    t = win.tools
    try:
        t._xref_file_next = str(ref)            # the file dialog's answer
        win._on_command_submitted("XA")
        assert t.active()
        win._on_command_submitted("")           # Attachment
        win._on_command_submitted("")           # Relative
        t.osnap_on = False
        t.on_click(300.0, 200.0)
        win._on_command_submitted("")           # X scale 1
        win._on_command_submitted("")           # Y = X
        win._on_command_submitted("")           # rotation 0
        assert not t.active()
        doc = win.document.doc
        assert "topo" in doc.blocks and xrefs.is_xref_block(doc.blocks.get("topo"))
        insert = doc.modelspace().query("INSERT")[0]
        assert (insert.dxf.insert.x, insert.dxf.insert.y) == (300.0, 200.0)
        info = xrefs.references(win.document)[0]
        assert info.status == "Loaded", info

        said = []
        win.command_line.echo = lambda text, *a, **k: said.append(text)
        win._on_command_submitted("-XR")
        win._on_command_submitted("?")
        assert any("topo" in s for s in said)
        win._on_command_submitted("U")
        win._on_command_submitted("topo")
        assert xrefs.references(win.document)[0].status == "Unloaded"
        win._on_command_submitted("-XREF")
        win._on_command_submitted("R")
        win._on_command_submitted("*")
        assert xrefs.references(win.document)[0].status == "Loaded"
        win._on_command_submitted("-XREF")
        win._on_command_submitted("D")
        win._on_command_submitted("topo")
        assert "topo" not in doc.blocks
        win._cmd_undo()
        assert "topo" in doc.blocks
    finally:
        win.document.dirty = False
        win.close()


def test_a_second_caller_waits_for_a_load_in_flight(tmp_path, monkeypatch):
    """The regen worker preloads while the palette asks from the GUI: the
    second caller must get the drawing, not "Not found" (seen once in five
    runs before the lock; forced here with a slow reader)."""
    import threading

    from core import document as document_mod

    ref = _referenced(tmp_path, "slow.dxf")
    real = document_mod.Document.load.__func__
    started = threading.Event()

    def slow(cls, path):
        started.set()
        time.sleep(0.3)
        return real(cls, path)

    monkeypatch.setattr(document_mod.Document, "load", classmethod(slow))
    first = []
    worker = threading.Thread(target=lambda: first.append(xrefs.load(ref)))
    worker.start()
    started.wait(5)
    second = xrefs.load(ref)
    worker.join(5)
    assert second is not None, "a load in flight read as not found"
    assert first and first[0] is second


def test_insert_browses_for_a_dwg_and_the_block_survives_save(qapp, tmp_path):
    # #70: INSERT answered "No blocks defined" -- no way to insert another
    # drawing (Rafael's DWG title block). Browse... defines it as a block
    # named after the file, and it must still be there after Save as DWG.
    from formats.dwg_bridge import find_dwg2dxf, find_dxf2dwg, load_dwg
    from views.main_window import MainWindow

    if find_dxf2dwg() is None or find_dwg2dxf() is None:
        pytest.skip("LibreDWG not available")
    title = ezdxf.new("R2018")
    title.layers.add("MARCO", color=3)
    title.modelspace().add_lwpolyline(
        [(0, 0), (297, 0), (297, 210), (0, 210)], close=True,
        dxfattribs={"layer": "MARCO"})
    Document(title).save_as(tmp_path / "FormatoA4_horizontal.dwg")

    win = MainWindow()
    win.new_document("m")
    win.maybe_save_changes = lambda: True
    asked = []
    win.tools._ask_choice = lambda prompt, items, default="": asked.append(items) or items[-1]
    win.tools.pick_drawing_file = lambda: str(tmp_path / "FormatoA4_horizontal.dwg")
    try:
        win._invoke_command("INSERT")
        win.tools.on_text("10,20")
        out = tmp_path / "prueba.dwg"
        win.document.save_as(out)
    finally:
        win.document.dirty = False
        win.close()
    assert asked and asked[0][-1] == "Browse..."
    back = load_dwg(out).doc
    block = back.blocks.get("FormatoA4_horizontal")
    assert block is not None and [e.dxftype() for e in block] == ["LWPOLYLINE"]
    assert "MARCO" in back.layers
    inserts = back.modelspace().query("INSERT")
    assert [(i.dxf.name, i.dxf.insert.x, i.dxf.insert.y) for i in inserts] \
        == [("FormatoA4_horizontal", 10, 20)]


def test_the_palette_lists_images_and_pdfs_too_and_detaches_them(qapp, tmp_path):
    # Rafael, review 6 (55:00-58:00): images and PDFs attached fine and
    # survived save, but the External References palette listed only the
    # DWG references; AutoCAD's lists them all.
    from PySide6.QtGui import QColor, QImage

    from core import actions
    from core.i18n import tr
    from views.main_window import MainWindow

    _referenced(tmp_path)
    png = tmp_path / "foto.png"
    img = QImage(8, 4, QImage.Format_RGB32)
    img.fill(QColor("red"))
    img.save(str(png))
    win = MainWindow()
    win.maybe_save_changes = lambda: True
    try:
        win.open_path(_host(tmp_path))
        while win._open_thread is not None:
            qapp.processEvents()
        win.tools._execute(actions.attach_image(str(png), (8, 4), (0, 0), 1.0))
        win.tools._execute(actions.attach_image(str(tmp_path / "plano-p1.png"),
                                                (8, 4), (50, 0), 1.0))
        panel = win._xrefs_panel
        panel.refresh()
        rows = {panel.table.item(r, 0).text(): (panel.table.item(r, 1).text(),
                                                 panel.table.item(r, 2).text())
                for r in range(panel.table.rowCount())}
        assert rows["topo"] == (tr("Loaded"), tr("Attach"))
        assert rows["foto"] == (tr("Loaded"), tr("Raster image"))
        assert rows["plano-p1"] == (tr("Not found"), tr("PDF (as image)"))
        r = next(r for r in range(panel.table.rowCount())
                 if panel.table.item(r, 0).text() == "foto")
        panel.table.selectRow(r)
        assert panel.detach_btn.isEnabled() and not panel.unload_btn.isEnabled()
        panel.detach_btn.click()
        names = [panel.table.item(i, 0).text() for i in range(panel.table.rowCount())]
        assert "foto" not in names
        assert len(win.document.modelspace().query("IMAGE")) == 1
        win._cmd_undo()
        panel.refresh()
        names = [panel.table.item(i, 0).text() for i in range(panel.table.rowCount())]
        assert "foto" in names
        assert len(win.document.modelspace().query("IMAGE")) == 2
    finally:
        win.document.dirty = False
        win.close()


@pytest.mark.parametrize("answer", ["Y", ""])
def test_browsing_to_a_block_already_defined_asks_to_redefine(qapp, tmp_path,
                                                              answer):
    # Rafael's sixth review: he edited his title block and inserted it
    # again; IngeCAD silently inserted the old definition. AutoCAD asks
    # "Redefine it?" -- Yes updates every reference, No (Enter) keeps it.
    from views.main_window import MainWindow

    def title(path, width):
        doc = ezdxf.new("R2018")
        doc.modelspace().add_lwpolyline(
            [(0, 0), (width, 0), (width, 210), (0, 210)], close=True)
        doc.saveas(path)

    path = tmp_path / "Formato.dxf"
    title(path, 297)
    win = MainWindow()
    win.new_document("m")
    win.tools._ask_choice = lambda prompt, items, default="": items[-1]
    win.tools.pick_drawing_file = lambda: str(path)
    try:
        win._invoke_command("INSERT")
        win.tools.on_text("0,0")
        title(path, 420)                       # the file is edited
        win._invoke_command("INSERT")
        assert "Redefine it?" in win.tools.current_prompt \
            or "¿Desea redefinirlo?" in win.tools.current_prompt
        win.tools.on_text(answer)
        win.tools.on_text("500,0")
        block = win.document.doc.blocks.get("Formato")
        widths = [max(x for x, *_ in e.get_points()) for e in block]
        assert widths == ([420] if answer == "Y" else [297])
        assert len(win.document.modelspace().query("INSERT")) == 2
        if answer == "Y":
            win.history.undo()                 # the second insert
            win.history.undo()                 # the redefinition
            block = win.document.doc.blocks.get("Formato")
            assert [max(x for x, *_ in e.get_points()) for e in block] == [297]
    finally:
        win.document.dirty = False
        win.close()
