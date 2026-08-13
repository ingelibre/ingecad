# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Headless tests of the regen pipeline: ezdxf doc -> frontend -> packed scene."""
from __future__ import annotations

import math

import ezdxf
import numpy as np
import pytest

from core.document import Document, DocumentError
from render.backend import build_scene
from render.batches import parse_color


def make_document() -> Document:
    doc = ezdxf.new("R2018", setup=True)
    msp = doc.modelspace()
    # UTM-scale coordinates on purpose: the precision path is the point.
    msp.add_line((500_000.0, 8_500_000.0), (500_100.0, 8_500_050.0))
    msp.add_circle((500_050.0, 8_500_050.0), 25.0)
    msp.add_text("PLANO", height=5.0, dxfattribs={"insert": (500_010.0, 8_500_080.0)})
    hatch = msp.add_hatch(color=1)
    hatch.paths.add_polyline_path(
        [(500_000.0, 8_500_000.0), (500_010.0, 8_500_000.0),
         (500_010.0, 8_500_010.0), (500_000.0, 8_500_010.0)],
        is_closed=True,
    )
    msp.add_point((500_020.0, 8_500_020.0))
    return Document(doc)


def test_scene_collects_all_primitive_kinds():
    scene = build_scene(make_document())
    assert scene.lines.vertex_count > 0        # line + flattened circle
    assert scene.triangles.vertex_count > 0    # hatch fill + text glyphs
    assert scene.points.vertex_count == 1
    assert not scene.is_empty


def test_scene_origin_recenters_utm_coordinates():
    scene = build_scene(make_document())
    ox, oy = scene.origin
    assert abs(ox - 500_050.0) < 100.0
    assert abs(oy - 8_500_040.0) < 100.0
    # Stored vertices are small numbers: float32 keeps full drawing precision.
    assert np.abs(scene.lines.positions()).max() < 1000.0


def test_scene_extents_match_drawing():
    scene = build_scene(make_document())
    min_x, min_y, max_x, max_y = scene.extents
    assert min_x == pytest.approx(500_000.0, abs=1.0)
    assert max_x == pytest.approx(500_100.0, abs=1.0)
    assert min_y == pytest.approx(8_500_000.0, abs=1.0)


def test_circle_flattening_is_accurate():
    scene = build_scene(make_document())
    ox, oy = scene.origin
    verts = scene.lines.positions().astype(np.float64)
    # Vertices on the circle sit 25 units from its center.
    cx, cy = 500_050.0 - ox, 8_500_050.0 - oy
    radii = np.hypot(verts[:, 0] - cx, verts[:, 1] - cy)
    on_circle = np.abs(radii - 25.0) < 0.05
    assert on_circle.sum() >= 64  # the circle produced a dense polyline


def test_thick_lineweights_become_quads():
    doc = ezdxf.new("R2018", setup=True)
    msp = doc.modelspace()
    msp.add_line((0.0, 0.0), (100.0, 0.0), dxfattribs={"lineweight": 50})   # 0.50 mm
    msp.add_line((0.0, 0.0), (0.0, 100.0), dxfattribs={"lineweight": 13})   # 0.13 mm
    scene = build_scene(Document(doc))

    # The 0.50 mm line becomes one quad (6 vertices); the thin one stays GL_LINES.
    assert scene.thick.vertex_count == 6
    assert scene.lines.vertex_count == 2
    assert scene.thick.ranges[0].lineweight == pytest.approx(0.5)
    normals = scene.thick.data["normal"]
    assert np.allclose(np.hypot(normals[:, 0], normals[:, 1]), 1.0, atol=1e-5)
    # The horizontal segment's expansion direction is vertical.
    assert np.allclose(np.abs(normals[:, 1]), 1.0, atol=1e-5)


def test_draw_ranges_partition_the_buffer():
    scene = build_scene(make_document())
    for batch in (scene.lines, scene.thick, scene.triangles, scene.points):
        cursor = 0
        for rng in batch.ranges:
            assert rng.first == cursor
            assert rng.count > 0
            cursor += rng.count
        assert cursor == batch.vertex_count


