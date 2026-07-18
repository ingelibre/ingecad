# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""DWG <-> DXF bridge through LibreDWG satellite processes.

DWG is never parsed inside the app (architectural principle #2): the
LibreDWG command-line tools run as external converters, the same satellite
pattern IngeTrazo uses for skp2dae. The user double-clicks a ``.dwg`` and
never sees the intermediate DXF.

Search order for the tools: the bundle shipped with IngeCAD
(``vendor/libredwg/bin``), then the system PATH. IngeCAD ships a patched
LibreDWG that reads DWG up to r2018 and writes r2000; r2013/r2018 write
support arrives with LibreDWG Track L progress (no proprietary satellite).
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

_VENDOR_BIN = Path(__file__).resolve().parent.parent / "vendor" / "libredwg" / "bin"
_TIMEOUT = 300  # seconds; big real-world DWGs convert in well under this


class DwgBridgeError(Exception):
    """A DWG conversion failed or no converter is available."""


def _find_tool(name: str) -> Optional[Path]:
    bundled = _VENDOR_BIN / name
    if bundled.is_file():
        return bundled
    system = shutil.which(name)
    return Path(system) if system else None


def find_dwg2dxf() -> Optional[Path]:
    return _find_tool("dwg2dxf")


def find_dxf2dwg() -> Optional[Path]:
    return _find_tool("dxf2dwg")


def have_dwg_support() -> bool:
    return find_dwg2dxf() is not None


def _run(cmd: list[str], out_path: Path) -> None:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise DwgBridgeError(f"converter timed out: {' '.join(cmd)}") from exc
    # LibreDWG often exits non-zero on recoverable warnings while still
    # writing a usable file — the output's existence is the real verdict.
    if not out_path.is_file() or out_path.stat().st_size == 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
        raise DwgBridgeError(
            "conversion produced no output: " + (" | ".join(tail) or f"rc={proc.returncode}")
        )


def _strip_null_handles(dxf_path: Path) -> None:
    """Drop (5, 0) tag pairs from an ASCII DXF.

    LibreDWG 0.14 emits ENDBLK entities with handle 0 ("Empty ENDBLK"
    warning), which ezdxf rejects even in recover mode; with the pair gone,
    recover assigns a fresh handle. Latin-1 keeps the bytes lossless in both
    directions. Track L: minimized, to be reported upstream.
    """
    lines = dxf_path.read_bytes().decode("latin-1").splitlines(keepends=True)
    out: list[str] = []
    dropped = 0
    i = 0
    while i + 1 < len(lines):  # ASCII DXF is a strict tag/value pair stream
        if lines[i].strip() == "5" and lines[i + 1].strip() == "0":
            dropped += 1
            i += 2
            continue
        out.append(lines[i])
        out.append(lines[i + 1])
        i += 2
    out.extend(lines[i:])
    if dropped:
        dxf_path.write_bytes("".join(out).encode("latin-1"))


def dwg_to_dxf(dwg_path: Path) -> Path:
    """Convert a DWG to a temporary DXF; returns the DXF path.

    The temp file lands in a fresh ASCII-only directory: satellite argv
    encoding is a known gotcha family (skp2dae), so the *output* side stays
    plain even when the input drawing name carries accents.
    """
    tool = find_dwg2dxf()
    if tool is None:
        raise DwgBridgeError("LibreDWG (dwg2dxf) is not available")
    dwg_path = Path(dwg_path)
    out_dir = Path(tempfile.mkdtemp(prefix="ingecad-dwg-"))
    out_dxf = out_dir / "converted.dxf"
    _run([str(tool), "-y", "-o", str(out_dxf), str(dwg_path)], out_dxf)
    _strip_null_handles(out_dxf)
    return out_dxf


def load_dwg(dwg_path: Path):
    """Open a DWG as a Document via LibreDWG.

    LibreDWG reads up to r2018. Output is validated — for some r2013+
    drawings (AcDs segments) it can emit structurally broken DXF where
    recover salvages the entity database but modelspace comes out empty.
    A published sheet with content only in a paperspace layout is a
    legitimate empty-modelspace case (the renderer falls back to it).
    """
    from core.document import Document

    dwg_path = Path(dwg_path)
    document = Document.load(dwg_to_dxf(dwg_path))
    document.path = dwg_path
    if len(document.modelspace()) > 0:
        return document
    # Empty modelspace is legitimate for published sheets (ArchiCAD etc.):
    # the content lives in a paperspace layout and the renderer falls back
    # to it. Only a big entitydb with NO layout content anywhere means the
    # conversion salvaged structure but lost the drawing.
    if any(len(layout) > 0 for layout in document.doc.layouts
           if layout.name != "Model"):
        return document
    if len(document.doc.entitydb) <= 100:
        return document
    from core.i18n import tr

    raise DwgBridgeError(
        tr("LibreDWG could not fully convert this DWG. The file may be "
           "damaged or use an unsupported AutoCAD feature.")
    )


def write_dwg(dxf_path: Path, dwg_path: Path) -> str:
    """Write a DWG from a DXF via LibreDWG (r2000).

    IngeCAD ships a patched LibreDWG and writes AutoCAD r2000 (opens in every
    AutoCAD/BricsCAD since 2000). r2000 is an older container, so paper-space
    layout settings and a few r2013+ display features are simplified on the
    way out; the geometry, layers, blocks, text and hatches round-trip
    faithfully. Returns the engine used: "libredwg".
    """
    dxf_to_dwg(dxf_path, dwg_path)
    return "libredwg"


def dxf_to_dwg(dxf_path: Path, dwg_path: Path, version: str = "r2000") -> None:
    """Convert a DXF to DWG (LibreDWG writes r2000 reliably)."""
    tool = find_dxf2dwg()
    if tool is None:
        raise DwgBridgeError("LibreDWG (dxf2dwg) is not available")
    dwg_path = Path(dwg_path)
    _run(
        [str(tool), "-y", "--as", version, "-o", str(dwg_path), str(Path(dxf_path))],
        dwg_path,
    )
