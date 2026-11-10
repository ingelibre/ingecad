# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A drawing saved as DWG opens in the classic CAD without being recovered.

An R2000 file states the version of some object classes in XDATA on each
object; later formats do not. A drawing that came from one of those and went
out as R2000 without the XDATA had its visual styles and multileader styles
"improperly read" (error 67): the classic CAD offered to recover the drawing
and threw those objects away. Judged in the classic CAD itself (2026-11-09):
either class alone was enough to refuse the file."""
import pytest

from formats.dwg_bridge import find_dxf2dwg

from core.document import Document
from core.encoding import write_dwg_intermediate
from formats.dwg_bridge import load_dwg


def _versioned(doc):
    """{type: [xdata of each object]} for the two classes."""
    out = {"VISUALSTYLE": [], "MLEADERSTYLE": []}
    for entity in doc.objects:
        if entity.dxftype() in out:
            out[entity.dxftype()].append(
                {app: [(t.code, t.value) for t in tags[1:]]
                 for app, tags in (entity.xdata.data if entity.xdata
                                   else {}).items()})
    return out


def _written(path):
    """The same, read from the DXF as text: (code, value) pairs per object."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    pairs = [(int(lines[i]), lines[i + 1].strip())
             for i in range(0, len(lines) - 1, 2)]
    out = {"VISUALSTYLE": [], "MLEADERSTYLE": []}
    current = None
    for code, value in pairs:
        if code == 0:
            current = None
            if value in out:
                current = {}
                out[value].append(current)
            app = None
        elif current is not None and code == 1001:
            app = value
            current[app] = []
        elif current is not None and code >= 1000 and app:
            current[app].append((code, int(value) if code == 1070 else value))
    return out


def _drawing_from_a_later_format():
    doc = Document.new()
    plain = _versioned(doc.doc)
    # as a drawing of a later format comes: the objects, and no version XDATA
    assert plain["MLEADERSTYLE"] and all(not x for x in plain["MLEADERSTYLE"])
    if not plain["VISUALSTYLE"]:
        style = doc.doc.objects.new_entity(
            "VISUALSTYLE", {"owner": doc.doc.rootdict.dxf.handle})
        assert style.dxftype() == "VISUALSTYLE"
    return doc


def test_the_intermediate_states_the_class_versions_and_the_drawing_is_as_before(
        tmp_path):
    doc = _drawing_from_a_later_format()
    assert "ACAD_MLEADERVER" not in doc.doc.appids

    out = tmp_path / "inter.dxf"
    write_dwg_intermediate(doc.doc, out)

    written = _written(out)
    assert written["VISUALSTYLE"] and all(
        x.get("ACAD") == [(1000, "AcDbSavedByObjectVersion"), (1070, 0)]
        for x in written["VISUALSTYLE"])
    assert all(x.get("ACAD_MLEADERVER") == [(1070, 2)]
               for x in written["MLEADERSTYLE"])
    # the caller's drawing did not notice
    after = _versioned(doc.doc)
    assert all(not x for kind in after.values() for x in kind)
    assert "ACAD_MLEADERVER" not in doc.doc.appids


def test_a_version_already_stated_is_left_as_it_is(tmp_path):
    doc = _drawing_from_a_later_format()
    style = next(e for e in doc.doc.objects if e.dxftype() == "MLEADERSTYLE")
    doc.doc.appids.new("ACAD_MLEADERVER")
    style.set_xdata("ACAD_MLEADERVER", [(1070, 1)])

    out = tmp_path / "inter.dxf"
    write_dwg_intermediate(doc.doc, out)

    assert {"ACAD_MLEADERVER": [(1070, 1)]} in _written(out)["MLEADERSTYLE"]
    assert style.get_xdata("ACAD_MLEADERVER")[0].value == 1   # and stays


@pytest.mark.skipif(find_dxf2dwg() is None, reason="LibreDWG not available")
def test_the_saved_dwg_carries_them(tmp_path):
    doc = _drawing_from_a_later_format()
    doc.modelspace().add_line((0, 0), (10, 0))
    path = tmp_path / "saved.dwg"
    engine, _warnings = doc.save_as(path)
    if engine != "libredwg":
        pytest.skip("no DWG writer here")

    loaded = load_dwg(path)
    back = _versioned(getattr(loaded, "doc", loaded))
    assert back["VISUALSTYLE"] and all("ACAD" in x for x in back["VISUALSTYLE"])
    assert back["MLEADERSTYLE"] and all(
        "ACAD_MLEADERVER" in x for x in back["MLEADERSTYLE"])