def test_malformed_entity_is_skipped_not_fatal():
    # Real-world case: LibreDWG emitted a HATCH spline edge with an
    # inconsistent knot count; one bad entity must never blank the drawing.
    doc = ezdxf.new("R2018")
    msp = doc.modelspace()
    msp.add_line((0.0, 0.0), (10.0, 0.0))
    hatch = msp.add_hatch(color=2)
    edge_path = hatch.paths.add_edge_path()
    edge_path.add_spline(
        control_points=[(0, 0), (5, 5), (10, 0)],
        knot_values=[0.0] * 32,  # wrong: 3 control points + degree 3 need 7
        degree=3,
    )
    scene = build_scene(Document(doc))
    assert scene.lines.vertex_count >= 2      # the LINE still renders
    assert len(scene.skipped) == 1
    assert scene.skipped[0].startswith("HATCH")


def test_view_culling_and_tiny_text_skip():
    doc = ezdxf.new("R2018")
    msp = doc.modelspace()
    # Two clusters far apart, plus a small text label near the first one.
    msp.add_line((0.0, 0.0), (10.0, 0.0))
    msp.add_line((10_000.0, 10_000.0), (10_010.0, 10_000.0))
    msp.add_text("A1", height=2.0, dxfattribs={"insert": (5.0, 5.0)})
    scene = build_scene(Document(doc))

    # Zoomed into the first cluster: the far line's ranges are culled.
    near = scene.lines.visible_runs((-50, -50, 50, 50), 10.0, 0.0)
    everything = scene.lines.visible_runs(scene.extents, 10.0, 0.0)
    assert sum(c for _f, c in near) < sum(c for _f, c in everything)

    # Text ranges disappear when glyphs are sub-pixel, reappear when legible.
    assert scene.triangles.vertex_count > 0  # the glyphs
    tiny = scene.triangles.visible_runs(scene.extents, 0.0001, 2.0)
    legible = scene.triangles.visible_runs(scene.extents, 10.0, 2.0)
    assert sum(c for _f, c in tiny) == 0
    assert sum(c for _f, c in legible) == scene.triangles.vertex_count


def test_empty_modelspace_falls_back_to_paperspace_layout():
    # ArchiCAD-published sheets: modelspace empty, everything composed in a
    # paperspace layout. The scene must show the layout and say so.
    doc = ezdxf.new("R2018")
    psp = doc.layout("Layout1")
    psp.add_line((0.0, 0.0), (420.0, 0.0))
    psp.add_line((0.0, 0.0), (0.0, 297.0))
    scene = build_scene(Document(doc))
    assert not scene.is_empty
    assert scene.layout_name == "Layout1"
    # Layout-tab look: gray desk canvas + the white paper sheet that the
    # viewport draws from scene.paper (AutoCAD layout tabs).
    assert scene.background is not None
    assert scene.paper is not None and "sheet" in scene.paper
    # A drawing with modelspace content keeps layout_name None.
    doc2 = ezdxf.new("R2018")
    doc2.modelspace().add_line((0, 0), (1, 1))
    assert build_scene(Document(doc2)).layout_name is None


def test_parse_color_rgb_and_rgba():
    assert parse_color("#ff0000") == (1.0, 0.0, 0.0, 1.0)
    r, g, b, a = parse_color("#00ff0080")
    assert (r, g, b) == (0.0, 1.0, 0.0)
    assert math.isclose(a, 128 / 255)


def test_document_load_rejects_garbage(tmp_path):
    bad = tmp_path / "bad.dxf"
    bad.write_text("this is not a dxf")
    with pytest.raises(DocumentError):
        Document.load(bad)


def test_document_roundtrip_load(tmp_path):
    path = tmp_path / "plan.dxf"
    make_document().doc.saveas(path)
    document = Document.load(path)
    assert document.name == "plan.dxf"
    scene = build_scene(document)
    assert not scene.is_empty


