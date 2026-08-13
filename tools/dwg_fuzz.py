# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Track L2 harness: round-trip fuzzing of the LibreDWG *write* path.

``dwg_bench.py`` sweeps real DWGs through ``dwg2dxf`` (the read path). This is
the complement for the write path, which has no real-world corpus to lean on:
*generate* seeded DXF drawings with ezdxf, write them to DWG with ``dxf2dwg``,
read them back with ``dwg2dxf``, reload with ezdxf, and compare the modelspace
entity by entity. Anything that does not survive the trip is a LibreDWG bug in
the DXF importer, the DWG writer or the DWG reader — or a harness
false positive, which triage must rule out first (linetype-name case, default
materialization and float noise are the expected offenders).

Every drawing is derived deterministically from its integer seed via an
intermediate *spec* (a JSON-able list of entity descriptions), so a failure
can be reproduced from the seed alone and *reduced* by dropping spec entries
without disturbing the generation of the survivors.

Usage:
    python tools/dwg_fuzz.py run --count 500 [--seed 0] [--workers 6]
                                 [--out report.csv] [--fails <dir>]
    python tools/dwg_fuzz.py repro <seed> [--fails <dir>]
    python tools/dwg_fuzz.py reduce <seed> --fails <dir>

Categories:
    OK              every fingerprint matched
    GEN_FAIL        ezdxf refused to build/save the drawing (harness bug)
    DXF2DWG_*       SEGV / ERR / TIMEOUT / EMPTY from the DXF->DWG step
    DWG2DXF_*       SEGV / ERR / TIMEOUT / EMPTY from the DWG->DXF step
    RELOAD_FAIL     ezdxf recover could not read the returned DXF
    LOST / EXTRA    per-type entity counts differ after the trip
    DIFF            counts match but entity attributes drifted
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from random import Random

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TIMEOUT = 60  # seconds per conversion
ROUND = 4     # decimals kept in fingerprints (abs tolerance 1e-4 drawing units)

SOURCE_VERSIONS = ["R2000", "R2004", "R2007", "R2010", "R2013", "R2018", "R12"]
TARGET_VERSIONS = ["r2000"] * 6 + ["r2004"] * 2 + ["r14"] + ["r12"]

# entities expressible in an R12 DXF (no LWPOLYLINE/MTEXT/SPLINE/ELLIPSE/
# HATCH/XLINE/RAY/DIMENSION-render blocks)
R12_KINDS = ["LINE", "POINT", "CIRCLE", "ARC", "TEXT", "SOLID", "3DFACE",
             "POLYLINE3D", "INSERT"]

LAYER_NAMES = ["MUROS", "EJES", "CAÑERÍAS", "COTAS 2", "L-01", "puntos_topo"]
LINETYPES = ["CONTINUOUS", "DASHED", "CENTER", "DASHDOT"]
TEXT_POOL = [
    "PLANTA GENERAL",
    "CAÑERÍA Ø150 PVC",
    "N.P.T. +2.45 m²",
    "AREA=125.40m2 100%%d",
    "esc: 1/500 \"indicada\"",
    "eje ^ referencia 45°",
    "Ñandú é ü — cota",
    "A" * 260,  # forces MTEXT chunking / long TV strings
]
BLOCK_NAMES = ["FZB0", "FZB1", "FZB2"]

# ---------------------------------------------------------------------------
# generation: seed -> spec -> ezdxf document
# ---------------------------------------------------------------------------

BASES = [(0.0, 0.0), (229_000.0, 8_252_000.0), (-1_234.5, 6_789.0)]


def _pt(rng: Random, base, spread=200.0, z=0.0):
    return [round(base[0] + rng.uniform(-spread, spread), 6),
            round(base[1] + rng.uniform(-spread, spread), 6),
            round(z, 6)]


def _maybe_z(rng: Random):
    return rng.uniform(-50, 4_500) if rng.random() < 0.25 else 0.0


#: Lineweights AutoCAD accepts, in 1/100 mm, plus the three special values.
LINEWEIGHTS = [-3, -2, -1, 0, 5, 13, 25, 35, 50, 70, 100, 158, 211]

#: XDATA application names — the "another app wrote here" case that IngeCAD's
#: conservative round-trip promises to preserve untouched.
XDATA_APPS = ["ACAD", "INGECAD_TEST", "AEC_MODIFY", "CIVIL3D_XD"]


