# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The system clipboard carries a copy as a DXF drawing.

Every IngeCAD window is its own process (two drawings open = two
programs), so a clipboard that lives in the window never reached the other
one: "Clipboard is empty." (#75, Arthur on Windows with 0.6.6). Ctrl+C now
also puts the copy on the system clipboard as a small DXF -- the entities
with every layer, block, style and linetype they name, and the base point
in ``$INSBASE`` -- under ``MIME``. Ctrl+V in any IngeCAD reads it back.

The clipboard drawing is built at copy time, on the GUI thread (it reads
the drawing the user edits): a snapshot, so a later edit or a cut does not
change what was copied. Writing it to text -- half the cost, 1.5 s for a
whole 35 000-object plan -- runs on a ``ClipWriter`` thread, and the window
that copied pastes from memory meanwhile. (A lazily rendered QMimeData
subclass is not an option: PySide never calls its retrieveData.)
"""
from __future__ import annotations

import io
import itertools
import os
import uuid
from typing import Optional

from PySide6.QtCore import QMimeData, QThread, Signal

MIME = "application/x-ingecad-dxf"
#: Which copy this is: "<process>-<pid>:<n>". A window pastes its own copy
#: from memory.
ID_MIME = "application/x-ingecad-clip-id"

_counter = itertools.count(1)
#: This process among the others. Not the pid alone: inside the Flatpak
#: every IngeCAD is pid 2 of its own sandbox, so two windows numbered their
#: copies alike and a window took another's newer copy for its own older
#: one (found running two Flatpak instances, 2026-10-10).
_PROCESS = uuid.uuid4().hex[:12]


def clip_document(entities, base):
    """A new drawing holding ``entities`` and everything they name."""
    import ezdxf
    from ezdxf import xref

    source = entities[0].doc
    version = source.dxfversion if source.dxfversion >= "AC1015" else "R2000"
    doc = ezdxf.new(version, setup=False)
    doc.header["$INSUNITS"] = source.header.get("$INSUNITS", 0)
    doc.header["$INSBASE"] = (float(base[0]), float(base[1]), 0.0)
    loader = xref.Loader(source, doc, conflict_policy=xref.ConflictPolicy.KEEP)
    loader.add_command(xref.LoadEntities(list(entities), doc.modelspace()))
    loader.execute()
    return doc


def dxf_bytes(doc) -> bytes:
    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue().encode("utf-8")


def read_dxf(data: bytes):
    """(sources, base) from clipboard DXF bytes."""
    import ezdxf

    doc = ezdxf.read(io.StringIO(data.decode("utf-8")))
    base = doc.header.get("$INSBASE", (0.0, 0.0, 0.0))
    return list(doc.modelspace()), (float(base[0]), float(base[1]))


def _clipboard():
    from PySide6.QtGui import QGuiApplication

    if QGuiApplication.instance() is None:
        return None
    return QGuiApplication.clipboard()


def build(entities, base):
    """(clip id, clipboard drawing) for ``entities``; None when there is no
    clipboard (headless) or an entity cannot be carried (the copy stays in
    the window's memory, as before)."""
    if _clipboard() is None or not entities:
        return None
    try:
        doc = clip_document(entities, base)
    except Exception:  # noqa: BLE001
        return None
    return f"{_PROCESS}-{os.getpid()}:{next(_counter)}", doc


def put(clip_id: str, data: bytes) -> None:
    """Hand the written copy to the system clipboard (GUI thread)."""
    board = _clipboard()
    if board is None:
        return
    mime = QMimeData()
    mime.setData(ID_MIME, clip_id.encode("ascii"))
    mime.setData(MIME, data)
    board.setMimeData(mime)


def publish(entities, base) -> Optional[str]:
    """build + write + put, all at once (headless helpers and tests)."""
    built = build(entities, base)
    if built is None:
        return None
    clip_id, doc = built
    put(clip_id, dxf_bytes(doc))
    return clip_id


class ClipWriter(QThread):
    """Writes a clipboard drawing to DXF text off the GUI thread. The
    drawing is the copy's own, so nothing else touches it meanwhile."""

    done = Signal(str, object)      # clip id, bytes (None when it failed)

    def __init__(self, clip_id: str, doc) -> None:
        super().__init__()
        self.setObjectName("clipboard-writer")
        self._clip_id = clip_id
        self._doc = doc

    def run(self) -> None:
        from core import gc_guard

        with gc_guard.paused():
            try:
                data = dxf_bytes(self._doc)
            except Exception:  # noqa: BLE001
                data = None
            self.done.emit(self._clip_id, data)


def current_id() -> Optional[str]:
    """The id of the IngeCAD copy now on the clipboard, if there is one."""
    board = _clipboard()
    data = board.mimeData() if board is not None else None
    if data is None or not data.hasFormat(ID_MIME):
        return None
    return bytes(data.data(ID_MIME)).decode("ascii", "replace") or None


def current_dxf() -> Optional[bytes]:
    board = _clipboard()
    data = board.mimeData() if board is not None else None
    if data is None or not data.hasFormat(MIME):
        return None
    raw = bytes(data.data(MIME))
    return raw or None