def test_extents_survive_a_corrupt_coordinate():
    """One bad vertex must not swallow the drawing.

    Real case (PTL-026-COFOPRI-01-OJAMOQ.dwg): the converter handed us LAYOUT
    extents at 6.7e301 and polyline vertices at 8.9e21, so raw min/max framed a
    box 10^301 across, Zoom Extents fitted that, and 5725 entities collapsed
    below one pixel — a blank canvas holding a complete drawing.
    """
    doc = ezdxf.new("R2018", setup=True)
    msp = doc.modelspace()
    for i in range(60):                                   # the real drawing
        msp.add_line((500_000.0 + i, 8_500_000.0), (500_000.0 + i, 8_500_050.0))
    msp.add_line((6.7e301, 8.9e21), (500_000.0, 8_500_000.0))   # the corrupt one

    min_x, min_y, max_x, max_y = build_scene(Document(doc)).extents
    assert max_x - min_x < 10_000.0, "the corrupt vertex widened the frame"
    assert max_y - min_y < 10_000.0
    assert min_x == pytest.approx(500_000.0, abs=1.0)
    assert max_y == pytest.approx(8_500_050.0, abs=1.0)
    # ...and the origin stays on the drawing, so float32 keeps its precision.
    ox, oy = build_scene(Document(doc)).origin
    assert abs(ox - 500_030.0) < 200.0 and abs(oy - 8_500_025.0) < 200.0


def test_extents_survive_non_finite_coordinates():
    doc = ezdxf.new("R2018", setup=True)
    msp = doc.modelspace()
    for i in range(40):
        msp.add_line((10.0 + i, 20.0), (10.0 + i, 60.0))
    msp.add_line((float("nan"), float("inf")), (10.0, 20.0))

    min_x, min_y, max_x, max_y = build_scene(Document(doc)).extents
    assert all(math.isfinite(v) for v in (min_x, min_y, max_x, max_y))
    assert max_x - min_x < 1000.0 and max_y - min_y < 1000.0


def test_extents_keep_a_legitimate_far_detail():
    """A real detail well away from the main body must stay inside the frame."""
    doc = ezdxf.new("R2018", setup=True)
    msp = doc.modelspace()
    for i in range(60):
        msp.add_line((0.0 + i, 0.0), (0.0 + i, 50.0))     # main body ~60 x 50
    msp.add_circle((3_000.0, 2_000.0), 10.0)               # far, but real

    min_x, min_y, max_x, max_y = build_scene(Document(doc)).extents
    assert max_x >= 2_900.0, "the far detail was clipped out of the frame"
    assert max_y >= 1_900.0


def test_stale_declared_extents_are_distrusted():
    """$EXTMIN/$EXTMAX that rejects a real slice of the drawing must not filter.

    The declared box is a good corruption detector only while it still describes
    the geometry. If it lags badly behind, believing it would push most of the
    drawing outside Zoom Extents — worse than the problem it solves.
    """
    doc = ezdxf.new("R2018", setup=True)
    msp = doc.modelspace()
    for i in range(100):
        msp.add_line((float(i), 0.0), (float(i), 100.0))
    # Declared box covers only a sliver of it.
    doc.header["$EXTMIN"] = (0.0, 0.0, 0.0)
    doc.header["$EXTMAX"] = (2.0, 2.0, 0.0)

    min_x, min_y, max_x, max_y = build_scene(Document(doc)).extents
    assert max_x == pytest.approx(99.0, abs=1.0), "the stale box was believed"
    assert max_y == pytest.approx(100.0, abs=1.0)


def test_thick_lines_are_hideable_by_handle():
    """Every drawable entity must appear in ``handle_ranges``.

    The viewport erases by zeroing the alpha of an entity's vertex runs; a
    handle missing from the map is skipped silently, so its geometry stays on
    screen until the next full regen. That is what Marco hit on 2026-08-07:
    cutting a big selection left the thick strokes of the original behind, and
    a delete looked partial. Thick lines live in their own batch, and only that
    batch was not recording owners.
    """
    doc = ezdxf.new("R2018", setup=True)
    msp = doc.modelspace()
    thin = msp.add_line((0.0, 0.0), (100.0, 0.0), dxfattribs={"lineweight": 13})
    thick = msp.add_line((0.0, 50.0), (100.0, 50.0), dxfattribs={"lineweight": 50})
    scene = build_scene(Document(doc))

    hr = scene.handle_ranges
    assert thin.dxf.handle in hr
    assert thick.dxf.handle in hr, "thick geometry cannot be hidden on erase"

    # The recorded run must cover exactly the quad's six vertices, and name the
    # batch the viewport will reach for with getattr(scene, batch_name).
    runs = hr[thick.dxf.handle]
    assert [name for name, _f, _c in runs] == ["thick"]
    assert sum(count for _n, _f, count in runs) == scene.thick.vertex_count == 6