def _gen_xdata(rng: Random) -> list:
    """One XDATA group list, mixing the code types real files carry.

    Deliberately excludes 1005 (handle) and 1003 (layer name), which name
    other objects and may legitimately be re-resolved by a converter.
    """
    items = [(1000, rng.choice(["eje", "cota", "PT-14", "área"]))]
    for _ in range(rng.randrange(1, 5)):
        c = rng.choice([1000, 1040, 1070, 1071, 1010, 1041, 1042])
        if c == 1000:
            items.append((c, rng.choice(["norte", "bm-1", "revisión B"])))
        elif c in (1040, 1041, 1042):
            items.append((c, round(rng.uniform(-1e4, 1e4), 4)))
        elif c == 1070:
            items.append((c, rng.randrange(-32768, 32768)))
        elif c == 1071:
            items.append((c, rng.randrange(-2 ** 31, 2 ** 31)))
        else:
            items.append((c, (round(rng.uniform(-500, 500), 4),
                              round(rng.uniform(-500, 500), 4),
                              round(rng.uniform(-50, 50), 4))))
    return items


def _tilted_normal(rng: Random):
    """A genuine OCS extrusion — not just the [0,0,-1] flip already covered.

    Real plans carry these (a circle drawn on a rotated UCS), and the arbitrary
    axis algorithm is where converters trip.
    """
    import math as _m

    theta = rng.uniform(0.15, _m.pi / 2)     # away from +Z, never degenerate
    phi = rng.uniform(0, 2 * _m.pi)
    return [round(_m.sin(theta) * _m.cos(phi), 6),
            round(_m.sin(theta) * _m.sin(phi), 6),
            round(_m.cos(theta), 6)]


def _common(rng: Random, header) -> dict:
    d: dict = {"layer": rng.randrange(len(header["layers"]))}
    p = rng.random()
    if p < 0.55:
        d["color"] = 256          # ByLayer
    elif p < 0.65:
        d["color"] = 0            # ByBlock
    else:
        d["color"] = rng.randrange(1, 256)
    if header["target"] == "r2004" and rng.random() < 0.15:
        d["true_color"] = [rng.randrange(256) for _ in range(3)]
    if rng.random() < 0.3:
        d["ltype"] = rng.choice(LINETYPES)
    if rng.random() < 0.2:
        d["ltscale"] = round(rng.uniform(0.01, 100.0), 4)
    # Lineweight is an R2000+ entity property; an R12 source has nowhere to
    # put it and an r12 target nowhere to keep it.
    if (header["version"] != "R12" and header["target"] not in ("r12", "r14")
            and rng.random() < 0.3):
        d["lineweight"] = rng.choice(LINEWEIGHTS)
    if header["version"] != "R12" and rng.random() < 0.25:
        d["xdata"] = [rng.choice(XDATA_APPS), _gen_xdata(rng)]
    return d


def gen_specs(seed: int) -> tuple[dict, list[dict]]:
    rng = Random(seed)
    header = {
        "seed": seed,
        "version": rng.choice(SOURCE_VERSIONS),
        "target": rng.choice(TARGET_VERSIONS),
        "base": rng.choice(BASES),
        "layers": [["0", 7, "CONTINUOUS"]] + [
            [name, rng.randrange(1, 256), rng.choice(LINETYPES)]
            for name in rng.sample(LAYER_NAMES, rng.randrange(1, 4))
        ],
        "blocks": [],
    }
    # 0-3 block definitions; the last may nest an insert of the first
    blk_kinds = (["LINE", "CIRCLE", "TEXT"] if header["version"] == "R12"
                 else ["LINE", "CIRCLE", "TEXT", "LWPOLYLINE"])
    for bi in range(rng.randrange(0, 4)):
        ents = []
        for _ in range(rng.randrange(1, 4)):
            kind = rng.choice(blk_kinds)
            ents.append(_gen_entity(rng, header, kind, spread=10.0))
        if rng.random() < 0.3:
            ents.append({"t": "ATTDEF", "layer": 0, "color": 256,
                         "tag": f"DEF{bi}", "text": rng.choice(TEXT_POOL[:5]),
                         "prompt": "value?", "insert": _pt(rng, (0, 0), 5),
                         "height": round(rng.uniform(0.5, 5), 4)})
        if bi == 2 and rng.random() < 0.5:
            ents.append({"t": "INSERT", "layer": 0, "color": 256,
                         "name": BLOCK_NAMES[0], "insert": _pt(rng, (0, 0), 5),
                         "xscale": 1.0, "yscale": 1.0, "zscale": 1.0,
                         "rotation": round(rng.uniform(0, 360), 4),
                         "attribs": []})
        header["blocks"].append(ents)

    if header["version"] == "R12" or header["target"] == "r12":
        kinds = list(R12_KINDS)
        if not header["blocks"]:
            kinds.remove("INSERT")
    else:
        kinds = ["LINE", "LINE", "LINE", "POINT", "CIRCLE", "ARC", "ELLIPSE",
                 "LWPOLYLINE", "LWPOLYLINE", "POLYLINE3D", "TEXT", "TEXT",
                 "MTEXT", "SOLID", "3DFACE", "SPLINE", "HATCH", "XLINE",
                 "RAY", "DIMLINEAR", "LEADER"]
        if header["blocks"]:
            kinds += ["INSERT", "INSERT", "INSERT", "MINSERT"]
    entities = [_gen_entity(rng, header, rng.choice(kinds))
                for _ in range(rng.randrange(5, 41))]
    return header, entities


