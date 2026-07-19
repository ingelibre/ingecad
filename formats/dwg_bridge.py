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


def _run(cmd: list[str], out_path: Path) -> str:
    """Run a converter; return its stderr so callers can inspect warnings."""
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
    return proc.stderr or ""


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


def _converter_errors(stderr: str) -> list[str]:
    """Genuinely fatal-looking lines the LibreDWG writer emitted.

    NOTE: "Duplicate handle ..." is deliberately excluded — LibreDWG logs it
    from a relative-handle optimisation even for files that open perfectly, so
    it is noise here, not a verdict. The reliable net is the entity-count
    re-read below; this only flags other, rarer hard errors.
    """
    hits: list[str] = []
    for line in (stderr or "").splitlines():
        s = line.strip()
        if not s or "Duplicate handle" in s:
            continue
        if (s.startswith("ERROR")
                or "can't be cast" in s
                or "improperly read" in s
                or "out of memory" in s.lower()):
            hits.append(s)
    return hits


def _modelspace_count(dxf_path: Path) -> int:
    """Count model-space entities in a DXF, tolerating a broken re-read."""
    import ezdxf
    from ezdxf import recover

    try:
        doc = ezdxf.readfile(dxf_path)
    except Exception:
        doc, _auditor = recover.readfile(dxf_path)
    return sum(1 for _ in doc.modelspace())


def verify_dwg(source_dxf: Path, dwg_path: Path, stderr: str = "") -> list[str]:
    """Check a just-written DWG and return human-readable warnings (empty = OK).

    Two cheap checks that need no proprietary tool:
    1. Did the LibreDWG writer raise any error while packing the file?
    2. Re-open the DWG and confirm the model-space entity count survived.

    This is a safety net, not a guarantee: a bug LibreDWG both writes AND
    reads the same wrong way (a "mirror" bug a strict parser would still
    reject) can slip through. The developer bench (ODA/BricsCAD) covers those.
    """
    warnings: list[str] = []
    if _converter_errors(stderr):
        warnings.append(
            "the DWG writer reported internal errors while packing the file")
    try:
        n_src = _modelspace_count(source_dxf)
        n_back = _modelspace_count(dwg_to_dxf(dwg_path))
        # A drop means geometry was lost. Allow tiny bookkeeping deltas.
        if n_src and n_back < n_src:
            warnings.append(
                f"some drawing objects did not survive the save "
                f"({n_src} → {n_back})")
    except Exception:
        warnings.append("could not re-open the saved DWG to verify it")
    return warnings


def write_dwg(dxf_path: Path, dwg_path: Path) -> list[str]:
    """Write a DWG from a DXF via LibreDWG (r2000), then verify it.

    IngeCAD ships a patched LibreDWG and writes AutoCAD r2000 (opens in every
    AutoCAD/BricsCAD since 2000). r2000 is an older container, so paper-space
    layout settings and a few r2013+ display features are simplified on the
    way out; the geometry, layers, blocks, text and hatches round-trip
    faithfully. Returns verification warnings (empty list = clean save).
    """
    stderr = dxf_to_dwg(dxf_path, dwg_path)
    return verify_dwg(Path(dxf_path), Path(dwg_path), stderr)


def dxf_to_dwg(dxf_path: Path, dwg_path: Path, version: str = "r2000") -> str:
    """Convert a DXF to DWG; return the converter's stderr."""
    tool = find_dxf2dwg()
    if tool is None:
        raise DwgBridgeError("LibreDWG (dxf2dwg) is not available")
    dwg_path = Path(dwg_path)
    return _run(
        [str(tool), "-y", "--as", version, "-o", str(dwg_path), str(Path(dxf_path))],
        dwg_path,
    )