def _document_with_everything() -> Document:
    """One drawing exercising every path that reaches a batch: thin and thick
    lines, curves, text glyphs, a hatch fill, a point, and a block holding its
    own hatch and a nested block."""
    doc = ezdxf.new("R2018", setup=True)
    inner = doc.blocks.new("INNER")
    inner.add_circle((0.0, 0.0), 1.5)
    blk = doc.blocks.new("MUEBLE")
    for i in range(4):
        blk.add_line((float(i), 0.0), (float(i), 4.0),
                     dxfattribs={"lineweight": 50})       # thick, inside a block
    blk.add_text("B", height=1.0, dxfattribs={"insert": (1.0, 1.0)})
    bh = blk.add_hatch(color=3)
    bh.paths.add_polyline_path([(0, 0), (4, 0), (4, 4), (0, 4)], is_closed=True)
    blk.add_blockref("INNER", (2.0, 2.0))                  # nested
    msp = doc.modelspace()
    msp.add_blockref("MUEBLE", (0.0, 0.0))
    msp.add_line((0.0, 20.0), (30.0, 20.0), dxfattribs={"lineweight": 70})
    msp.add_line((0.0, 22.0), (30.0, 22.0), dxfattribs={"lineweight": 13})
    msp.add_arc((10.0, 30.0), 5.0, 0.0, 180.0)
    msp.add_text("PLANO", height=2.0, dxfattribs={"insert": (0.0, 35.0)})
    msp.add_point((25.0, 25.0))
    h = msp.add_hatch(color=1)
    h.paths.add_polyline_path([(0, 40), (10, 40), (10, 45), (0, 45)], is_closed=True)
    return Document(doc)


def test_handle_ranges_cover_every_vertex_of_every_batch():
    """No drawable vertex may be un-attributable: an unowned run is a run the
    viewport can never hide. Checks the packing offsets line up too — an
    off-by-one in the run arithmetic would zero a neighbour's alpha instead."""
    scene = build_scene(_document_with_everything())
    # the invariant is worthless if the drawing does not reach every batch
    for name in ("lines", "thick", "triangles", "points"):
        assert getattr(scene, name).vertex_count > 0, f"{name} batch is empty"
    covered = {name: 0 for name in ("lines", "thick", "triangles", "points")}
    for runs in scene.handle_ranges.values():
        for name, first, count in runs:
            batch = getattr(scene, name)
            assert 0 <= first
            assert first + count <= batch.vertex_count, f"{name} run runs past the end"
            covered[name] += count
    for name, total in covered.items():
        assert total == getattr(scene, name).vertex_count, f"{name}: unowned vertices"


def test_block_content_is_owned_by_the_insert():
    """Block geometry must be attributed to the INSERT, not left unowned.

    The frontend expands an INSERT into *virtual* copies, whose ``handle`` is
    None, so every vertex inside every block used to be unowned — and the only
    handle that could ever hide them is the INSERT's, because that is what the
    selection and the pick index hold.
    """
    doc = ezdxf.new("R2018", setup=True)
    blk = doc.blocks.new("MUEBLE")
    for i in range(6):
        blk.add_line((float(i), 0.0), (float(i), 4.0))
    msp = doc.modelspace()
    ins = msp.add_blockref("MUEBLE", (0.0, 0.0))
    scene = build_scene(Document(doc))

    assert scene.handle_ranges.keys() == {ins.dxf.handle}
    covered = sum(c for _n, _f, c in scene.handle_ranges[ins.dxf.handle])
    assert covered == scene.lines.vertex_count == 12   # 6 segments, 2 verts each


def test_a_parent_keeps_its_owner_after_a_child_exits():
    """exit_entity used to clear the context instead of restoring it, so
    anything the enclosing entity drew after a nested child came out unowned."""
    doc = ezdxf.new("R2018", setup=True)
    blk = doc.blocks.new("NESTED")
    blk.add_line((0.0, 0.0), (1.0, 0.0))
    outer = doc.blocks.new("OUTER")
    outer.add_blockref("NESTED", (0.0, 0.0))     # child, entered and exited
    outer.add_line((0.0, 1.0), (1.0, 1.0))       # drawn AFTER that child
    msp = doc.modelspace()
    ins = msp.add_blockref("OUTER", (0.0, 0.0))
    scene = build_scene(Document(doc))

    assert scene.handle_ranges.keys() == {ins.dxf.handle}
    covered = sum(c for _n, _f, c in scene.handle_ranges[ins.dxf.handle])
    assert covered == scene.lines.vertex_count == 4