def _gen_entity(rng: Random, header, kind: str, spread=200.0) -> dict:
    base = header["base"]
    d = _common(rng, header)
    d["t"] = kind
    z = _maybe_z(rng)
    if kind == "LINE":
        d["start"] = _pt(rng, base, spread, z)
        d["end"] = _pt(rng, base, spread, _maybe_z(rng))
        if rng.random() < 0.1:
            d["extrusion"] = _tilted_normal(rng)
    elif kind == "POINT":
        d["loc"] = _pt(rng, base, spread, z)
    elif kind in ("CIRCLE", "ARC"):
        d["center"] = _pt(rng, base, spread, z)
        d["radius"] = round(rng.choice(
            [rng.uniform(0.001, 1), rng.uniform(1, 500), 1e6 * rng.random() + 1]), 6)
        if kind == "ARC":
            a = rng.uniform(0, 360)
            d["start_angle"] = round(a, 4)
            d["end_angle"] = round((a + rng.uniform(1, 359)) % 360, 4)
        if rng.random() < 0.15:
            d["extrusion"] = [0, 0, -1]
        elif rng.random() < 0.12:
            d["extrusion"] = _tilted_normal(rng)
    elif kind == "ELLIPSE":
        d["center"] = _pt(rng, base, spread, z)
        d["major_axis"] = [round(rng.uniform(1, 300), 6),
                           round(rng.uniform(1, 300), 6), 0]
        d["ratio"] = round(rng.uniform(0.05, 1.0), 6)
        d["start_param"] = 0.0
        d["end_param"] = round(rng.uniform(0.5, 2 * math.pi), 6)
    elif kind == "LWPOLYLINE":
        n = rng.randrange(2, 9)
        d["points"] = [
            _pt(rng, base, spread)[:2]
            + [round(rng.uniform(-2, 2), 4) if rng.random() < 0.3 else 0.0]
            for _ in range(n)]
        d["closed"] = rng.random() < 0.5
        if rng.random() < 0.25:
            d["const_width"] = round(rng.uniform(0.05, 5.0), 4)
        if rng.random() < 0.2:
            d["elevation"] = round(z, 6)
    elif kind == "POLYLINE3D":
        d["points"] = [_pt(rng, base, spread, _maybe_z(rng))
                       for _ in range(rng.randrange(2, 7))]
    elif kind == "TEXT":
        d["text"] = rng.choice(TEXT_POOL[:-1])
        d["insert"] = _pt(rng, base, spread, z)
        d["height"] = round(rng.uniform(0.1, 50), 4)
        d["rotation"] = round(rng.uniform(0, 360), 4)
        if rng.random() < 0.1:
            d["extrusion"] = [0, 0, -1]
    elif kind == "MTEXT":
        parts = rng.sample(TEXT_POOL, rng.randrange(1, 4))
        d["text"] = "\\P".join(parts)
        d["insert"] = _pt(rng, base, spread, z)
        d["char_height"] = round(rng.uniform(0.1, 20), 4)
        d["width"] = round(rng.uniform(10, 500), 4)
    elif kind in ("SOLID", "3DFACE"):
        p0 = _pt(rng, base, spread, z if kind == "3DFACE" else 0.0)
        pts = [p0]
        for _ in range(3):
            q = [p0[0] + rng.uniform(-30, 30), p0[1] + rng.uniform(-30, 30),
                 p0[2] if kind == "SOLID" else _maybe_z(rng)]
            pts.append([round(v, 6) for v in q])
        d["corners"] = pts
    elif kind == "SPLINE":
        n = rng.randrange(3, 9)
        d["degree"] = rng.choice([2, 3])
        d["mode"] = rng.choice(["fit", "control"])
        d["points"] = [_pt(rng, base, spread, _maybe_z(rng)) for _ in range(n)]
    elif kind == "HATCH":
        d["solid"] = rng.random() < 0.5
        if not d["solid"]:
            d["pattern"] = rng.choice(["ANSI31", "ANSI37", "NET"])
            d["scale"] = round(rng.uniform(0.1, 50), 4)
            d["angle"] = round(rng.uniform(0, 180), 4)
        c = _pt(rng, base, spread)
        w, h = rng.uniform(5, 100), rng.uniform(5, 100)
        d["path"] = [[c[0], c[1], 0.0], [round(c[0] + w, 6), c[1],
                     round(rng.uniform(-1, 1), 4) if rng.random() < 0.3 else 0.0],
                     [round(c[0] + w, 6), round(c[1] + h, 6), 0.0],
                     [c[0], round(c[1] + h, 6), 0.0]]
    elif kind in ("XLINE", "RAY"):
        d["start"] = _pt(rng, base, spread, z)
        a = rng.uniform(0, 2 * math.pi)
        d["unit"] = [round(math.cos(a), 9), round(math.sin(a), 9), 0.0]
    elif kind in ("INSERT", "MINSERT"):
        d["name"] = BLOCK_NAMES[rng.randrange(len(header["blocks"]))]
        d["insert"] = _pt(rng, base, spread, z)
        d["xscale"] = round(rng.choice([1.0, rng.uniform(0.01, 20),
                                        -rng.uniform(0.5, 2)]), 6)
        d["yscale"] = round(rng.choice([d["xscale"], rng.uniform(0.01, 20)]), 6)
        d["zscale"] = 1.0
        d["rotation"] = round(rng.uniform(0, 360), 4)
        d["attribs"] = []
        if kind == "MINSERT":
            d["rows"] = rng.randrange(2, 5)
            d["cols"] = rng.randrange(1, 5)
            d["row_spacing"] = round(rng.uniform(5, 50), 4)
            d["col_spacing"] = round(rng.uniform(5, 50), 4)
        elif rng.random() < 0.3:
            for i in range(rng.randrange(1, 3)):
                d["attribs"].append(
                    [f"TAG{i}", rng.choice(TEXT_POOL[:5]),
                     _pt(rng, d["insert"][:2], 5)])
    elif kind == "DIMLINEAR":
        p1 = _pt(rng, base, spread)
        p2 = _pt(rng, base, spread)
        d["p1"], d["p2"] = p1[:2], p2[:2]
        d["base"] = [round((p1[0] + p2[0]) / 2, 6),
                     round(max(p1[1], p2[1]) + rng.uniform(5, 60), 6)]
        d["angle"] = rng.choice([0.0, 90.0, round(rng.uniform(0, 360), 4)])
        d["text"] = rng.choice(["<>", "<>", "<> m", " "])
    elif kind == "LEADER":
        d["points"] = [_pt(rng, base, spread)
                       for _ in range(rng.randrange(2, 6))]
    return d


