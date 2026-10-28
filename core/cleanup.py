# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Drawing cleanup, headless: PURGE, OVERKILL and WBLOCK (#37).

AutoCAD's prompts (acad_acr, "-PURGE", p. 1571; "-WBLOCK", p. 2089), kept
verbatim so a user types what their hands already know::

    Enter type of unused objects to purge
    [Blocks/DEtailviewstyles/Dimstyles/Groups/LAyers/LTypes/MAterials/
     MUltileaderstyles/Plotstyles/SHapes/textSTyles/Mlinestyles/
     SEctionviewstyles/Tablestyles/Visualstyles/Regapps/Zero-length geometry/
     Empty text objects/Orphaned data/All]:
    Enter name(s) to purge <*>:
    Verify each name to be purged? [Yes/No] <Y>:

    Enter name of output file:
    Enter name of existing block or
    [= (block=output file)/* (whole drawing)] <define new drawing>:

OVERKILL is not in that reference (it joined AutoCAD in 2012); its
command-line form follows the -OVERKILL prompt AutoCAD shows::

    Enter an option to change
    [Ignore/Tolerance/Optimize plines/Partial overlap/End to end/
     Associativity/Done] <Done>:

The rules that keep a purge conservative (the round-trip promise): nothing
is touched but what was purged, a purge is one undoable Command, and the
protected names never go -- layer 0 and Defpoints, the current layer, the
Standard styles, Continuous/ByLayer/ByBlock, layout blocks, xrefs, and any
block still reachable from a layout, a dimension, a leader or a style.
"""
from __future__ import annotations

import fnmatch
import math
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

from core.commands import Command
from core.i18n import tr

# -- categories ---------------------------------------------------------------

#: (key, AutoCAD keyword as spelt in the prompt, singular noun for messages)
CATEGORIES = (
    ("blocks", "Blocks", "block"),
    ("dimstyles", "Dimstyles", "dimension style"),
    ("groups", "Groups", "group"),
    ("layers", "LAyers", "layer"),
    ("ltypes", "LTypes", "linetype"),
    ("mleaderstyles", "MUltileaderstyles", "multileader style"),
    ("textstyles", "textSTyles", "text style"),
    ("regapps", "Regapps", "regapp"),
)
#: Categories the prompt lists that this drawing engine has no table for.
UNSUPPORTED = {
    "DE": "detail view styles", "MA": "materials", "P": "plot styles",
    "SH": "shapes", "M": "multiline styles", "SE": "section view styles",
    "T": "table styles", "V": "visual styles", "O": "orphaned data",
}
NAMED = tuple(key for key, _kw, _noun in CATEGORIES)
UNNAMED = ("zero", "empty")

PURGE_PROMPT = ("Enter type of unused objects to purge "
                "[Blocks/DEtailviewstyles/Dimstyles/Groups/LAyers/LTypes/"
                "MAterials/MUltileaderstyles/Plotstyles/SHapes/textSTyles/"
                "Mlinestyles/SEctionviewstyles/Tablestyles/Visualstyles/"
                "Regapps/Zero-length geometry/Empty text objects/"
                "Orphaned data/All]:")
_KEY_TO_CATEGORY = {"B": "blocks", "D": "dimstyles", "G": "groups",
                    "LA": "layers", "LT": "ltypes", "MU": "mleaderstyles",
                    "ST": "textstyles", "R": "regapps", "Z": "zero",
                    "E": "empty", "A": "all"}
NOUNS = {key: noun for key, _kw, noun in CATEGORIES}
NOUNS.update({"zero": "zero-length object", "empty": "empty text object"})
#: The plural of each noun, translated as a whole (Spanish does not pluralize
#: "estilo de cota" by appending an s).
PLURALS = {"blocks": "blocks", "dimstyles": "dimension styles",
           "groups": "groups", "layers": "layers", "ltypes": "linetypes",
           "mleaderstyles": "multileader styles", "textstyles": "text styles",
           "regapps": "regapps", "zero": "zero-length objects",
           "empty": "empty text objects"}

_PROTECTED_LAYERS = {"0", "DEFPOINTS"}
_PROTECTED_LTYPES = {"BYLAYER", "BYBLOCK", "CONTINUOUS"}
_BLK_XREF = 4 | 8 | 16          # xref, xref overlay, external dependent


# -- walking the drawing -----------------------------------------------------

def _layouts(doc):
    return list(doc.layouts)


def _blocks(doc):
    """Block layouts that are not layouts themselves."""
    return [b for b in doc.blocks if not b.is_any_layout]


def _is_xref(block) -> bool:
    try:
        return bool(int(block.block.dxf.get("flags", 0)) & _BLK_XREF)
    except Exception:  # noqa: BLE001
        return False


def _record_name(doc, handle) -> Optional[str]:
    if not handle or handle == "0":
        return None
    record = doc.entitydb.get(handle)
    if record is None or not record.is_alive:
        return None
    try:
        return record.dxf.name
    except Exception:  # noqa: BLE001
        return None


def _block_refs_of(doc, entity) -> set[str]:
    """Block names one entity (or one style object) points at."""
    names: set[str] = set()
    kind = entity.dxftype()
    dxf = entity.dxf
    if kind == "INSERT":
        names.add(dxf.get("name", ""))
    elif kind.endswith("DIMENSION"):
        geometry = dxf.get("geometry", None)
        if geometry:
            names.add(geometry)
    for attr in ("block_record_handle", "arrow_head_handle"):
        if dxf.is_supported(attr):
            name = _record_name(doc, dxf.get(attr, None))
            if name:
                names.add(name)
    if kind == "DIMSTYLE":
        # an arrow is named ARCHTICK in the style and _ARCHTICK as a block
        from ezdxf.render.arrows import ARROWS

        for attr in ("dimblk", "dimblk1", "dimblk2", "dimldrblk"):
            value = dxf.get(attr, "")
            if value:
                names.add(value)
                try:
                    names.add(ARROWS.block_name(value))
                except Exception:  # noqa: BLE001
                    pass
    names.discard("")
    return names


def _style_objects(doc):
    yield from doc.dimstyles
    try:
        for _name, style in doc.mleader_styles.items():
            yield style
    except Exception:  # noqa: BLE001
        pass


def block_candidates(doc, nested: bool = True) -> list[str]:
    """Block definitions nothing needs.

    ``nested`` (the dialog's "Purge nested items") purges a block that only
    an unreferenced block uses; ``-PURGE`` removes one level at a time.
    """
    by_name = {b.name: b for b in _blocks(doc)}
    protected = {name for name, b in by_name.items()
                 if _is_xref(b) or name.upper().startswith(("*MODEL_SPACE",
                                                            "*PAPER_SPACE"))}
    roots: set[str] = set()
    for layout in _layouts(doc):
        for e in layout:
            roots |= _block_refs_of(doc, e)
    for style in _style_objects(doc):
        roots |= _block_refs_of(doc, style)
    inside: dict[str, set[str]] = {}
    for name, b in by_name.items():
        refs: set[str] = set()
        for e in b:
            refs |= _block_refs_of(doc, e)
        inside[name] = refs
    if nested:
        reachable: set[str] = set()
        stack = [n for n in roots if n in by_name]
        while stack:
            name = stack.pop()
            if name in reachable:
                continue
            reachable.add(name)
            stack.extend(n for n in inside.get(name, ()) if n in by_name)
        used = reachable
    else:
        used = set(roots)
        for refs in inside.values():
            used |= refs
    return sorted(n for n in by_name
                  if n not in used and n not in protected)


def _entities_kept(doc, dropping_blocks: Iterable[str]):
    """Every entity that survives a purge of ``dropping_blocks``."""
    dropping = set(dropping_blocks)
    for layout in _layouts(doc):
        yield from layout
    for b in _blocks(doc):
        if b.name not in dropping:
            yield from b


def used_linetypes(doc, entities=None, dropping_layers=()) -> set[str]:
    """The linetypes the drawing uses, upper-cased: by its entities, by the
    layers that stay, by dimension and multileader styles, as the current
    one -- plus the three that always count (BYLAYER, BYBLOCK, CONTINUOUS).

    One answer for both questions that need it: what PURGE may remove (with
    the layers it is dropping in the same pass) and what the Linetype
    Manager's Delete may remove (AutoCAD: "You can delete only unused
    linetypes").
    """
    if entities is None:
        entities = _entities_kept(doc, ())
    dropping = {str(n).upper() for n in dropping_layers}
    used = {str(e.dxf.get("linetype", "BYLAYER")).upper() for e in entities}
    used |= {str(l.dxf.get("linetype", "CONTINUOUS")).upper()
             for l in doc.layers if l.dxf.name.upper() not in dropping}
    used.add(str(doc.header.get("$CELTYPE", "BYLAYER")).upper())
    for style in _style_objects(doc):
        for attr in ("dimltype", "dimltex1", "dimltex2"):
            used.add(str(style.dxf.get(attr, "")).upper())
        if style.dxf.is_supported("leader_linetype_handle"):
            used.add(str(_record_name(
                doc, style.dxf.get("leader_linetype_handle", None)) or "").upper())
    used.discard("")
    return used | _PROTECTED_LTYPES


def candidates(doc, nested: bool = True) -> dict[str, list]:
    """What PURGE may remove, per category: names, or entities for the
    unnamed categories (zero-length geometry, empty text)."""
    out: dict[str, list] = {}
    blocks = block_candidates(doc, nested)
    out["blocks"] = blocks
    kept = list(_entities_kept(doc, blocks))
    header = doc.header

    def ci(names):
        return {str(n).upper() for n in names if n}

    # layers: entities, viewport freeze lists, the current one, 0/Defpoints
    used_layers = ci(e.dxf.get("layer", "0") for e in kept) | _PROTECTED_LAYERS
    used_layers.add(str(header.get("$CLAYER", "0")).upper())
    for e in kept:
        if e.dxftype() == "VIEWPORT":
            used_layers |= ci(getattr(e, "frozen_layers", []) or [])
    out["layers"] = sorted(l.dxf.name for l in doc.layers
                           if l.dxf.name.upper() not in used_layers)
    dropping_layers = ci(out["layers"])
    used_lt = used_linetypes(doc, kept, dropping_layers)
    out["ltypes"] = sorted(lt.dxf.name for lt in doc.linetypes
                           if lt.dxf.name.upper() not in used_lt)
    # text styles: text entities, dimension and multileader styles, current
    used_st = ci(e.dxf.get("style", "Standard") for e in kept
                 if e.dxftype() in ("TEXT", "MTEXT", "ATTRIB", "ATTDEF"))
    used_st.add(str(header.get("$TEXTSTYLE", "Standard")).upper())
    used_st.add("STANDARD")
    for style in _style_objects(doc):
        used_st.add(str(style.dxf.get("dimtxsty", "")).upper())
        if style.dxf.is_supported("text_style_handle"):
            used_st.add(str(_record_name(
                doc, style.dxf.get("text_style_handle", None)) or "").upper())
    out["textstyles"] = sorted(s.dxf.name for s in doc.styles
                               if s.dxf.name.upper() not in used_st
                               and not s.dxf.name.startswith("*"))
    # dimension styles: dimensions, leaders, tolerances, current
    used_ds = ci(e.dxf.get("dimstyle", "Standard") for e in kept
                 if e.dxftype().endswith("DIMENSION")
                 or e.dxftype() in ("LEADER", "TOLERANCE"))
    used_ds.add(str(header.get("$DIMSTYLE", "Standard")).upper())
    used_ds.add("STANDARD")
    out["dimstyles"] = sorted(s.dxf.name for s in doc.dimstyles
                              if s.dxf.name.upper() not in used_ds)
    # multileader styles: multileaders, current
    used_ml = {"STANDARD"}
    for e in kept:
        if e.dxftype() == "MULTILEADER":
            used_ml.add(str(_record_name(
                doc, e.dxf.get("style_handle", None)) or "").upper())
    used_ml.add(str(_record_name(
        doc, header.get("$CMLEADERSTYLE", None)) or "").upper())
    try:
        out["mleaderstyles"] = sorted(
            name for name, _s in doc.mleader_styles.items()
            if name.upper() not in used_ml)
    except Exception:  # noqa: BLE001
        out["mleaderstyles"] = []
    # groups: empty ones
    empty_groups = []
    try:
        for name, group in doc.groups:
            if not any(e.is_alive for e in group):
                empty_groups.append(name)
    except Exception:  # noqa: BLE001
        pass
    out["groups"] = sorted(empty_groups)
    # regapps: appids no XDATA names any more
    used_apps = {"ACAD"}
    for e in list(kept) + list(doc.objects):
        xdata = getattr(e, "xdata", None)
        if xdata is not None:
            try:
                used_apps |= ci(xdata.data.keys())
            except Exception:  # noqa: BLE001
                pass
    out["regapps"] = sorted(a.dxf.name for a in doc.appids
                            if a.dxf.name.upper() not in used_apps)
    out["zero"] = zero_length_entities(doc)
    out["empty"] = empty_text_entities(doc)
    return out


def _locked(doc, entity) -> bool:
    try:
        return doc.layers.get(entity.dxf.layer).is_locked()
    except Exception:  # noqa: BLE001
        return False


def _same(a, b, tol: float = 1e-9) -> bool:
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol


def zero_length_entities(doc) -> list:
    """Lines, arcs, circles and polylines of no length, in the layouts only
    (AutoCAD: never inside blocks, never on locked layers)."""
    out = []
    for layout in _layouts(doc):
        for e in layout:
            kind = e.dxftype()
            if _locked(doc, e):
                continue
            zero = False
            try:
                if kind == "LINE":
                    zero = _same(e.dxf.start, e.dxf.end)
                elif kind == "CIRCLE":
                    zero = float(e.dxf.radius) <= 0.0
                elif kind == "ARC":
                    span = (float(e.dxf.end_angle) - float(e.dxf.start_angle)) % 360.0
                    zero = float(e.dxf.radius) <= 0.0 or span == 0.0
                elif kind == "LWPOLYLINE":
                    pts = [(p[0], p[1]) for p in e.get_points("xy")]
                    zero = len(pts) < 2 or all(_same(p, pts[0]) for p in pts)
                elif kind == "POLYLINE":
                    pts = [(v.dxf.location.x, v.dxf.location.y) for v in e.vertices]
                    zero = len(pts) < 2 or all(_same(p, pts[0]) for p in pts)
            except Exception:  # noqa: BLE001
                zero = False
            if zero:
                out.append(e)
    return out


def empty_text_entities(doc) -> list:
    out = []
    for layout in _layouts(doc):
        for e in layout:
            kind = e.dxftype()
            if kind not in ("TEXT", "MTEXT") or _locked(doc, e):
                continue
            try:
                text = e.plain_text() if kind == "MTEXT" else e.dxf.text
            except Exception:  # noqa: BLE001
                text = e.dxf.get("text", "") if kind == "TEXT" else e.text
            if not str(text).strip():
                out.append(e)
    return out


# -- the Command ---------------------------------------------------------------

def _table_for(doc, category: str):
    return {"layers": doc.layers, "ltypes": doc.linetypes,
            "textstyles": doc.styles, "dimstyles": doc.dimstyles,
            "regapps": doc.appids}[category]


class PurgeCommand(Command):
    """Remove the given unused items; undo puts every one of them back.

    ``items`` maps a category to names (or, for ``zero``/``empty``, to
    entities). Table entries are only unhooked from their table, so undo
    re-hooks the very same objects; a block's content is destroyed by
    ezdxf, so a copy of it is kept and rebuilt on undo (its handles change,
    which is the price of an unreferenced block).
    """

    name = "PURGE"
    touches_blocks = True
    needs_regen = True

    def __init__(self, items: dict[str, list]) -> None:
        self.items = {k: list(v) for k, v in items.items() if v}
        self._undo: list = []
        self.removed_handles: list[str] = []

    @property
    def count(self) -> int:
        return sum(len(v) for v in self.items.values())

    def do(self, document) -> None:
        doc = document.doc
        self._undo = []
        self.removed_handles = []
        for name in self.items.get("blocks", ()):
            block = doc.blocks.get(name)
            if block is None or not block.is_alive:
                continue
            copies = []
            for e in list(block):
                try:
                    copies.append(e.copy())
                except Exception:  # noqa: BLE001 - what cannot copy is lost
                    pass
            base = tuple(block.block.dxf.get("base_point", (0, 0, 0)))
            flags = int(block.block.dxf.get("flags", 0))
            self._undo.append(("block", name, base, flags, copies))
            doc.blocks.delete_block(name, safe=False)
        for category in ("zero", "empty"):
            for e in self.items.get(category, ()):
                if not e.is_alive:
                    continue
                try:
                    layout = doc.layouts.get_layout_for_entity(e)
                except Exception:  # noqa: BLE001
                    continue
                self.removed_handles.append(e.dxf.handle)
                layout.unlink_entity(e)
                self._undo.append(("entity", e, layout))
        for category in ("layers", "ltypes", "textstyles", "dimstyles", "regapps"):
            table = _table_for(doc, category)
            for name in self.items.get(category, ()):
                if not table.has_entry(name):
                    continue
                entry = table.get(name)
                table.discard(name)
                doc.entitydb.discard(entry)
                self._undo.append(("table", table, entry))
        for name in self.items.get("groups", ()):
            try:
                group = doc.groups.get(name)
            except Exception:  # noqa: BLE001
                group = None
            if group is None:
                continue
            record = (name, group.dxf.get("description", ""),
                      int(group.dxf.get("selectable", 1)),
                      [e.dxf.handle for e in group if e.is_alive])
            doc.groups.delete(name)
            self._undo.append(("group",) + record)
        for name in self.items.get("mleaderstyles", ()):
            style = doc.mleader_styles.get(name)
            if style is None:
                continue
            attribs = {k: v for k, v in style.dxfattribs().items()
                       if k not in ("handle", "owner", "name")}
            doc.mleader_styles.delete(name)
            self._undo.append(("mleaderstyle", name, attribs))
        document.dirty = True

    def undo(self, document) -> None:
        doc = document.doc
        for record in reversed(self._undo):
            kind = record[0]
            if kind == "block":
                _kind, name, base, flags, copies = record
                if name in doc.blocks:
                    continue
                block = doc.blocks.new(name, base_point=base,
                                       dxfattribs={"flags": flags})
                for c in copies:
                    block.add_entity(c.copy())
            elif kind == "entity":
                _kind, e, layout = record
                layout.add_entity(e)
            elif kind == "table":
                _kind, table, entry = record
                if not table.has_entry(entry.dxf.name):
                    table.add_entry(entry)
            elif kind == "group":
                _kind, name, description, selectable, handles = record
                group = doc.groups.new(name, description=description,
                                       selectable=bool(selectable))
                entities = [doc.entitydb.get(h) for h in handles]
                entities = [e for e in entities if e is not None and e.is_alive]
                if entities:
                    group.set_data(entities)
            elif kind == "mleaderstyle":
                _kind, name, attribs = record
                if doc.mleader_styles.get(name) is None:
                    style = doc.mleader_styles.new(name)
                    for key, value in attribs.items():
                        try:
                            style.dxf.set(key, value)
                        except Exception:  # noqa: BLE001
                            pass
        self._undo = []
        document.dirty = True


def match_names(names: Iterable[str], pattern: str) -> list[str]:
    """AutoCAD's name list: ``*`` for all, wildcards, several by comma."""
    pattern = (pattern or "").strip() or "*"
    wanted = [p.strip() for p in pattern.split(",") if p.strip()]
    out = []
    for name in names:
        if any(fnmatch.fnmatchcase(name.upper(), p.upper()) for p in wanted):
            out.append(name)
    return out


# -- the -PURGE prompt flow ----------------------------------------------------

def purge_command(document, history, *, echo, refresh, args=(),
                  nested: bool = False):
    """The -PURGE command: AutoCAD's prompts, one Command per run.

    ``-PURGE`` removes one level of reference (the reference says so), hence
    ``nested=False``; the dialog passes True for "Purge nested items".
    """
    from core.actions import Prompt
    from core.i18n import keywords

    queue = list(args)
    doc = document.doc

    def step(text, handler):
        if queue:
            return handler(queue.pop(0))
        return Prompt(text, handler)

    def purge(items: dict[str, list]) -> None:
        command = PurgeCommand(items)
        if command.count == 0:
            return
        history.execute(command)
        refresh()

    def none_found(category: str) -> None:
        echo(tr("No unreferenced {kind} found.", kind=tr(PLURALS[category])))

    def run_named(categories: list[str], pattern: str, verify: bool):
        found = candidates(doc, nested)
        chosen: dict[str, list[str]] = {}
        for category in categories:
            names = match_names(found.get(category, []), pattern)
            if not names:
                none_found(category)
                continue
            chosen[category] = names
        if not chosen:
            return None
        if not verify:
            for category, names in chosen.items():
                for name in names:
                    echo(tr('Deleting {kind} "{name}".',
                            kind=tr(NOUNS[category]), name=name))
            purge(chosen)
            return None
        pending = [(category, name) for category, names in chosen.items()
                   for name in names]
        accepted: dict[str, list[str]] = {}

        def ask_next():
            if not pending:
                if accepted:
                    purge(accepted)
                return None
            category, name = pending[0]
            return step(tr('Purge {kind} "{name}"? [Yes/No] <N>:',
                           kind=tr(NOUNS[category]), name=name), on_answer)

        def on_answer(text: str):
            category, name = pending.pop(0)
            source = 'Purge {kind} "{name}"? [Yes/No] <N>:'
            if keywords.match(text, source) == "Y":
                echo(tr('Deleting {kind} "{name}".',
                        kind=tr(NOUNS[category]), name=name))
                accepted.setdefault(category, []).append(name)
            return ask_next()

        return ask_next()

    def on_names(categories):
        def handler(text: str):
            pattern = text.strip() or "*"
            source = "Verify each name to be purged? [Yes/No] <Y>:"

            def on_verify(answer: str):
                verify = keywords.match(answer, source) != "N"
                return run_named(categories, pattern, verify)

            return step(tr(source), on_verify)
        return handler

    def run_unnamed(category: str):
        found = candidates(doc, nested).get(category, [])
        if not found:
            none_found(category)
            return None
        purge({category: found})
        echo(tr("{count} {kind} deleted.", count=len(found),
                kind=tr(PLURALS[category])))
        return None

    def on_type(text: str):
        key = keywords.match(text, PURGE_PROMPT)
        if key is None:
            echo(tr("Invalid option keyword."))
            return step(tr(PURGE_PROMPT), on_type)
        if key in UNSUPPORTED:
            echo(tr("No unreferenced {kind} found.", kind=tr(UNSUPPORTED[key])))
            return None
        category = _KEY_TO_CATEGORY[key]
        if category in UNNAMED:
            return run_unnamed(category)
        categories = list(NAMED) if category == "all" else [category]
        return step(tr("Enter name(s) to purge <*>:"), on_names(categories))

    return step(tr(PURGE_PROMPT), on_type)


# -- OVERKILL ------------------------------------------------------------------

OVERKILL_PROMPT = ("Enter an option to change [Ignore/Tolerance/Optimize plines/"
                   "Partial overlap/End to end/Associativity/Done] <Done>:")
IGNORE_PROMPT = ("Enter properties to ignore [Color/LAyer/LType/LTScale/"
                 "LWeight/Thickness/TRansparency/PLotstyle/MAterial/None] "
                 "<None>:")
#: Property option key -> the DXF attributes it compares.
IGNORABLE = {
    "C": ("color", "true_color"), "LA": ("layer",), "LT": ("linetype",),
    "LTS": ("ltscale",), "LW": ("lineweight",), "T": ("thickness",),
    "TR": ("transparency",), "PL": ("plotstyle_handle",),
    "MA": ("material_handle",),
}


@dataclass
class OverkillSettings:
    tolerance: float = 0.000001
    ignore: set[str] = field(default_factory=set)     # keys of IGNORABLE
    optimize_plines: bool = True
    ignore_widths: bool = False
    no_break: bool = False
    partial: bool = True
    end_to_end: bool = True
    associative: bool = True


@dataclass
class OverkillPlan:
    duplicates: list = field(default_factory=list)
    #: (old entities, factory(layout) -> new entity, objects/segments removed)
    merges: list = field(default_factory=list)

    @property
    def duplicate_count(self) -> int:
        return len(self.duplicates)

    @property
    def overlap_count(self) -> int:
        return sum(removed for _olds, _f, removed in self.merges)

    def empty(self) -> bool:
        return not self.duplicates and not self.merges


def _q(value: float, tol: float) -> int:
    return int(round(value / tol)) if tol > 0 else int(round(value * 1e9))


def _props(e, settings: OverkillSettings) -> tuple:
    skip = set()
    for key in settings.ignore:
        skip.update(IGNORABLE.get(key, ()))
    out = []
    for attr in ("layer", "color", "true_color", "linetype", "ltscale",
                 "lineweight", "thickness", "transparency",
                 "plotstyle_handle", "material_handle"):
        if attr in skip:
            continue
        out.append(str(e.dxf.get(attr, None)) if e.dxf.is_supported(attr) else None)
    return tuple(out)


def _pt(p, tol):
    return (_q(p[0], tol), _q(p[1], tol))


def _geometry_key(e, tol: float):
    kind = e.dxftype()
    dxf = e.dxf
    try:
        if kind == "LINE":
            a, b = _pt(dxf.start, tol), _pt(dxf.end, tol)
            return ("LINE", frozenset((a, b)))
        if kind == "CIRCLE":
            return ("CIRCLE", _pt(dxf.center, tol), _q(dxf.radius, tol))
        if kind == "ARC":
            return ("ARC", _pt(dxf.center, tol), _q(dxf.radius, tol),
                    _q(float(dxf.start_angle) % 360.0, 1e-6),
                    _q(float(dxf.end_angle) % 360.0, 1e-6))
        if kind == "LWPOLYLINE":
            pts = tuple((_pt(p, tol), _q(p[2], tol), _q(p[3], tol), _q(p[4], tol))
                        for p in e.get_points("xyseb"))
            return ("LWPOLYLINE", pts, bool(e.closed))
        if kind == "POINT":
            return ("POINT", _pt(dxf.location, tol))
        if kind == "TEXT":
            return ("TEXT", _pt(dxf.insert, tol), dxf.text, _q(dxf.height, tol),
                    _q(dxf.get("rotation", 0.0), 1e-6))
        if kind == "MTEXT":
            return ("MTEXT", _pt(dxf.insert, tol), e.text, _q(dxf.char_height, tol),
                    _q(dxf.get("rotation", 0.0), 1e-6))
        if kind == "INSERT":
            return ("INSERT", dxf.name, _pt(dxf.insert, tol),
                    _q(dxf.get("xscale", 1.0), 1e-9), _q(dxf.get("yscale", 1.0), 1e-9),
                    _q(dxf.get("rotation", 0.0), 1e-6))
        if kind == "ELLIPSE":
            return ("ELLIPSE", _pt(dxf.center, tol), _pt(dxf.major_axis, tol),
                    _q(dxf.ratio, 1e-9), _q(dxf.get("start_param", 0.0), 1e-9),
                    _q(dxf.get("end_param", math.tau), 1e-9))
        if kind == "SPLINE":
            return ("SPLINE", tuple(_pt(p, tol) for p in e.control_points),
                    int(dxf.get("degree", 3)))
    except Exception:  # noqa: BLE001 - malformed: never a duplicate
        return None
    return None


def _attribs(e) -> dict:
    out = e.dxfattribs()
    for key in ("handle", "owner", "reactors", "extension_dict"):
        out.pop(key, None)
    return out


def _merge_lines(lines, settings: OverkillSettings, tol: float) -> list:
    """Collinear LINEs of one property set -> [(olds, factory)]."""
    groups: dict[tuple, list] = {}
    for e in lines:
        sx, sy = e.dxf.start.x, e.dxf.start.y
        ex, ey = e.dxf.end.x, e.dxf.end.y
        dx, dy = ex - sx, ey - sy
        length = math.hypot(dx, dy)
        if length <= tol:
            continue
        dx, dy = dx / length, dy / length
        if dx < 0 or (abs(dx) <= 1e-12 and dy < 0):
            dx, dy = -dx, -dy
        offset = sx * dy - sy * dx            # signed distance of the line
        key = (_q(dx, 1e-9), _q(dy, 1e-9), _q(offset, tol))
        t0, t1 = sx * dx + sy * dy, ex * dx + ey * dy
        groups.setdefault(key, []).append((min(t0, t1), max(t0, t1), e, dx, dy, offset))
    out = []
    for members in groups.values():
        if len(members) < 2:
            continue
        members.sort(key=lambda m: m[0])
        run = [members[0]]
        runs = []
        for m in members[1:]:
            cur_end = max(r[1] for r in run)
            gap = m[0] - cur_end
            overlap = gap < -tol
            touching = abs(gap) <= tol
            if (overlap and settings.partial) or (touching and settings.end_to_end):
                run.append(m)
            else:
                runs.append(run)
                run = [m]
        runs.append(run)
        for run in runs:
            if len(run) < 2:
                continue
            t_min = min(r[0] for r in run)
            t_max = max(r[1] for r in run)
            _t0, _t1, first, dx, dy, offset = run[0]
            nx, ny = -dy, dx
            start = (t_min * dx + offset * nx, t_min * dy + offset * ny)
            end = (t_max * dx + offset * nx, t_max * dy + offset * ny)
            attribs = _attribs(first)
            attribs.pop("start", None)
            attribs.pop("end", None)
            z = float(first.dxf.start.z)

            def factory(layout, start=start, end=end, z=z, attribs=attribs):
                return layout.add_line((start[0], start[1], z),
                                       (end[0], end[1], z), dxfattribs=dict(attribs))
            out.append(([r[2] for r in run], factory, len(run) - 1))
    return out


def _merge_arcs(arcs, settings: OverkillSettings, tol: float) -> list:
    groups: dict[tuple, list] = {}
    for e in arcs:
        key = (_pt(e.dxf.center, tol), _q(e.dxf.radius, tol))
        start = float(e.dxf.start_angle) % 360.0
        span = (float(e.dxf.end_angle) - float(e.dxf.start_angle)) % 360.0
        if span == 0.0:
            span = 360.0
        groups.setdefault(key, []).append((start, start + span, e))
    out = []
    angle_tol = math.degrees(tol / max(1e-12, 1.0))    # tolerance in degrees
    for members in groups.values():
        if len(members) < 2:
            continue
        members.sort(key=lambda m: m[0])
        merged = []
        for m in members:
            if merged:
                cur = merged[-1]
                gap = m[0] - cur[1]
                overlap = gap < -angle_tol
                touching = abs(gap) <= angle_tol
                if (overlap and settings.partial) or (touching and settings.end_to_end):
                    merged[-1] = (cur[0], max(cur[1], m[1]), cur[2] + [m[2]])
                    continue
            merged.append((m[0], m[1], [m[2]]))
        # wrap-around: the last run may reach the first one past 360
        if len(merged) > 1:
            first, last = merged[0], merged[-1]
            gap = first[0] + 360.0 - last[1]
            if (gap < -angle_tol and settings.partial) or \
                    (abs(gap) <= angle_tol and settings.end_to_end):
                merged = [(last[0], max(last[1], first[1] + 360.0),
                           last[2] + first[2])] + merged[1:-1]
        for a0, a1, ents in merged:
            if len(ents) < 2:
                continue
            first = ents[0]
            attribs = _attribs(first)
            for key in ("start_angle", "end_angle"):
                attribs.pop(key, None)
            full = a1 - a0 >= 360.0 - angle_tol
            center = attribs.pop("center")
            radius = float(attribs.pop("radius", first.dxf.radius))

            def factory(layout, a0=a0, a1=a1, attribs=attribs, full=full,
                        center=center, radius=radius):
                if full:
                    return layout.add_circle(center, radius, dxfattribs=dict(attribs))
                return layout.add_arc(center, radius, a0 % 360.0, a1 % 360.0,
                                      dxfattribs=dict(attribs))
            out.append((ents, factory, len(ents) - 1))
    return out


def _optimize_polyline(e, settings: OverkillSettings, tol: float):
    """Drop repeated vertices and merge collinear straight segments."""
    try:
        pts = [list(p) for p in e.get_points("xyseb")]
    except Exception:  # noqa: BLE001
        return None
    if len(pts) < 3:
        return None
    out = [pts[0]]
    for p in pts[1:]:
        if _same(p, out[-1], tol):
            out[-1][2:] = p[2:]        # keep the later widths/bulge
            continue
        out.append(p)
    changed = len(out) != len(pts)
    i = 1
    while i < len(out) - 1:
        a, b, c = out[i - 1], out[i], out[i + 1]
        straight = abs(a[4]) <= 1e-12 and abs(b[4]) <= 1e-12
        same_width = settings.ignore_widths or (
            abs(a[2] - b[2]) <= 1e-12 and abs(a[3] - b[3]) <= 1e-12)
        cross = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        dot = (b[0] - a[0]) * (c[0] - b[0]) + (b[1] - a[1]) * (c[1] - b[1])
        if straight and same_width and abs(cross) <= tol * max(
                1.0, math.hypot(c[0] - a[0], c[1] - a[1])) and dot > 0:
            del out[i]
            changed = True
            continue
        i += 1
    if not changed:
        return None
    attribs = _attribs(e)
    for key in ("count", "points"):
        attribs.pop(key, None)
    closed = bool(e.closed)
    points = [tuple(p) for p in out]

    def factory(layout, points=points, closed=closed, attribs=attribs):
        return layout.add_lwpolyline(points, format="xyseb", close=closed,
                                     dxfattribs=dict(attribs))
    return factory, len(pts) - len(out)


def overkill_plan(entities, settings: Optional[OverkillSettings] = None) -> OverkillPlan:
    """What OVERKILL would do to ``entities``, without touching them."""
    settings = settings or OverkillSettings()
    tol = max(0.0, float(settings.tolerance))
    plan = OverkillPlan()
    seen: dict[tuple, object] = {}
    survivors = []
    for e in entities:
        if not getattr(e, "is_alive", True):
            continue
        key = _geometry_key(e, tol)
        if key is None:
            survivors.append(e)
            continue
        full = (key, _props(e, settings))
        if full in seen:
            plan.duplicates.append(e)
            continue
        seen[full] = e
        survivors.append(e)
    by_props: dict[tuple, dict[str, list]] = {}
    for e in survivors:
        kind = e.dxftype()
        if kind in ("LINE", "ARC"):
            by_props.setdefault(_props(e, settings), {}).setdefault(kind, []).append(e)
    if settings.partial or settings.end_to_end:
        for kinds in by_props.values():
            plan.merges.extend(_merge_lines(kinds.get("LINE", []), settings, tol))
            plan.merges.extend(_merge_arcs(kinds.get("ARC", []), settings, tol))
    if settings.optimize_plines:
        for e in survivors:
            if e.dxftype() == "LWPOLYLINE":
                optimized = _optimize_polyline(e, settings, tol)
                if optimized is not None:
                    factory, removed = optimized
                    plan.merges.append(([e], factory, removed))
    return plan


def overkill_command(plan: OverkillPlan) -> Optional[Command]:
    """One undoable OVERKILL step, or None when there is nothing to do."""
    from core.actions import EraseCommand, ReplaceEntitiesCommand
    from core.commands import CompositeCommand

    commands = []
    if plan.duplicates:
        commands.append(EraseCommand(plan.duplicates))
    for olds, factory, _removed in plan.merges:
        commands.append(ReplaceEntitiesCommand("OVERKILL", olds, [factory]))
    if not commands:
        return None
    if len(commands) == 1:
        command = commands[0]
        command.name = "OVERKILL"
        return command
    return CompositeCommand("OVERKILL", commands)


# -- WBLOCK --------------------------------------------------------------------

WBLOCK_PROMPT = ("Enter name of existing block or "
                 "[= (block=output file)/* (whole drawing)] <define new drawing>:")


def write_block_file(document, path, *, block_name: Optional[str] = None,
                     entities: Optional[list] = None,
                     base_point=(0.0, 0.0, 0.0), whole: bool = False) -> int:
    """Write a block, a selection or the whole drawing to a new file.

    A block or a selection lands in the new drawing's modelspace with
    ``base_point`` at the origin (AutoCAD: the block's base point becomes
    the drawing's insertion base). Layers, linetypes, styles and nested
    blocks travel along (ezdxf's Importer brings only what is used, which
    is AutoCAD's "except unreferenced symbols"). Returns how many entities
    were written. ``.dwg`` goes through the same LibreDWG path as Save As.
    """
    import ezdxf
    from ezdxf.addons import Importer
    from pathlib import Path

    from core.document import Document

    path = Path(path)
    source = document.doc
    version = source.dxfversion if source.dxfversion >= "AC1015" else "AC1015"
    target = ezdxf.new(version)
    for key in ("$INSUNITS", "$MEASUREMENT", "$LUNITS", "$LUPREC", "$AUNITS",
                "$AUPREC", "$LTSCALE"):
        try:
            target.header[key] = source.header[key]
        except Exception:  # noqa: BLE001
            pass
    importer = Importer(source, target)
    count = 0
    if whole:
        importer.import_modelspace()
        importer.import_paperspace_layouts()
        importer.finalize()
        count = len(target.modelspace())
    else:
        if block_name is not None:
            block = source.blocks.get(block_name)
            if block is None:
                raise KeyError(block_name)
            entities = list(block)
            base_point = tuple(block.block.dxf.get("base_point", (0, 0, 0)))
        entities = [e for e in (entities or []) if e.is_alive]
        msp = target.modelspace()
        importer.import_entities(entities, msp)
        importer.finalize()
        bx, by, bz = (list(base_point) + [0.0, 0.0, 0.0])[:3]
        if bx or by or bz:
            for e in msp:
                try:
                    e.translate(-bx, -by, -bz)
                except Exception:  # noqa: BLE001 - what cannot move stays
                    pass
        count = len(msp)
    target.header["$INSBASE"] = (0.0, 0.0, 0.0)
    Document(target).save_as(path)
    return count
