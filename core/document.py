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
from core import dimassoc  # noqa: F401 -- registers DIMASSOC before any read

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
        # The way back from an ezdxf entity to the Document it lives in
        # (``entity.doc._ingecad_document``): the pick index, the snap
        # engine and the renderer meet bare entities and need the host's
        # path to resolve an external reference (core.xrefs).
        doc._ingecad_document = self
        self.path = path
        self._dirty = False
        # Monotonic edit counter: every mutation bumps it (all Commands set
        # dirty=True). Lets a background regen detect that the document
        # changed under it and that its result is stale.
        self.revision = 0
        #: bumped when a block definition changes (see History._mark_blocks)
        self.blocks_revision = 0
        #: The last PLOT dialog settings per layout name, for the session:
        #: the dialog reopens as it was left, the way AutoCAD's does.
        self.plot_settings: dict[str, dict] = {}
        #: Layouts born in this session that were never opened: the first
        #: visit gives them a viewport onto the model, as AutoCAD's Layout1
        #: comes with one (LAYOUTCREATEVIEWPORT). A drawing's own layouts
        #: are never touched: an empty sheet in a file is deliberate.
        self.uninitialized_layouts: set[str] = set()
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
        # Not ezdxf's setup: a new AutoCAD drawing (acadiso.dwt) carries
        # only Continuous -- the rest are loaded from acadiso.lin when wanted,
        # with its millimetre values, not ezdxf's preloaded ones -- and only a
        # couple of established styles, not dozens of OpenSans/EZ_* entries.
        # install_default_styles seeds the metric ISO-25 dim style.
        from core import styles as _styles

        document = cls(ezdxf.new("R2018", setup=False))
        _styles.install_default_styles(document)
        # AutoCAD's templates: MIRROR keeps text readable. ezdxf's own
        # default is 1 (mirror writing).
        document.doc.header["$MIRRTEXT"] = 0
        # acadiso.dwt's Standard text style is Arial. The drawing stores the
        # name; where Arial is not installed (a clean Linux) it is drawn in
        # Liberation Sans, made on Arial's exact widths
        # (ezdxf_patches._patch_metric_compatible_fonts).
        standard = document.doc.styles.get("Standard")
        if standard is not None and not standard.dxf.get("font", ""):
            standard.dxf.font = "arial.ttf"
            standard.set_extended_font_data(family="Arial")
        # and their scale list (annotation scales, viewport scales)
        from core import annotative

        annotative.seed_standard_scales(document.doc)
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
        # sheets IngeCAD wrote before 0.6.7 lack AutoCAD's main viewport
        from core.layouts import repair_missing_main_viewports

        repair_missing_main_viewports(doc)
        return cls(doc, path)

    @property
    def name(self) -> str:
        if self.path:
            return self.path.name
        from core.i18n import tr

        return tr("Untitled")

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
        """Save as DXF directly, or as DWG r2000 through LibreDWG (bundled)
        — see ``formats.dwg_bridge.dwg_write_engine``.

        Returns ``(engine, warnings)``: engine is "dxf" or "libredwg";
        warnings is a list of human-readable strings from the verified save
        (empty when the DWG checked out clean). DXF saves never warn.
        """
        engine, warnings = self.prepare_save(path, version)()
        self.saved_to(path)
        return engine, warnings

    def prepare_save(self, path: Path, version: str = "r2000"):
        """The part of a save that READS the drawing, done now, on the
        calling thread; returns ``finish()``, the part that only works on
        files -- LibreDWG's conversion and the verification, 7 of the 10
        seconds a big plan takes -- safe to run on a worker thread. It
        returns ``(engine, warnings)`` like :meth:`save_as`; call
        :meth:`saved_to` once it has succeeded."""
        path = Path(path)
        if path.suffix.lower() != ".dwg":
            self.doc.saveas(path)
            return lambda: ("dxf", [])
        import shutil

        from core.encoding import write_dwg_intermediate
        from formats.dwg_bridge import dwg_write_engine, write_dwg

        engine = dwg_write_engine(version) or "libredwg"
        tmp = Path(tempfile.mkdtemp(prefix="ingecad-save-"))
        tmp_dxf = tmp / "out.dxf"
        try:
            write_dwg_intermediate(self.doc, tmp_dxf)
            annotative = _annotative_save_warnings(self.doc)
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise

        def finish():
            try:
                return engine, write_dwg(tmp_dxf, path, version) + annotative
            finally:
                shutil.rmtree(tmp, ignore_errors=True)

        return finish

    def saved_to(self, path: Path) -> None:
        """The drawing now lives in ``path``, as saved."""
        self.path = Path(path)
        self.dirty = False


def _survives_dwg(entity) -> bool:
    """Do this object's scale representations come back from a DWG? The
    bundled LibreDWG imports text and dimension contexts since 0.6.7
    (vendor patch of 2026-10-10, checked through ODA); other kinds --
    a colleague's multileaders, hatches, blocks -- are not proven yet."""
    kind = entity.dxftype()
    if kind in ("TEXT", "MTEXT"):
        return True
    return kind == "DIMENSION" and (entity.dimtype & 7) in (0, 1, 3, 4)


def _annotative_save_warnings(doc) -> list[str]:
    """A save that would lose scale representations says so -- and DXF,
    which keeps them all, is the way out."""
    from core import annotative
    from core.i18n import tr

    count = sum(1 for layout in doc.layouts for e in layout
                if annotative.is_annotative(e)
                and len(annotative.representations(e)) > 1
                and not _survives_dwg(e))
    if not count:
        return []
    return [tr("{count} annotative objects keep only their default scale "
               "in the DWG; save as DXF to keep every scale",
               count=count)]