def build_doc(header: dict, entities: list[dict]):
    import ezdxf

    doc = ezdxf.new(dxfversion=header["version"], setup=True)
    for name, color, ltype in header["layers"]:
        if name != "0":
            doc.layers.add(name, color=color, linetype=ltype)
        else:
            doc.layers.get("0").color = color
    for bi, ents in enumerate(header["blocks"]):
        blk = doc.blocks.new(name=BLOCK_NAMES[bi])
        for spec in ents:
            _add_entity(blk, spec, header)
    msp = doc.modelspace()
    for spec in entities:
        _add_entity(msp, spec, header)
    return doc


def _add_entity(layout, d: dict, header) -> None:
    at = {"layer": header["layers"][d["layer"]][0], "color": d["color"]}
    if "true_color" in d:
        r, g, b = d["true_color"]
        at["true_color"] = (r << 16) | (g << 8) | b
    if "ltype" in d:
        at["linetype"] = d["ltype"]
    if "ltscale" in d:
        at["ltscale"] = d["ltscale"]
    if "lineweight" in d:
        at["lineweight"] = d["lineweight"]
    t = d["t"]
    entity = _make_entity(layout, d, header, at, t)
    if entity is not None and "xdata" in d:
        app, items = d["xdata"]
        doc = layout.doc
        if app not in doc.appids:
            doc.appids.add(app)
        entity.set_xdata(app, list(items))


