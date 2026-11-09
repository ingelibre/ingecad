# SPDX-License-Identifier: GPL-3.0-or-later
"""Undoing MIRROR puts back the XDATA too.

MIRROR on an OCS entity (or a text) restores the entity from a snapshot on
undo, while MOVE, ROTATE and SCALE undo with the inverse matrix. The
snapshot path put back the DXF attributes and the vertices, but not the
XDATA: the world points and directions in it (group codes 1011-1013), which
the mirror had reflected, stayed reflected after U. A plugin that keeps a
reference point in XDATA (as the architecture plugin does) then sees the
entity back in place and its point still mirrored.
"""
from __future__ import annotations

import ezdxf
import pytest

from core import actions
from core.commands import History
from core.document import Document

APPID = "TESTAPP"


def _document_with(add):
    doc = ezdxf.new()
    doc.appids.new(APPID)
    entity = add(doc.modelspace())
    entity.set_xdata(APPID, [(1000, "ref"), (1011, (1.0, 2.0, 0.0)),
                             (1012, (1.0, 0.0, 0.0))])
    document = Document(doc)
    return document, entity


def _xdata(entity):
    return [(code, tuple(round(v, 9) for v in value) if isinstance(value, tuple)
             or hasattr(value, "x") else value)
            for code, value in entity.get_xdata(APPID)]


@pytest.mark.parametrize("add", [
    lambda msp: msp.add_lwpolyline([(0, 0), (4, 0), (4, 1)]),
    lambda msp: msp.add_circle((2, 2), 1),
    lambda msp: msp.add_text("A", dxfattribs={"insert": (1, 1)}),
    lambda msp: msp.add_line((0, 0), (3, 1)),
], ids=["lwpolyline", "circle", "text", "line"])
def test_mirror_undo_restores_xdata(add):
    document, entity = _document_with(add)
    before = _xdata(entity)
    history = History(document)
    history.execute(actions.mirror_entities([entity], (0, 5), (10, 5),
                                            keep_source=False))
    assert _xdata(entity) != before          # the mirror moved the point
    history.undo()
    assert _xdata(entity) == before
    history.redo()
    history.undo()
    assert _xdata(entity) == before
