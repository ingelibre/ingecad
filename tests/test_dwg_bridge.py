# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""LibreDWG bridge tests. Skipped when the satellite tools are not present
(CI does not build LibreDWG yet); they always run on dev machines with the
vendor/ build."""
from __future__ import annotations

import re

import ezdxf
import pytest

from core.document import Document
from formats import dwg_bridge
from formats.dwg_bridge import (
    DwgBridgeError,
    dwg_to_dxf,
    dxf_to_dwg,
    find_dwg2dxf,
    find_dxf2dwg,
    load_dwg,
)

needs_libredwg = pytest.mark.skipif(
    find_dwg2dxf() is None or find_dxf2dwg() is None,
    reason="LibreDWG tools not available",
)


def _sample_doc():
    doc = ezdxf.new("R2000")
    msp = doc.modelspace()
    msp.add_line((1.25, 2.5), (300.75, 400.125))
    msp.add_circle((50.0, 60.0), 12.5)
    return doc


@needs_libredwg
def test_dxf_dwg_dxf_roundtrip(tmp_path):
    dxf = tmp_path / "plan.dxf"
    _sample_doc().saveas(dxf)

    dwg = tmp_path / "plan.dwg"
    dxf_to_dwg(dxf, dwg)
    assert dwg.stat().st_size > 0

    # Document.load is the app's real path: LibreDWG output needs ezdxf's
    # recover mode (it emits some handle-0 entities strict readfile rejects).
    back = dwg_to_dxf(dwg)
    doc2 = Document.load(back).doc
    lines = doc2.modelspace().query("LINE")
    assert len(lines) == 1
    start = lines[0].dxf.start
    assert start.x == pytest.approx(1.25) and start.y == pytest.approx(2.5)
    circles = doc2.modelspace().query("CIRCLE")
    assert len(circles) == 1
    assert circles[0].dxf.radius == pytest.approx(12.5)


def test_empty_salvage_raises_actionable_error(tmp_path, monkeypatch):
    # Real bench case (BASE COTAHUASI.dwg): LibreDWG emits broken DXF where
    # recover salvages a big entitydb but modelspace comes out empty. The user
    # must get an actionable message, not a blank drawing.
    doc = ezdxf.new("R2018")
    block = doc.blocks.new("ORPHANED")
    for i in range(150):
        block.add_line((i, 0.0), (i, 1.0))
    fake_dxf = tmp_path / "salvaged.dxf"
    doc.saveas(fake_dxf)

    monkeypatch.setattr(dwg_bridge, "dwg_to_dxf", lambda p: fake_dxf)
    with pytest.raises(DwgBridgeError, match="could not fully convert"):
        load_dwg(tmp_path / "colega.dwg")


def test_paperspace_only_sheet_is_not_rejected(tmp_path, monkeypatch):
    # ArchiCAD-published sheet: empty modelspace, content in a paperspace
    # layout. load_dwg must NOT reject it as a broken salvage.
    doc = ezdxf.new("R2018")
    psp = doc.layout("Layout1")
    for i in range(60):
        psp.add_line((i, 0.0), (i, 297.0))
    block = doc.blocks.new("DRAWING_1")
    for i in range(120):
        block.add_line((i, 0.0), (i, 1.0))
    fake_dxf = tmp_path / "sheet.dxf"
    doc.saveas(fake_dxf)

    monkeypatch.setattr(dwg_bridge, "dwg_to_dxf", lambda p: fake_dxf)
    document = load_dwg(tmp_path / "lamina.dwg")
    assert len(document.modelspace()) == 0
    assert any(len(lay) for lay in document.doc.layouts if lay.name != "Model")


@needs_libredwg
def test_accented_paths_survive(tmp_path):
    # skp2dae gotcha family: paths with accents and spaces must work.
    folder = tmp_path / "planos año"
    folder.mkdir()
    dxf = folder / "detalle ñandú.dxf"
    _sample_doc().saveas(dxf)
    dwg = folder / "detalle ñandú.dwg"
    dxf_to_dwg(dxf, dwg)
    back = dwg_to_dxf(dwg)
    assert len(Document.load(back).modelspace().query("LINE")) == 1


def _dxf_with(n_entities, path):
    doc = ezdxf.new("R2000")
    for i in range(n_entities):
        doc.modelspace().add_line((i, 0), (i, 1))
    doc.saveas(path)
    return path


def test_verify_dwg_clean_when_counts_match(tmp_path, monkeypatch):
    # Verified save: source and re-read agree, no writer errors -> no warning.
    src = _dxf_with(5, tmp_path / "src.dxf")
    back = _dxf_with(5, tmp_path / "back.dxf")
    monkeypatch.setattr(dwg_bridge, "dwg_to_dxf", lambda p: back)
    assert dwg_bridge.verify_dwg(src, tmp_path / "out.dwg", stderr="") == []


def test_verify_dwg_flags_dropped_entities(tmp_path, monkeypatch):
    # A DWG that lost geometry on the way out must warn the user.
    src = _dxf_with(10, tmp_path / "src.dxf")
    back = _dxf_with(6, tmp_path / "back.dxf")
    monkeypatch.setattr(dwg_bridge, "dwg_to_dxf", lambda p: back)
    warnings = dwg_bridge.verify_dwg(src, tmp_path / "out.dwg", stderr="")
    assert warnings and any("did not survive" in w for w in warnings)


def test_verify_dwg_flags_real_converter_error(tmp_path, monkeypatch):
    src = _dxf_with(3, tmp_path / "src.dxf")
    back = _dxf_with(3, tmp_path / "back.dxf")
    monkeypatch.setattr(dwg_bridge, "dwg_to_dxf", lambda p: back)
    stderr = "ERROR: HATCH no paths[0].segs\nSomething improperly read\n"
    warnings = dwg_bridge.verify_dwg(src, tmp_path / "out.dwg", stderr=stderr)
    assert any("internal errors" in w for w in warnings)


def test_verify_dwg_ignores_duplicate_handle_noise(tmp_path, monkeypatch):
    # "Duplicate handle" is logged even for files that open fine -> not a verdict.
    src = _dxf_with(3, tmp_path / "src.dxf")
    back = _dxf_with(3, tmp_path / "back.dxf")
    monkeypatch.setattr(dwg_bridge, "dwg_to_dxf", lambda p: back)
    stderr = "ERROR: Duplicate handle B for object 72 already points to object 48\n"
    assert dwg_bridge.verify_dwg(src, tmp_path / "out.dwg", stderr=stderr) == []


def test_verify_dwg_flags_unreadable_output(tmp_path, monkeypatch):
    src = _dxf_with(3, tmp_path / "src.dxf")
    def _boom(_p):
        raise dwg_bridge.DwgBridgeError("cannot read")
    monkeypatch.setattr(dwg_bridge, "dwg_to_dxf", _boom)
    warnings = dwg_bridge.verify_dwg(src, tmp_path / "out.dwg", stderr="")
    assert any("could not re-open" in w for w in warnings)


def _steal_handle(dxf_path, dxftype: str, victim_handle: str) -> None:
    """Rewrite the handle of the first ``dxftype`` object to ``victim_handle``.

    Reproduces LibreDWG#1356 without needing a real drawing: two objects end up
    sharing a handle, so ezdxf resolves it to whichever it read last.
    """
    lines = dxf_path.read_bytes().decode("latin-1").split("\n")
    i = 0
    while i + 1 < len(lines):
        if lines[i].strip() == "0" and lines[i + 1].strip() == dxftype:
            j = i + 2
            while j + 1 < len(lines) and lines[j].strip() != "0":
                if lines[j].strip() == "5":
                    lines[j + 1] = victim_handle
                    dxf_path.write_bytes("\n".join(lines).encode("latin-1"))
                    return
                j += 2
        i += 2
    raise AssertionError(f"no {dxftype} found to corrupt")


def test_dedupe_handles_recovers_a_stolen_modelspace_handle(tmp_path):
    # The real killer of LibreDWG#1356: an OBJECTS-section object takes the
    # handle of the *Model_Space BLOCK_RECORD, and the whole file stops loading.
    doc = ezdxf.new("R2018")
    msp = doc.modelspace()
    for i in range(7):
        msp.add_line((float(i), 0.0), (float(i), 1.0))
    doc.groups.new("G1").extend(msp.query("LINE")[:2])
    ms_handle = doc.block_records.get("*Model_Space").dxf.handle

    dxf = tmp_path / "stolen.dxf"
    doc.saveas(dxf)
    _steal_handle(dxf, "GROUP", ms_handle)

    with pytest.raises(ezdxf.DXFError):
        ezdxf.readfile(dxf)

    assert dwg_bridge._dedupe_handles(dxf) == 1
    assert len(ezdxf.readfile(dxf).modelspace().query("LINE")) == 7
    # Idempotent: a repaired file has nothing left to renumber.
    assert dwg_bridge._dedupe_handles(dxf) == 0


def test_dedupe_handles_leaves_a_clean_file_untouched(tmp_path):
    dxf = _dxf_with(4, tmp_path / "clean.dxf")
    before = dxf.read_bytes()
    assert dwg_bridge._dedupe_handles(dxf) == 0
    assert dxf.read_bytes() == before  # not rewritten at all


def test_dxf_lines_do_not_split_on_byte_0x85(tmp_path):
    # str.splitlines() breaks on \x0b \x0c \x1c-\x1e \x85 too, and latin-1 maps
    # byte 0x85 to U+0085. Real drawings carry it, and one phantom line shifts
    # every tag/value pair after it -> a handle rewrite lands on a group code.
    dxf = _dxf_with(2, tmp_path / "raw.dxf")
    # into a free-text *value* line, so the tag structure itself stays intact
    raw = dxf.read_bytes().replace(b"ANSI_1252", b"ANSI_1252\x85", 1)
    assert b"\x85" in raw, "the fixture needs a value line to poison"
    dxf.write_bytes(raw)

    def anchors_off_pairing(lines: list[str]) -> int:
        """How many '0'/<NAME> records land on an odd index (0 == pairing intact)."""
        return sum(
            1
            for i in range(len(lines) - 1)
            if lines[i].strip() == "0"
            and re.fullmatch(r"[A-Z][A-Z0-9_$*]{1,30}", lines[i + 1].strip())
            and i % 2
        )

    assert anchors_off_pairing(dwg_bridge._read_dxf_lines(dxf)) == 0
    # ...whereas splitlines() invents a line at the 0x85 and shifts the rest
    assert anchors_off_pairing(raw.decode("latin-1").splitlines(keepends=True)) > 0
    # and the round trip stays byte-exact
    dwg_bridge._write_dxf_lines(dxf, dwg_bridge._read_dxf_lines(dxf))
    assert dxf.read_bytes() == raw


def test_load_dwg_does_not_leak_its_temp_dxf(tmp_path):
    """Every opened .dwg used to leave its converted DXF in /tmp forever.

    /tmp is a tmpfs on most desktops, so 189 leftover directories measured on
    the author's machine were 2.4 GB of RAM. ezdxf reads the whole document in
    memory, so the DXF is disposable as soon as load returns.
    """
    if find_dwg2dxf() is None:
        pytest.skip("LibreDWG not available")
    import glob

    dxf = tmp_path / "plan.dxf"
    _sample_doc().saveas(dxf)
    dwg = tmp_path / "plan.dwg"
    dxf_to_dwg(dxf, dwg)

    before = set(glob.glob("/tmp/ingecad-dwg-*"))
    document = load_dwg(dwg)
    assert len(document.modelspace()) > 0     # it really did load
    assert set(glob.glob("/tmp/ingecad-dwg-*")) == before


def test_discard_temp_dxf_only_touches_our_own_directories(tmp_path):
    """A monkeypatched dwg_to_dxf hands back fixture paths; never delete those."""
    from formats.dwg_bridge import _discard_temp_dxf

    keep = tmp_path / "precious.dxf"
    keep.write_text("0\nEOF\n")
    _discard_temp_dxf(keep)
    assert keep.exists() and tmp_path.exists()

    ours = tmp_path / "ingecad-dwg-xyz"
    ours.mkdir()
    inside = ours / "converted.dxf"
    inside.write_text("0\nEOF\n")
    _discard_temp_dxf(inside)
    assert not ours.exists()