def _make_entity(layout, d: dict, header, at: dict, t: str):
    if t == "LINE":
        if "extrusion" in d:
            at["extrusion"] = d["extrusion"]
        return layout.add_line(d["start"], d["end"], dxfattribs=at)
    elif t == "POINT":
        return layout.add_point(d["loc"], dxfattribs=at)
    elif t == "CIRCLE":
        if "extrusion" in d:
            at["extrusion"] = d["extrusion"]
        return layout.add_circle(d["center"], d["radius"], dxfattribs=at)
    elif t == "ARC":
        if "extrusion" in d:
            at["extrusion"] = d["extrusion"]
        return layout.add_arc(d["center"], d["radius"], d["start_angle"],
                       d["end_angle"], dxfattribs=at)
    elif t == "ELLIPSE":
        return layout.add_ellipse(d["center"], d["major_axis"], d["ratio"],
                           d["start_param"], d["end_param"], dxfattribs=at)
    elif t == "LWPOLYLINE":
        if "const_width" in d:
            at["const_width"] = d["const_width"]
        if "elevation" in d:
            at["elevation"] = d["elevation"]
        return layout.add_lwpolyline(d["points"], format="xyb",
                              close=d["closed"], dxfattribs=at)
    elif t == "POLYLINE3D":
        return layout.add_polyline3d(d["points"], dxfattribs=at)
    elif t == "TEXT":
        at["insert"] = d["insert"]
        at["height"] = d["height"]
        at["rotation"] = d["rotation"]
        if "extrusion" in d:
            at["extrusion"] = d["extrusion"]
        return layout.add_text(d["text"], dxfattribs=at)
    elif t == "MTEXT":
        at["insert"] = d["insert"]
        at["char_height"] = d["char_height"]
        at["width"] = d["width"]
        return layout.add_mtext(d["text"], dxfattribs=at)
    elif t == "SOLID":
        return layout.add_solid(d["corners"], dxfattribs=at)
    elif t == "3DFACE":
        return layout.add_3dface(d["corners"], dxfattribs=at)
    elif t == "SPLINE":
        if d["mode"] == "fit":
            return layout.add_spline(d["points"], degree=d["degree"], dxfattribs=at)
        else:
            return layout.add_open_spline(d["points"], degree=d["degree"],
                                   dxfattribs=at)
    elif t == "HATCH":
        h = layout.add_hatch(dxfattribs=at)
        if d["solid"]:
            h.set_solid_fill(color=d["color"] if d["color"] not in (0, 256) else 7)
        else:
            h.set_pattern_fill(d["pattern"], scale=d["scale"], angle=d["angle"])
        h.paths.add_polyline_path(
            [(p[0], p[1], p[2]) for p in d["path"]], is_closed=True)
        return h
    elif t == "XLINE":
        return layout.add_xline(d["start"], d["unit"], dxfattribs=at)
    elif t == "RAY":
        return layout.add_ray(d["start"], d["unit"], dxfattribs=at)
    elif t in ("INSERT", "MINSERT"):
        at.update(xscale=d["xscale"], yscale=d["yscale"], zscale=d["zscale"],
                  rotation=d["rotation"])
        ref = layout.add_blockref(d["name"], d["insert"], dxfattribs=at)
        if t == "MINSERT":
            ref.grid(size=(d["rows"], d["cols"]),
                     spacing=(d["row_spacing"], d["col_spacing"]))
        for tag, text, ins in d["attribs"]:
            ref.add_attrib(tag, text, ins)
        return ref
    elif t == "ATTDEF":
        at.update(insert=d["insert"], height=d["height"], prompt=d["prompt"],
                  tag=d["tag"])
        return layout.add_attdef(d["tag"], text=d["text"], dxfattribs=at)
    elif t == "DIMLINEAR":
        dim = layout.add_linear_dim(base=d["base"], p1=d["p1"], p2=d["p2"],
                                    angle=d["angle"], text=d["text"],
                                    dxfattribs=at)
        dim.render()
        # the DIMENSION itself carries the xdata; its rendered block does not
        return dim.dimension if hasattr(dim, "dimension") else None
    elif t == "LEADER":
        return layout.add_leader(d["points"], dxfattribs=at)


# ---------------------------------------------------------------------------
# fingerprints: what must survive the round trip
# ---------------------------------------------------------------------------

def _r(v):
    return round(float(v), ROUND)


def _rp(p):
    return (_r(p[0]), _r(p[1]), _r(p[2]) if len(p) > 2 else 0.0)


def _fp_xdata(e):
    """The XDATA of the apps this harness writes, normalized for comparison.

    Only our own appids are compared: ACAD's own groups are rewritten by every
    converter by design (ACAD_DSTYLE, dimension overrides), and other apps'
    are not something the generator controls.
    """
    xdata = getattr(e, "xdata", None)
    if xdata is None:
        return None
    out = []
    for app in sorted(XDATA_APPS):
        if app == "ACAD":
            continue
        try:
            tags = xdata.get(app)
        except Exception:
            continue
        if not tags:
            continue
        items = []
        for code, value in tags:
            if code == 1001:
                continue                       # the appid marker itself
            if code in (1010, 1011, 1012, 1013):
                items.append((code, _rp(value)))
            elif code in (1040, 1041, 1042):
                items.append((code, _r(value)))
            else:
                items.append((code, value))
        out.append((app, tuple(items)))
    return tuple(out) or None


def _fp_common(e):
    dxf = e.dxf
    return (dxf.layer.upper(),
            dxf.color,
            dxf.true_color if dxf.hasattr("true_color") else None,
            dxf.linetype.upper(),
            _r(dxf.ltscale),
            # An absent group 370 means BYLAYER (-1) per the DXF reference, so
            # an explicit -1 and no group at all are the same statement; the
            # normalization keeps a converter that spells out the default from
            # reading as a difference. Anything else stated must survive.
            dxf.lineweight if dxf.hasattr("lineweight") else -1,
            _fp_xdata(e))


