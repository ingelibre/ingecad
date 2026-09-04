# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Thin wrapper around the ezdxf document.

The ezdxf document IS the model (architectural principle #1): entities are
edited in place through Commands and saved back with ezdxf, so everything
IngeCAD does not understand (XDATA, proxies, 3DSOLID, dictionaries) survives
the round-trip untouched.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional

import ezdxf
from ezdxf import recover
from ezdxf.document import Drawing
from ezdxf.lldxf.const import DXFStructureError

from core import ezdxf_patches

ezdxf_patches.apply()


class DocumentError(Exception):
    """A DXF file could not be loaded."""


def _repair_material_dict(doc) -> None:
    """Heal ACAD_MATERIAL entries that are dead handle strings.

    LibreDWG-converted files can carry ByBlock/ByLayer/Global entries whose
    MATERIAL objects never made it across; ezdxf then crashes on save
    (``materials.get("ByLayer").dxf``). Dropping the dead strings and
    recreating the required defaults is exactly what AutoCAD's own audit
    does — the rest of the file stays untouched.
    """
    try:
        materials = doc.materials
        broken = [key for key, value in list(materials.object_dict.items())
                  if isinstance(value, str)]
        for key in broken:
            materials.object_dict.discard(key)
        if broken:
            materials.create_required_entries()
    except Exception:
        pass    # never let a repair pass break an open


class Document:
    """An open drawing: the ezdxf doc plus its filesystem identity."""

    def __init__(self, doc: Drawing, path: Optional[Path] = None) -> None:
        self.doc = doc
        self.path = path
        self._dirty = False
        # Monotonic edit counter: every mutation bumps it (all Commands set
        # dirty=True). Lets a background regen detect that the document
        # changed under it and that its result is stale.
        self.revision = 0
        #: Name of the block open in the Block Editor, or None. While set,
        #: :meth:`current_space` answers with that block's layout, so every
        #: draw/edit/snap/pick path operates on the definition without
        #: knowing the editor exists. Owned by core.blockedit.
        self.edit_block: Optional[str] = None
        #: Name of the paper-space layout tab that is current, or None for
        #: the Model tab. Same trick as edit_block and the same reason:
        #: AutoCAD's commands "operate in either model space or paper space"
        #: (MSPACE, p. 1213), so the sheet is edited through the very code
        #: paths the model uses. Owned by views.main_window.switch_layout.
        self.active_layout: Optional[str] = None
        _repair_material_dict(doc)

    @property
    def dirty(self) -> bool:
        return self._dirty

    @dirty.setter
    def dirty(self, value: bool) -> None:
        if value:
            self.revision += 1
        self._dirty = value

    def mark_dirty_no_revision(self) -> None:
        """Dirty without a revision bump.

        For changes that must reach the FILE but alter no drawable content —
        a tab switch writing ``$TILEMODE``. The revision is what scene and
        index caches key on; bumping it here would invalidate them on every
        Model/Layout switch, which is exactly the moment they are needed.
        """
        self._dirty = True

    @classmethod
    def new(cls) -> "Document":
        # Load the standard linetypes (needed for linetype rendering) but not
        # ezdxf's full style/dimstyle setup — a new AutoCAD drawing carries
        # only a couple of established styles, not dozens of OpenSans/EZ_*
        # entries. install_default_styles seeds the metric ISO-25 dim style.
        from core import styles as _styles

        document = cls(ezdxf.new("R2018", setup=["linetypes"]))
        _styles.install_default_styles(document)
        return document

    @classmethod
    def load(cls, path: Path | str) -> "Document":
        """Open a DXF file; real-world files get the ezdxf recover treatment.

        ``recover.readfile`` handles the malformed output of many exporters
        (wrong encodings, unordered sections) that plain ``readfile`` rejects —
        exactly the kind of file a colleague sends.
        """
        path = Path(path)
        try:
            doc = ezdxf.readfile(path)
        except OSError as exc:
            raise DocumentError(str(exc)) from exc
        except Exception:
            # Strict parsing rejects a lot of real-world output (wrong
            # encodings, unordered sections, LibreDWG's handle-0 entities...);
            # recover mode rebuilds what it can.
            try:
                doc, _auditor = recover.readfile(path)
            except (DXFStructureError, ValueError) as exc:
                raise DocumentError(f"not a readable DXF file: {exc}") from exc
        return cls(doc, path)

    @property
    def name(self) -> str:
        return self.path.name if self.path else "Untitled"

    def current_space(self):
        """The space edits happen in — what every draw/edit/snap/pick path
        means by "the drawing".

        Three answers, in priority order: the block open in the Block
        Editor, the active paper-space layout tab, or the modelspace. A
        caller that must always mean the real modelspace says
        ``document.doc.modelspace()`` — being explicit is the whole guard,
        so grep for it before adding one.
        """
        if self.edit_block is not None and self.edit_block in self.doc.blocks:
            return self.doc.blocks.get(self.edit_block)
        if self.active_layout is not None:
            try:
                return self.doc.layouts.get(self.active_layout)
            except Exception:
                self.active_layout = None    # deleted under us: fall back
        return self.doc.modelspace()

    #: Historical name of :meth:`current_space`, kept because most callers
    #: read better as "the modelspace" and every one of them means "the
    #: current space" — the audit that generalized paper-space editing
    #: checked all 42.
    modelspace = current_space

    @property
    def space_name(self) -> str:
        """Human name of the current space, for prompts and status."""
        if self.edit_block is not None:
            return self.edit_block
        return self.active_layout or "Model"

    def save_as(self, path: Path, version: str = "r2000") -> str:
        """Save as DXF directly, or as DWG via a satellite: LibreDWG for
        r2000 (bundled), Open CAD Studio for r2018 (native writer) — see
        ``formats.dwg_bridge.dwg_write_engine``.

        Returns ``(engine, warnings)``: engine is "dxf", "libredwg" or
        "opencadstudio";
        warnings is a list of human-readable strings from the verified save
        (empty when the DWG checked out clean). DXF saves never warn.
        """
        path = Path(path)
        warnings: list[str] = []
        if path.suffix.lower() == ".dwg":
            from core.encoding import write_dwg_intermediate
            from formats.dwg_bridge import dwg_write_engine, write_dwg

            engine = dwg_write_engine(version) or "libredwg"
            with tempfile.TemporaryDirectory(prefix="ingecad-save-") as tmp:
                tmp_dxf = Path(tmp) / "out.dxf"
                write_dwg_intermediate(self.doc, tmp_dxf)
                warnings = write_dwg(tmp_dxf, path, version)
        else:
            self.doc.saveas(path)
            engine = "dxf"
        self.path = path
        self.dirty = False
        return engine, warnings
