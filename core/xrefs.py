# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""External references (XREF): find, load, show and manage them (issue #33).

An xref is a block definition that is EMPTY in the host file: its BLOCK
carries the xref flag (4, or 8 for an overlay) and the path of another
drawing, and every INSERT of that block means "draw that drawing's
modelspace here". ezdxf models the definition (:mod:`ezdxf.xref`); this
module adds what a viewer needs on top: resolving the path the way AutoCAD
does (absolute, relative to the host's folder, or the bare file name in
that folder -- and the other extension when a .dwg was saved as .dxf or
back), loading each referenced drawing ONCE per session (a cache keyed by
path and mtime, so Reload sees an edited file), and handing out the
referenced entities transformed by an INSERT for the regen, the pick
index and the snap engine (:func:`virtual_entities`).

The ezdxf document stays the model: the definitions, flags and paths live
in the host drawing and round-trip untouched. Only two things are kept
beside it, per process: the load cache, and the names the user UNLOADed in
this session (AutoCAD writes that state into the file; we do not yet).
One level of nesting is drawn: a referenced drawing's own xrefs are not
followed (said in the report of #33).
"""
from __future__ import annotations

import fnmatch
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from core.commands import Command

#: BLOCK flags (DXF group 70)
BLK_XREF = 4
BLK_XREF_OVERLAY = 8
BLK_EXTERNAL = 16

#: (resolved path, mtime) -> Document of the referenced drawing (or None
#: when it could not be read, so a broken file is not retried per regen)
_CACHE: dict[tuple[str, float], object] = {}
#: paths being loaded right now: a drawing that references itself, or two
#: that reference each other, must not recurse (one level is drawn anyway)
_LOADING: set[str] = set()
_LOCK = threading.RLock()
#: id(host Document) -> xref names the user unloaded this session
_UNLOADED: dict[int, set[str]] = {}


@dataclass
class XrefInfo:
    name: str
    path: str                     # as saved in the drawing
    overlay: bool
    resolved: Optional[Path]      # where the file was found, or None
    status: str                   # "Loaded" | "Unloaded" | "Not found" | "Unreferenced"
    inserts: int
    #: "dwg" for a drawing; "image" for a raster image, "pdf" for a PDF page
    #: attached as one (PDFATTACH's NAME-pN.png): the palette lists them all,
    #: as AutoCAD's External References palette does.
    kind: str = "dwg"
    #: An image's IMAGEDEF handle -- its key in the palette.
    handle: str = ""


# -- definitions ---------------------------------------------------------------

def is_xref_block(block) -> bool:
    """A block layout / block record that stands for an external drawing."""
    try:
        record = getattr(block, "block_record", block)
        entity = record.block
        return entity is not None and bool(
            entity.dxf.flags & (BLK_XREF | BLK_XREF_OVERLAY))
    except Exception:                        # noqa: BLE001 - not a block then
        return False


def is_xref_insert(insert) -> bool:
    """An INSERT whose block is an external reference."""
    try:
        if insert.dxftype() != "INSERT" or insert.doc is None:
            return False
        block = insert.doc.blocks.get(insert.dxf.name)
        return block is not None and is_xref_block(block)
    except Exception:                        # noqa: BLE001
        return False


def xref_blocks(doc) -> list:
    return [b for b in doc.blocks if is_xref_block(b)]


def xref_path_of(block) -> str:
    try:
        return str(block.block.dxf.get("xref_path", "") or "")
    except Exception:                        # noqa: BLE001
        return ""


def is_overlay(block) -> bool:
    try:
        return bool(block.block.dxf.flags & BLK_XREF_OVERLAY)
    except Exception:                        # noqa: BLE001
        return False


# -- finding and loading -------------------------------------------------------

def resolve_path(host_path: Optional[Path], xref_path: str) -> Optional[Path]:
    """Where the referenced file is, or None.

    AutoCAD's order: the saved path as is (absolute, or relative to the
    host's folder), then the bare file name in the host's folder; and, as
    a courtesy for a project converted between formats, the same name with
    the other extension (.dwg <-> .dxf).
    """
    if not xref_path:
        return None
    candidates: list[Path] = []
    given = Path(xref_path.replace("\\", "/"))
    if given.is_absolute():
        candidates.append(given)
    folder = Path(host_path).parent if host_path else Path.cwd()
    candidates.append(folder / given)
    candidates.append(folder / given.name)
    for candidate in list(candidates):
        for other in (".dwg", ".dxf"):
            if candidate.suffix.lower() != other:
                candidates.append(candidate.with_suffix(other))
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate.resolve()
        except OSError:
            continue
    return None


def load(path: Path):
    """The referenced drawing as a Document, cached by (path, mtime).

    Returns None when the file cannot be read; that answer is cached too,
    until the file changes, so a broken xref costs one attempt, not one
    per regen. A file currently being loaded (a cycle) answers None.
    """
    path = Path(path)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    key = (str(path), mtime)
    if key in _CACHE:
        return _CACHE[key]
    # One loader at a time: the regen worker preloads while the palette
    # asks from the GUI thread, and a second caller must WAIT for the
    # first, not read "being loaded" as "not found" (measured: the palette
    # listed a fresh attachment as Not found). The lock is re-entrant, so
    # only a cycle within ONE thread sees its own path in _LOADING.
    with _LOCK:
        if key in _CACHE:
            return _CACHE[key]
        if str(path) in _LOADING:
            return None
        return _load_locked(path, key)


def read_drawing(path: Path):
    """Another drawing file, DWG or DXF, read as a Document (raises when it
    cannot be read). What an xref shows and what INSERT ▸ Browse defines."""
    from core.document import Document

    path = Path(path)
    if path.suffix.lower() == ".dwg":
        from formats.dwg_bridge import load_dwg

        return load_dwg(path)
    return Document.load(path)


def _load_locked(path: Path, key):
    _LOADING.add(str(path))
    try:
        document = read_drawing(path)
    except Exception as exc:                 # noqa: BLE001 - unreadable: not found
        import logging

        logging.getLogger(__name__).warning("xref %s unreadable: %s", path, exc)
        document = None
    finally:
        _LOADING.discard(str(path))
    for old in [k for k in _CACHE if k[0] == str(path)]:
        del _CACHE[old]                      # older versions of the same file
    _CACHE[key] = document
    return document


def forget(path: Optional[Path] = None) -> None:
    """Drop the cache (Reload): one file, or everything."""
    if path is None:
        _CACHE.clear()
        return
    wanted = {str(path), str(Path(path).resolve())}
    for key in [k for k in _CACHE if k[0] in wanted]:
        del _CACHE[key]


def unloaded(document) -> set[str]:
    return _UNLOADED.setdefault(id(document), set())


def referenced_document(document, block):
    """The loaded drawing behind an xref block, or None (unloaded / missing)."""
    if block.name in unloaded(document):
        return None
    path = resolve_path(getattr(document, "path", None), xref_path_of(block))
    if path is None:
        return None
    return load(path)


def preload(document) -> None:
    """Load every referenced drawing now (before a regen forks its
    workers, so each child inherits the cache instead of reading the
    files itself)."""
    for block in xref_blocks(document.doc):
        try:
            referenced_document(document, block)
        except Exception:                    # noqa: BLE001
            pass


def spaces(doc):
    """Every container an INSERT can live in, once each: the layouts and
    the block definitions proper (a layout's block record is the layout)."""
    out = list(doc.layouts)
    out.extend(b for b in doc.blocks if b.block_record.is_block_layout)
    return out


def _insert_counts(doc) -> dict[str, int]:
    counts: dict[str, int] = {}
    for layout in spaces(doc):
        for insert in layout.query("INSERT"):
            counts[insert.dxf.name] = counts.get(insert.dxf.name, 0) + 1
    return counts


def references(document) -> list[XrefInfo]:
    """What the External References palette lists."""
    doc = document.doc
    counts = _insert_counts(doc)
    out = []
    for block in xref_blocks(doc):
        path = xref_path_of(block)
        resolved = resolve_path(getattr(document, "path", None), path)
        if block.name in unloaded(document):
            status = "Unloaded"
        elif resolved is None or load(resolved) is None:
            status = "Not found"
        elif not counts.get(block.name):
            status = "Unreferenced"
        else:
            status = "Loaded"
        out.append(XrefInfo(block.name, path, is_overlay(block), resolved,
                            status, counts.get(block.name, 0)))
    return sorted(out, key=lambda x: x.name.lower())


IMAGE_DICT = "ACAD_IMAGE_DICT"


def image_references(document) -> list[XrefInfo]:
    """The raster images (and PDF pages attached as images) a drawing
    references, for the External References palette (Rafael, review 6,
    55:00-58:00: the palette listed only DWGs). Status as for a drawing:
    found next to the drawing or where saved, "Not found", or
    "Unreferenced" when no IMAGE uses the definition any more."""
    import re

    from core.layers import placed_entities

    doc = document.doc
    images = doc.rootdict.get(IMAGE_DICT)
    if images is None:
        return []
    counts: dict[str, int] = {}
    for entity in placed_entities(document):
        if entity.dxftype() == "IMAGE":
            key = entity.dxf.get("image_def_handle", "")
            counts[key] = counts.get(key, 0) + 1
    out = []
    for name, image_def in images.items():
        if image_def is None or not image_def.is_alive or image_def.dxftype() != "IMAGEDEF":
            continue
        path = str(image_def.dxf.get("filename", ""))
        resolved = resolve_path(getattr(document, "path", None), path)
        handle = image_def.dxf.handle
        if resolved is None:
            status = "Not found"
        elif not counts.get(handle):
            status = "Unreferenced"
        else:
            status = "Loaded"
        kind = "pdf" if re.search(r"-p\d+\.png$", path, re.I) else "image"
        # AutoCAD keys the dictionary by a plain name; ezdxf by the whole
        # file path -- the palette shows the name either way
        label = str(name)
        if any(c in label for c in "/\\."):
            label = Path(label.replace("\\", "/")).stem
        out.append(XrefInfo(label, path, False, resolved, status,
                            counts.get(handle, 0), kind=kind, handle=handle))
    return sorted(out, key=lambda x: x.name.lower())


class DetachImageCommand(Command):
    """The palette's Detach for an image (AutoCAD's -IMAGE Detach): every
    IMAGE that shows it leaves the drawing, and the definition leaves the
    image dictionary. One undo step puts both back."""

    name = "IMAGE"
    needs_regen = True

    def __init__(self, handle: str) -> None:
        self.handle = handle
        self._unlinked: list = []
        self._key = None

    def do(self, document) -> None:
        doc = document.doc
        self._unlinked = []
        for layout in doc.layouts_and_blocks():
            for entity in list(layout):
                if entity.dxftype() == "IMAGE" and \
                        entity.dxf.get("image_def_handle", "") == self.handle:
                    layout.unlink_entity(entity)
                    self._unlinked.append((layout, entity))
        images = doc.rootdict.get(IMAGE_DICT)
        if images is not None:
            for key, value in list(images.items()):
                if value is not None and value.dxf.handle == self.handle:
                    self._key = (key, value)
                    images.discard(key)
        document.dirty = True

    def undo(self, document) -> None:
        images = document.doc.rootdict.get(IMAGE_DICT)
        if self._key is not None and images is not None:
            images[self._key[0]] = self._key[1]
        for layout, entity in reversed(self._unlinked):
            layout.add_entity(entity)
        self._unlinked = []
        document.dirty = True


def match_names(document, pattern: str) -> list[str]:
    """Xref names matching an AutoCAD wildcard list ("A,B*")."""
    names = [b.name for b in xref_blocks(document.doc)]
    wanted: list[str] = []
    for part in pattern.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        for name in names:
            if fnmatch.fnmatchcase(name.upper(), part.upper()) and name not in wanted:
                wanted.append(name)
    return wanted


# -- the referenced geometry, placed by an INSERT ------------------------------

MAX_DEPTH = 8


def _explode(entity, depth: int):
    """Plain entities of ``entity``, block references expanded."""
    if depth > MAX_DEPTH:
        return
    if entity.dxftype() == "INSERT":
        try:
            children = list(entity.virtual_entities())
        except Exception:                    # noqa: BLE001 - a broken block: skip
            return
        for child in children:
            yield from _explode(child, depth + 1)
        return
    yield entity


def referenced_for_insert(document, insert):
    """The Document an xref INSERT shows, or None."""
    if insert.doc is None:
        return None
    block = insert.doc.blocks.get(insert.dxf.name)
    if block is None or not is_xref_block(block):
        return None
    return referenced_document(document, block)


def virtual_entities(insert, document):
    """Copies of the referenced drawing's modelspace entities, transformed
    by ``insert`` -- what the regen draws and the indexes trace for an
    xref INSERT. Empty when the file is missing or unloaded.

    Entities that fail to copy or transform are skipped (a viewer draws
    what it can), and the copies belong to the REFERENCED document, so
    their layers, styles and nested blocks resolve there.
    """
    xdoc = referenced_for_insert(document, insert)
    if xdoc is None:
        return
    try:
        matrix = insert.matrix44()
    except Exception:                        # noqa: BLE001
        return
    for entity in xdoc.doc.modelspace():
        for plain in _explode(entity, 0):
            try:
                copy = plain if plain.dxf.handle is None else plain.copy()
                copy.transform(matrix)
            except Exception:                # noqa: BLE001 - not placeable: skip
                continue
            yield copy


def inserts_of(doc, name: str) -> list:
    out = []
    for layout in spaces(doc):
        out.extend(e for e in layout.query("INSERT") if e.dxf.name == name)
    return out


# -- commands ------------------------------------------------------------------

def saved_path_for(host_path: Optional[Path], file: Path, path_type: str) -> str:
    """What XATTACH writes into the drawing for the chosen path type:
    Full (absolute), Relative (to the host's folder, AutoCAD's ".\\")
    or No path (the bare file name)."""
    file = Path(file)
    kind = (path_type or "Relative").strip().upper()[:1]
    if kind == "N":
        return file.name
    if kind == "F" or host_path is None:
        return str(file.resolve())
    try:
        relative = os.path.relpath(file.resolve(),
                                   Path(host_path).resolve().parent)
    except ValueError:                        # another drive on Windows
        return str(file.resolve())
    if not relative.startswith("."):
        relative = os.path.join(".", relative)
    return relative


def unique_name(doc, stem: str) -> str:
    name = stem
    n = 1
    while name in doc.blocks:
        n += 1
        name = f"{stem}-{n}"
    return name


class AttachXrefCommand(Command):
    """XATTACH / -XREF Attach: define the xref block (if new) and place one
    INSERT of it in the current space, as one undo step."""

    needs_regen = True

    def __init__(self, name: str, saved_path: str, insert, xscale=1.0,
                 yscale=None, rotation=0.0, overlay=False) -> None:
        self.name = "XATTACH"
        self.block_name = name
        self.saved_path = saved_path
        self.point = (float(insert[0]), float(insert[1]))
        self.xscale = float(xscale)
        self.yscale = float(xscale if yscale is None else yscale)
        self.rotation = float(rotation)
        self.overlay = bool(overlay)
        self.entity = None
        self._defined = False

    def do(self, document) -> None:
        from ezdxf import xref as ezxref

        doc = document.doc
        if self.block_name not in doc.blocks:
            ezxref.define(doc, self.block_name, self.saved_path,
                          overlay=self.overlay)
            self._defined = True
        space = self.space(document)
        self.entity = space.add_blockref(
            self.block_name, self.point,
            dxfattribs={"xscale": self.xscale, "yscale": self.yscale,
                        "rotation": self.rotation})
        from core.actions import dress_new_entity

        dress_new_entity(document, self.entity, None)
        document.dirty = True

    def undo(self, document) -> None:
        doc = document.doc
        if self.entity is not None:
            self.removed_handles = [self.entity.dxf.handle]
            self.space(document).delete_entity(self.entity)
            self.entity = None
        if self._defined and self.block_name in doc.blocks:
            doc.blocks.delete_block(self.block_name, safe=False)
            self._defined = False
        document.dirty = True


class DetachXrefCommand(Command):
    """-XREF Detach: every INSERT of the xref goes, then its definition."""

    needs_regen = True

    def __init__(self, name: str) -> None:
        self.name = "XREF Detach"
        self.block_name = name
        self._inserts: list = []          # (owner layout, insert)
        self._path = ""
        self._flags = 0

    def do(self, document) -> None:
        doc = document.doc
        block = doc.blocks.get(self.block_name)
        if block is None:
            return
        self._path = xref_path_of(block)
        self._flags = int(block.block.dxf.flags)
        self._inserts = []
        for layout in spaces(doc):
            for insert in list(layout.query("INSERT")):
                if insert.dxf.name == self.block_name:
                    layout.unlink_entity(insert)
                    self._inserts.append((layout, insert))
        self.removed_handles = [e.dxf.handle for _l, e in self._inserts]
        doc.blocks.delete_block(self.block_name, safe=False)
        document.dirty = True

    def undo(self, document) -> None:
        doc = document.doc
        if self.block_name not in doc.blocks:
            doc.blocks.new(name=self.block_name,
                           dxfattribs={"flags": self._flags,
                                       "xref_path": self._path})
        for layout, insert in self._inserts:
            layout.add_entity(insert)
        self._inserts = []
        document.dirty = True


class SetXrefPathCommand(Command):
    """-XREF Path: the saved path of an xref."""

    needs_regen = True

    def __init__(self, name: str, new_path: str) -> None:
        self.name = "XREF Path"
        self.block_name = name
        self.new_path = new_path
        self.old_path = ""

    def do(self, document) -> None:
        block = document.doc.blocks.get(self.block_name)
        if block is None:
            return
        self.old_path = xref_path_of(block)
        block.block.dxf.xref_path = self.new_path
        document.dirty = True

    def undo(self, document) -> None:
        block = document.doc.blocks.get(self.block_name)
        if block is not None:
            block.block.dxf.xref_path = self.old_path
        document.dirty = True


class SetXrefOverlayCommand(Command):
    """-XREF Overlay / Attach on an existing xref: flip its reference type."""

    def __init__(self, name: str, overlay: bool) -> None:
        self.name = "XREF type"
        self.block_name = name
        self.overlay = bool(overlay)
        self.old_flags = 0

    def do(self, document) -> None:
        block = document.doc.blocks.get(self.block_name)
        if block is None:
            return
        self.old_flags = int(block.block.dxf.flags)
        flags = self.old_flags & ~(BLK_XREF | BLK_XREF_OVERLAY)
        block.block.dxf.flags = flags | (
            BLK_XREF_OVERLAY if self.overlay else BLK_XREF)
        document.dirty = True

    def undo(self, document) -> None:
        block = document.doc.blocks.get(self.block_name)
        if block is not None:
            block.block.dxf.flags = self.old_flags
        document.dirty = True


def unload(document, names: Iterable[str]) -> None:
    unloaded(document).update(names)


def reload(document, names: Iterable[str]) -> None:
    """Reload: forget the loaded copy so the next regen reads the file;
    an unloaded xref comes back."""
    for name in names:
        unloaded(document).discard(name)
        block = document.doc.blocks.get(name)
        if block is None:
            continue
        path = resolve_path(getattr(document, "path", None), xref_path_of(block))
        if path is not None:
            forget(path)