def fingerprint(e):
    t = e.dxftype()
    c = _fp_common(e)
    d = e.dxf
    if t == "LINE":
        g = (_rp(d.start), _rp(d.end), _rp(d.extrusion))
    elif t == "POINT":
        g = (_rp(d.location),)
    elif t == "CIRCLE":
        g = (_rp(d.center), _r(d.radius), _rp(d.extrusion))
    elif t == "ARC":
        g = (_rp(d.center), _r(d.radius), _r(d.start_angle),
             _r(d.end_angle), _rp(d.extrusion))
    elif t == "ELLIPSE":
        g = (_rp(d.center), _rp(d.major_axis), _r(d.ratio),
             _r(d.start_param), _r(d.end_param))
    elif t == "LWPOLYLINE":
        g = (e.closed, _r(d.const_width), _r(d.elevation),
             tuple((_r(x), _r(y), _r(b)) for x, y, b in e.get_points("xyb")))
    elif t == "POLYLINE":
        g = (e.is_3d_polyline, e.is_closed,
             tuple(_rp(v.dxf.location) for v in e.vertices))
    elif t == "TEXT":
        g = (d.text, _rp(d.insert), _r(d.height), _r(d.rotation),
             _rp(d.extrusion))
    elif t == "MTEXT":
        g = (e.text, _rp(d.insert), _r(d.char_height))
    elif t in ("SOLID", "3DFACE"):
        g = (_rp(d.vtx0), _rp(d.vtx1), _rp(d.vtx2), _rp(d.vtx3))
    elif t == "SPLINE":
        g = (d.degree, e.closed, len(e.control_points), len(e.fit_points))
    elif t == "HATCH":
        g = (d.pattern_name.upper(), d.solid_fill, len(e.paths))
    elif t in ("INSERT", "MINSERT"):
        t = "INSERT"  # ezdxf may expose a grid INSERT under either name
        g = (d.name.upper(), _rp(d.insert), _r(d.xscale), _r(d.yscale),
             _r(d.rotation),
             d.get("row_count", 1), d.get("column_count", 1),
             _r(d.get("row_spacing", 0)), _r(d.get("column_spacing", 0)),
             tuple(sorted((a.dxf.tag, a.dxf.text) for a in e.attribs)))
    elif t in ("XLINE", "RAY"):
        g = (_rp(d.start), _rp(d.unit_vector))
    elif t == "ATTDEF":
        g = (d.tag, d.text, _rp(d.insert), _r(d.height))
    elif t == "DIMENSION":
        # loose on purpose: geometry lives in the *D block, styles vary
        g = (d.dimtype & 7, d.get("dimstyle", "").upper(), _rp(d.defpoint),
             d.get("text", ""))
    elif t == "LEADER":
        g = (tuple(_rp(v) for v in e.vertices),)
    else:
        g = ()
    return (t,) + c + g


def fingerprints(msp) -> Counter:
    return Counter(fingerprint(e) for e in msp
                   if e.dxftype() not in ("SEQEND", "ATTRIB"))


def block_fingerprints(doc) -> dict:
    """Per-block entity fingerprints. Anonymous/layout blocks excluded."""
    out = {}
    for b in doc.blocks:
        name = b.name.upper()
        if name.startswith(("*", "$")):
            continue
        out[name] = Counter(fingerprint(e) for e in b
                            if e.dxftype() not in ("SEQEND", "ATTRIB"))
    return out


# ---------------------------------------------------------------------------
# the round trip
# ---------------------------------------------------------------------------

def _convert(cmd: list[str], out: Path) -> tuple[str, str]:
    """Run a converter. Returns (failure-category-suffix or '', signature)."""
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=TIMEOUT,
                              encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return "TIMEOUT", ""
    sig = ""
    for line in reversed((proc.stderr or "").strip().splitlines()):
        if "ERROR" in line or "Segmentation" in line:
            sig = line.strip()[:160]
            break
    if proc.returncode < 0:
        return "SEGV", f"signal {-proc.returncode}: {sig}"
    if not out.is_file() or out.stat().st_size == 0:
        return "EMPTY", sig or f"rc={proc.returncode}"
    return "", sig