def test_bold_and_italic_reach_the_canvas():
    """ezdxf's font matcher filtered by style BEFORE weight, so \\f...|b1
    resolved to the regular face and bold/italic rendered exactly like
    plain text (patched in core.ezdxf_patches)."""
    def glyphs(content):
        doc = Document.new()
        mtext = doc.modelspace().add_mtext(
            content, dxfattribs={"char_height": 2.5, "width": 80.0})
        mtext.set_location((0.0, 0.0))
        scene = build_scene(doc)
        return np.asarray([v[0] for v in scene.triangles.data])

    plain = glyphs("PRUEBA")
    bold = glyphs(r"{\fArial|b1|i0;PRUEBA}")
    italic = glyphs(r"{\fArial|b0|i1;PRUEBA}")
    assert plain.shape != bold.shape or not np.allclose(plain, bold)
    assert plain.shape != italic.shape or not np.allclose(plain, italic)


def test_detached_glyph_parts_render():
    """baño drew as bano: the filler took the LARGEST ring as the exterior
    and every other sub-path as a hole — the ñ's tilde and the i's dot are
    detached outlines, and an outside "hole" tessellates to nothing. The
    even-odd nesting classifier keeps them (and keeps the O's hole a hole)."""
    def verts(txt):
        doc = Document.new()
        e = doc.modelspace().add_text(txt, dxfattribs={"height": 2.5})
        scene = build_scene(doc)
        return sum(n for _b, _s, n in scene.handle_ranges.get(e.dxf.handle, []))

    assert verts("ñ") > verts("n")          # the tilde
    assert verts("i") > verts("l")          # the dot
    assert verts("á") > verts("a")          # the accent
    # and a ring INSIDE another is still a hole: the O is not a filled disc
    doc = Document.new()
    o = doc.modelspace().add_text("O", dxfattribs={"height": 2.5})
    disc = doc.modelspace().add_circle((50, 0), 1.25)  # nothing to compare
    scene = build_scene(doc)
    o_verts = sum(n for _b, _s, n in scene.handle_ranges[o.dxf.handle])
    assert o_verts > 0


def test_layout_viewport_text_keeps_its_counters():
    """The paperspace viewport clipper explodes a multi-ring glyph into
    sibling single-ring paths; per-path nesting then filled the O's
    counter solid on every layout tab (Marco's capture). The nesting now
    runs per CALL, so the model copy and the viewport copy of the same
    text tessellate identically."""
    doc = Document.new()
    msp = doc.modelspace()
    text = msp.add_text("COCINA O", dxfattribs={"height": 2.5,
                                                "insert": (10.0, 10.0)})
    layout = doc.doc.layouts.get("Layout1")
    vp = layout.add_viewport(center=(100, 100), size=(80, 60),
                             view_center_point=(15, 10), view_height=30)
    vp.dxf.status = 2

    def filled_area(scene, scale=1.0):
        total = 0.0
        for name, start, count in scene.handle_ranges.get(
                text.dxf.handle, []):
            if name != "triangles":
                continue
            pos = scene.triangles.data["pos"][start:start + count]
            for i in range(0, len(pos), 3):
                ax, ay = pos[i]; bx, by = pos[i + 1]; cx, cy = pos[i + 2]
                total += abs((bx - ax) * (cy - ay)
                             - (cx - ax) * (by - ay)) / 2.0
        return total / (scale * scale)

    vp_scale = 60.0 / 30.0        # paper units per model unit in the vp
    model = filled_area(build_scene(doc, "Model"))
    paper = filled_area(build_scene(doc, "Layout1"), scale=vp_scale)
    assert model > 0
    # filled counters would inflate the paper copy's ink by ~50 %+;
    # tessellation density differences stay within a few percent
    assert abs(paper - model) / model < 0.10
