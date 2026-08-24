# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The fence plan's two blank spots, pinned as behaviour.

Marco, dogfooding 0059_04.CERCOS PERIMETRICOS.dwg against BricsCAD: every
leader label in the model was a white box with no text, and the sheet's
title block showed its grid but none of its text.

Two distinct causes, one file:

* ezdxf draws MULTILEADER only from its proxy graphic — the picture the
  saving program baked in, with the text mask as a HATCH in the *saving*
  machine's window colour (white) and the text in colours white swallows.
* pack() sorts buckets by (group, layer, color, ...), which re-orders
  entities of different layers: the title block's WIPEOUT (layer "0",
  filled in paper white) landed after the labels of layer "-Textos".
"""
from __future__ import annotations

import base64

import ezdxf
from ezdxf.render.mleader import ConnectionSide

from core.document import Document
from render.backend import build_scene
from render.batches import Bucket, pack

# The proxy graphic of one leader from the real plan (1236 bytes): the mask
# baked as a WHITE hatch plus the label text. A MULTILEADER ezdxf creates
# carries NO proxy graphic — and without one the old code already fell back
# to the native engine, so a synthetic leader alone cannot reproduce the bug.
_BAKED_PROXY = base64.b64decode(
    "1AQAAB8AAAAMAAAAFgAAAAAAAMAMAAAAMwAAAAAAAAAMAAAAEwAAAJk6AAAMAAAAFgAAAP"
    "///8IMAAAAFAAAAAEAAABsAAAABwAAAAQAAADrQ4Ge1+OfQMnD+hyPTp9AAAAAAAAAAAAG"
    "rkEqf+ifQMnD+hyPTp9AAAAAAAAAAAAGrkEqf+ifQGoV9kyjTJ9AAAAAAAAAAADrQ4Ge1+"
    "OfQGoV9kyjTJ9AAAAAAAAAAAAMAAAAFgAAAAAAAMAMAAAAFAAAAAEAAADMAAAAJgAAAJYl"
    "+Jvx459AJ35EKRFOn0AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAADwPwAAAAAAAP"
    "A/B1wUMyamwbwAAAAAAAAAAFAARQBSAEYASQBMAAAAQwAGAAAAAQAAAMqhRbbz/bQ/AAAA"
    "AAAA8D8AAAAAAAAAAAAAAAAAAPA/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAEAAA"
    "AAAAAAAABOAHIAbwBtAGEAbgBzAC4AcwBoAHgAAABhAAAAZQDMAAAAJgAAAL6NzJr9459A"
    "Ab/rNoVNn0AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAADwPwAAAAAAAPA/B1wUMy"
    "amwbwAAAAAAAAAAEEATgBHAFUATABBAFIAAAAHAAAAAQAAAMqhRbbz/bQ/AAAAAAAA8D8A"
    "AAAAAAAAAAAAAAAAAPA/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAEAAAAAAAAAAA"
    "AAAHIAbwBtAGEAbgBzAC4AcwBoAHgAAAB4AAAAZQDcAAAAJgAAAE5IlJv1459A/HQiRulM"
    "n0AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAADwPwAAAAAAAPA/B1wUMyamwbwAAA"
    "AAAAAAADMALwA0ACIAeAAzAC8ANAAiAHgAMwAvADEANgAiAAAADwAAAAEAAADKoUW28/20"
    "PwAAAAAAAPA/AAAAAAAAAAAAAAAAAADwPwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "ABAAAAAAAAAAAATwByAG8AbQBhAG4AcwAuAHMAaAB4AAAANQAAADQADAAAADMAAAAAAAAA"
    "DAAAABAAAAAGAAAADAAAABYAAAAAAADADAAAABIAAAD/fwAADAAAABMAAAABAAAADAAAAB"
    "QAAAABAAAAVAAAAAcAAAADAAAAoxZPml/jn0DiBNtuiU6fQAAAAAAAAAAAds4ePVnjn0A+"
    "x5nyvE6fQAAAAAAAAAAA/elZ92/jn0CAlRdIjk6fQAAAAAAAAAAADAAAABQAAAABAAAADA"
    "AAABMAAACJEwAAPAAAAAYAAAACAAAAUIDUyGfjn0AxTXnbi06fQAAAAAAAAAAAdpLjrq/j"
    "n0A+Z/g0mU2fQAAAAAAAAAAADAAAABMAAAARJwAAPAAAAAYAAAACAAAAdpLjrq/jn0A+Z/"
    "g0mU2fQAAAAAAAAAAA0iGmpNjjn0A+Z/g0mU2fQAAAAAAAAAAADAAAABYAAAAAAADADAAA"
    "ABIAAAD/fwAADAAAABcAAAAAAAAADAAAABMAAACaOgAADAAAABYAAAAAAADADAAAABIAAA"
    "D/fwAADAAAABcAAAD/////DAAAADMAAAAAAAAA"
)


def _doc_with_mleader():
    doc = ezdxf.new("R2018", setup=True)
    msp = doc.modelspace()
    ml = msp.add_multileader_mtext(style="Standard")
    ml.set_content("PERFIL ANGULAR", char_height=1.0)
    ml.add_leader_line(ConnectionSide.left, [(-10.0, -5.0)])
    ml.build(insert=ezdxf.math.Vec2(0, 0))
    ml.multileader.proxy_graphic = _BAKED_PROXY
    return Document(doc)


def test_mleader_draws_its_text_not_its_proxy_picture():
    document = _doc_with_mleader()
    scene = build_scene(document)
    text = scene.triangles.is_text
    assert text is not None and bool(text.any()), (
        "a MULTILEADER produced no text glyphs — it is being drawn from "
        "its proxy graphic again (the white-box regression)")


def test_mleader_vertices_belong_to_the_mleader_handle():
    """Pick/erase need every leader vertex owned by the MULTILEADER."""
    document = _doc_with_mleader()
    handle = next(e for e in document.modelspace()
                  if e.dxftype() == "MULTILEADER").dxf.handle
    scene = build_scene(document)
    runs = scene.handle_ranges.get(handle, [])
    total = sum(count for _batch, _first, count in runs)
    assert total > 0, "no vertex is attributed to the MULTILEADER"


def test_mleader_window_colour_mask_is_not_painted():
    """A mask set to 'use window colour' must not become a filled box.

    The white boxes on Marco's plan were exactly this mask, baked white
    into the proxy graphic. The native path leaves the fill out (matching
    ezdxf's complex-mtext behaviour for bg_fill == 3).
    """
    doc = ezdxf.new("R2018", setup=True)
    msp = doc.modelspace()
    ml = msp.add_multileader_mtext(style="Standard")
    ml.set_content("MALLA DE ALAMBRE", char_height=1.0)
    ml.add_leader_line(ConnectionSide.left, [(-10.0, -5.0)])
    ml.build(insert=ezdxf.math.Vec2(0, 0))
    entity = next(e for e in msp if e.dxftype() == "MULTILEADER")
    entity.proxy_graphic = _BAKED_PROXY
    entity.context.mtext.has_bg_fill = 1
    entity.context.mtext.use_window_bg_color = 1
    entity.context.mtext.bg_color = -1027028792   # RGB(200, 200, 200)
    document = Document(doc)
    scene = build_scene(document)

    # Control first: the text itself must be there (otherwise "no white
    # triangles" would also pass on a drawing that renders nothing).
    text = scene.triangles.is_text
    assert text is not None and bool(text.any())

    light_fill = 0
    for rng, flag in zip(scene.triangles.ranges, text):
        if flag:
            continue
        run = scene.triangles.data[rng.first:rng.first + rng.count]
        rgb = run["rgba"][:, :3].astype(int)
        light_fill += int((rgb.min(axis=1) >= 190).sum())
    assert light_fill == 0, (
        f"{light_fill} near-white fill vertices — the baked mask is back")


def test_pack_draws_text_buckets_after_fills_of_any_layer():
    """Layer '0' sorts after '-Textos'; the text must still win."""
    wipeout = Bucket("0", "#ffffff", kind="")
    wipeout.triangles.extend([0.0, 0.0, 10.0, 0.0, 10.0, 10.0])
    wipeout.triangles_owner.append("W1")
    label = Bucket("-Textos", "#000000", kind="T")
    label.triangles.extend([1.0, 1.0, 2.0, 1.0, 2.0, 2.0])
    label.triangles_owner.append("T1")
    buckets = {
        (0, "-Textos", "#000000", 0.25, "T"): label,
        (0, "0", "#ffffff", 0.25, ""): wipeout,
    }
    scene = pack(buckets)
    order = [rng.layer for rng in scene.triangles.ranges]
    assert order.index("0") < order.index("-Textos"), (
        "the wipeout must be packed before the text so the text paints on "
        f"top — got {order}")


def test_pack_keeps_draworder_groups_above_text():
    """DRAWORDER 'bring to front' still beats text, as the user asked."""
    front = Bucket("0", "#ff0000", kind="", group=1)
    front.triangles.extend([0.0, 0.0, 1.0, 0.0, 1.0, 1.0])
    front.triangles_owner.append("F1")
    label = Bucket("-Textos", "#000000", kind="T", group=0)
    label.triangles.extend([0.0, 0.0, 1.0, 0.0, 1.0, 1.0])
    label.triangles_owner.append("T1")
    buckets = {
        (1, "0", "#ff0000", 0.25, ""): front,
        (0, "-Textos", "#000000", 0.25, "T"): label,
    }
    scene = pack(buckets)
    order = [rng.layer for rng in scene.triangles.ranges]
    assert order.index("-Textos") < order.index("0"), (
        "an explicit bring-to-front must not be overridden by the text rule")


def test_a_text_mask_packs_between_fills_and_glyphs():
    """The mask of an MTEXT must underlie its own glyphs, whatever colours.

    On a sheet the window-colour mask is paper white and the glyphs black;
    alphabetical colour order painted the mask LAST, so every masked label
    erased its own text. The model tab survived by luck ("#212830" sorts
    before "#ffffff"). Kind "TM" pins the order by construction.
    """
    mask = Bucket("A", "#ffffff", kind="TM")
    mask.triangles.extend([0.0, 0.0, 10.0, 0.0, 10.0, 10.0])
    mask.triangles_owner.append("M1")
    glyphs = Bucket("A", "#000000", kind="T")
    glyphs.triangles.extend([1.0, 1.0, 2.0, 1.0, 2.0, 2.0])
    glyphs.triangles_owner.append("M1")
    fill = Bucket("Z", "#ff0000", kind="")
    fill.triangles.extend([0.0, 0.0, 1.0, 0.0, 1.0, 1.0])
    fill.triangles_owner.append("F1")
    buckets = {
        (0, "A", "#000000", 0.25, "T"): glyphs,
        (0, "A", "#ffffff", 0.25, "TM"): mask,
        (0, "Z", "#ff0000", 0.25, ""): fill,
    }
    scene = pack(buckets)
    order = [(rng.layer, bool(t)) for rng, t in
             zip(scene.triangles.ranges, scene.triangles.is_text)]
    assert order == [("Z", False), ("A", False), ("A", True)], order


def test_masked_mtext_on_a_sheet_keeps_its_text_on_top():
    """End to end: window-colour mask on paper, glyphs packed after it."""
    doc = ezdxf.new("R2018", setup=True)
    layout = doc.layouts.new("Sheet")
    mtext = layout.add_mtext("PERFIL ANGULAR", dxfattribs={
        "char_height": 5.0, "insert": (100.0, 100.0), "bg_fill": 3,
    })
    document = Document(doc)
    scene = build_scene(document, layout_name="Sheet")
    tri = scene.triangles
    runs = [r for r in scene.handle_ranges.get(mtext.dxf.handle, [])
            if r[0] == "triangles"]
    assert runs, "the masked MTEXT produced no triangles"
    flags = []
    for _name, first, count in runs:
        for rng, is_t in zip(tri.ranges, tri.is_text):
            if first <= rng.first < first + count:
                flags.append(bool(is_t))
    assert False in flags, "the mask quad is missing"
    assert True in flags, "the glyphs are missing"
    assert flags.index(False) < flags.index(True), (
        f"the mask must pack before the glyphs — got {flags}")