def run_trip(header: dict, entities: list[dict], workdir: Path,
             dxf2dwg: str, dwg2dxf: str) -> dict:
    """Build, convert out and back, compare. Returns a result row."""
    from ezdxf import recover

    row = {"seed": header["seed"], "version": header["version"],
           "target": header["target"], "n": len(entities),
           "category": "?", "signature": ""}
    gen_dxf = workdir / "gen.dxf"
    gen_dwg = workdir / "gen.dwg"
    back_dxf = workdir / "back.dxf"

    try:
        doc = build_doc(header, entities)
        doc.saveas(gen_dxf)
    except Exception as exc:
        row.update(category="GEN_FAIL",
                   signature=f"{type(exc).__name__}: {str(exc)[:140]}")
        return row

    fail, sig = _convert([dxf2dwg, "-y", "--as", header["target"],
                          "-o", str(gen_dwg), str(gen_dxf)], gen_dwg)
    if fail:
        row.update(category=f"DXF2DWG_{fail}", signature=sig)
        return row

    fail, sig = _convert([dwg2dxf, "-y", "-o", str(back_dxf), str(gen_dwg)],
                         back_dxf)
    if fail:
        row.update(category=f"DWG2DXF_{fail}", signature=sig)
        return row

    try:
        doc_a, _ = recover.readfile(gen_dxf)
        doc_b, _ = recover.readfile(back_dxf)
    except Exception as exc:
        row.update(category="RELOAD_FAIL",
                   signature=f"{type(exc).__name__}: {str(exc)[:140]}")
        return row

    fp_a = fingerprints(doc_a.modelspace())
    fp_b = fingerprints(doc_b.modelspace())
    if fp_a == fp_b:
        blk_a = block_fingerprints(doc_a)
        blk_b = block_fingerprints(doc_b)
        if blk_a == blk_b:
            row["category"] = "OK"
            return row
        # blocks only in the output are tolerated: LibreDWG materializes
        # the standard arrowhead definitions (_CLOSEDFILLED & co.) that a
        # DXF may reference by name without defining
        bad = [n for n in blk_a if blk_a.get(n) != blk_b.get(n)]
        if not bad:
            row["category"] = "OK"
            return row
        row["category"] = "BLOCKDIFF"
        row["signature"] = ",".join(sorted(bad))[:160]
        row["missing"] = Counter()
        row["extra"] = Counter()
        for n in bad:
            a, b = blk_a.get(n, Counter()), blk_b.get(n, Counter())
            for fp, cnt in (a - b).items():
                row["missing"][(n,) + fp] = cnt
            for fp, cnt in (b - a).items():
                row["extra"][(n,) + fp] = cnt
        return row

    missing = fp_a - fp_b   # in the original, absent after the trip
    extra = fp_b - fp_a
    types_a = Counter(fp[0] for fp in fp_a.elements())
    types_b = Counter(fp[0] for fp in fp_b.elements())
    if types_a != types_b:
        lost = types_a - types_b
        gained = types_b - types_a
        row["category"] = "LOST" if lost else "EXTRA"
        row["signature"] = ("lost " + ",".join(f"{k}×{v}" for k, v in lost.items())
                           + ("; gained " + ",".join(f"{k}×{v}" for k, v in gained.items())
                              if gained else ""))[:160]
    else:
        row["category"] = "DIFF"
        row["signature"] = ",".join(sorted({fp[0] for fp in missing}))[:160]
    row["missing"] = missing
    row["extra"] = extra
    return row


def save_artifacts(row: dict, header, entities, workdir: Path, fails: Path):
    dest = fails / row["category"] / str(row["seed"])
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("gen.dxf", "gen.dwg", "back.dxf"):
        src = workdir / name
        if src.is_file():
            shutil.copy2(src, dest / name)
    (dest / "spec.json").write_text(
        json.dumps({"header": header, "entities": entities},
                   ensure_ascii=False, indent=1))
    lines = [f"seed {row['seed']}  {row['version']} -> {row['target']}  "
             f"{row['n']} entities", f"{row['category']}: {row['signature']}", ""]
    for label in ("missing", "extra"):
        for fp, cnt in list(row.get(label, {}).items())[:20]:
            lines.append(f"{label} ×{cnt}: {fp!r}"[:400])
    (dest / "report.txt").write_text("\n".join(lines) + "\n")


def fuzz_one(seed: int, dxf2dwg: str, dwg2dxf: str,
             fails: str | None, keep: list[int] | None = None) -> dict:
    t0 = time.perf_counter()
    header, entities = gen_specs(seed)
    if keep is not None:
        entities = [entities[i] for i in keep]
    tmp = Path(tempfile.mkdtemp(prefix="dwgfuzz-"))
    try:
        row = run_trip(header, entities, tmp, dxf2dwg, dwg2dxf)
        if row["category"] not in ("OK",) and fails:
            save_artifacts(row, header, entities, tmp, Path(fails))
        row.pop("missing", None)
        row.pop("extra", None)
        return row
    finally:
        row_time = round(time.perf_counter() - t0, 2)
        shutil.rmtree(tmp, ignore_errors=True)
        try:
            row["seconds"] = row_time
        except NameError:
            pass


# ---------------------------------------------------------------------------
# reduction: drop spec entries while the failure persists
# ---------------------------------------------------------------------------

def reduce_seed(seed: int, dxf2dwg: str, dwg2dxf: str, fails: Path) -> None:
    header, entities = gen_specs(seed)
    tmp = Path(tempfile.mkdtemp(prefix="dwgfuzz-red-"))
    try:
        base = run_trip(header, entities, tmp, dxf2dwg, dwg2dxf)
        target_cat = base["category"]
        if target_cat == "OK":
            print(f"seed {seed} passes — nothing to reduce")
            return
        print(f"seed {seed}: {target_cat} with {len(entities)} entities; reducing…")

        keep = list(range(len(entities)))
        chunk = max(1, len(keep) // 2)
        while chunk >= 1:
            i, shrunk = 0, False
            while i < len(keep):
                cand = keep[:i] + keep[i + chunk:]
                if not cand:
                    i += chunk
                    continue
                sub = [entities[j] for j in cand]
                for f in tmp.iterdir():
                    f.unlink()
                r = run_trip(header, sub, tmp, dxf2dwg, dwg2dxf)
                if r["category"] == target_cat:
                    keep = cand
                    shrunk = True
                else:
                    i += chunk
            if chunk == 1 and not shrunk:
                break
            if not shrunk:
                chunk //= 2
        final = [entities[j] for j in keep]
        for f in tmp.iterdir():
            f.unlink()
        row = run_trip(header, final, tmp, dxf2dwg, dwg2dxf)
        dest = fails / f"{target_cat}" / f"{seed}-min"
        save_artifacts(row, header, final, tmp, fails)
        # save_artifacts wrote under category/<seed>; move to <seed>-min
        src_dir = fails / target_cat / str(seed)
        if src_dir.is_dir() and src_dir != dest:
            if dest.is_dir():
                shutil.rmtree(dest)
            src_dir.rename(dest)
        print(f"reduced to {len(final)} entities "
              f"(kept indices {keep}) -> {dest}")
        print(f"{row['category']}: {row['signature']}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _find_converters(args) -> tuple[str, str]:
    from formats.dwg_bridge import find_dwg2dxf, find_dxf2dwg

    dxf2dwg = args.dxf2dwg or find_dxf2dwg()
    dwg2dxf = args.dwg2dxf or find_dwg2dxf()
    if not dxf2dwg or not dwg2dxf:
        print("converters not found (vendor/libredwg/bin)", file=sys.stderr)
        sys.exit(1)
    return str(dxf2dwg), str(dwg2dxf)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dxf2dwg", type=Path, default=None)
    ap.add_argument("--dwg2dxf", type=Path, default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run")
    p_run.add_argument("--count", type=int, default=200)
    p_run.add_argument("--seed", type=int, default=0, help="first seed")
    p_run.add_argument("--workers", type=int, default=6)
    p_run.add_argument("--out", type=Path, default=Path("dwg_fuzz_report.csv"))
    p_run.add_argument("--fails", type=Path, default=None)

    p_rep = sub.add_parser("repro")
    p_rep.add_argument("seed", type=int)
    p_rep.add_argument("--fails", type=Path, default=None)

    p_red = sub.add_parser("reduce")
    p_red.add_argument("seed", type=int)
    p_red.add_argument("--fails", type=Path, required=True)

    args = ap.parse_args()
    dxf2dwg, dwg2dxf = _find_converters(args)

    if args.cmd == "repro":
        row = fuzz_one(args.seed, dxf2dwg, dwg2dxf,
                       str(args.fails) if args.fails else None)
        print(json.dumps(row, ensure_ascii=False, indent=1))
        return 0 if row["category"] == "OK" else 1

    if args.cmd == "reduce":
        reduce_seed(args.seed, dxf2dwg, dwg2dxf, args.fails)
        return 0

    seeds = range(args.seed, args.seed + args.count)
    counts: dict[str, int] = {}
    t0 = time.perf_counter()
    with ProcessPoolExecutor(max_workers=args.workers) as pool, \
         open(args.out, "w", newline="") as fh:
        writer = csv.DictWriter(fh, ["seed", "version", "target", "n",
                                     "category", "signature", "seconds"])
        writer.writeheader()
        futures = {pool.submit(fuzz_one, s, dxf2dwg, dwg2dxf,
                               str(args.fails) if args.fails else None): s
                   for s in seeds}
        for n, fut in enumerate(as_completed(futures), 1):
            s = futures[fut]
            try:
                row = fut.result()
            except Exception as exc:
                row = {"seed": s, "version": "?", "target": "?", "n": 0,
                       "category": "HARNESS_ERROR",
                       "signature": str(exc)[:140], "seconds": 0}
            counts[row["category"]] = counts.get(row["category"], 0) + 1
            writer.writerow(row)
            fh.flush()
            if row["category"] != "OK":
                print(f"[{row['category']}] seed {row['seed']} "
                      f"({row['version']}->{row['target']}) — {row['signature']}",
                      flush=True)
            if n % 100 == 0:
                print(f"--- {n}/{args.count} ({time.perf_counter()-t0:.0f}s) "
                      f"{counts}", flush=True)
    print(f"\nDONE in {time.perf_counter()-t0:.0f}s: {counts}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
