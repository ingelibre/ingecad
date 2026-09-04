# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""DWG <-> DXF bridge through satellite processes: LibreDWG and Open CAD Studio.

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

from core.paths import app_root

_VENDOR_BIN = app_root() / "vendor" / "libredwg" / "bin"
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


def converter_path(name: str) -> Optional[Path]:
    """Any LibreDWG tool we ship, by name (``dwgbmp`` for thumbnails)."""
    return _find_tool(name)


# ---- Open CAD Studio, the second satellite ---------------------------------
# https://github.com/HakanSeven12/OpenCADStudio (GPL-3, Rust): native DWG
# R14–2018 read AND write through its ``--export in out`` command line. It
# covers what LibreDWG cannot — writing r2018, and Windows, where no
# dwg2dxf.exe ships yet — and doubles as a fallback reader. Same rule as
# always: an external process, the DWG is never parsed inside IngeCAD.
_OCS_ENV = "INGECAD_OPENCADSTUDIO"


def _ocs_candidates() -> list[Path]:
    import os
    import sys
    out: list[Path] = []
    env = os.environ.get(_OCS_ENV)
    if env:
        out.append(Path(env))
    for name in ("OpenCADStudio", "opencadstudio", "open-cad-studio"):
        found = shutil.which(name)
        if found:
            out.append(Path(found))
    home = Path.home()
    if sys.platform.startswith("win"):
        for base in (os.environ.get("ProgramFiles"),
                     os.environ.get("ProgramW6432"),
                     os.environ.get("LOCALAPPDATA")):
            if base:
                out.append(Path(base) / "Open CAD Studio" / "OpenCADStudio.exe")
                out.append(Path(base) / "Programs" / "Open CAD Studio"
                           / "OpenCADStudio.exe")
    elif sys.platform == "darwin":
        out.append(Path("/Applications/OpenCADStudio.app/Contents/MacOS/OpenCADStudio"))
    else:
        for folder in (home / "Aplicaciones", home / "Applications",
                       home / ".local" / "bin", home / "Descargas",
                       home / "Downloads", Path("/opt/opencadstudio")):
            try:
                images = sorted(folder.glob("OpenCADStudio-*.AppImage"))
            except OSError:
                images = []
            out.extend(reversed(images))        # the newest version first
            out.append(folder / "OpenCADStudio.AppImage")
    return out


def find_opencadstudio() -> Optional[Path]:
    """The Open CAD Studio executable, or None. Looked up in this order:
    the ``INGECAD_OPENCADSTUDIO`` environment variable, the PATH, the
    platform's usual install folders (Program Files, /Applications, the
    user's Aplicaciones / Downloads for the AppImage)."""
    import os
    for cand in _ocs_candidates():
        try:
            if cand.is_file() and os.access(cand, os.X_OK):
                return cand
        except OSError:
            continue
    return None


_DXF_VERSIONS = {"r2004": "AC1018", "r2007": "AC1021", "r2010": "AC1024",
                 "r2013": "AC1027", "r2018": "AC1032"}


def _upgrade_dxf(dxf_path: Path, version: str) -> Path:
    """A copy of *dxf_path* saved as DXF *version* (ezdxf upgrades in
    place; a failure leaves the original to go through as it is)."""
    target = _DXF_VERSIONS.get(version.lower())
    if target is None:
        return dxf_path
    try:
        import ezdxf
        doc = ezdxf.readfile(str(dxf_path))
        if doc.dxfversion >= target:
            return dxf_path
        doc.dxfversion = target
        out = dxf_path.with_name(dxf_path.stem + f"-{version.lower()}.dxf")
        doc.saveas(str(out))
        return out
    except Exception:  # noqa: BLE001 — the upgrade is best effort
        return dxf_path


def _ocs_export(src: Path, dst: Path) -> str:
    """``OpenCADStudio --export src dst``: the extension decides the format."""
    tool = find_opencadstudio()
    if tool is None:
        raise DwgBridgeError("Open CAD Studio is not available")
    return _run([str(tool), "--export", str(src), str(dst)], dst)


def have_dwg_support() -> bool:
    """Can we read a DWG at all — LibreDWG, or Open CAD Studio as fallback."""
    return find_dwg2dxf() is not None or find_opencadstudio() is not None


def dwg_write_engine(version: str = "r2000") -> str:
    """Which satellite writes DWG *version*: ``"libredwg"`` (r2000, bundled),
    ``"opencadstudio"`` (r2018 native, or r2000 when LibreDWG is missing),
    or ``""`` when nothing can."""
    version = (version or "r2000").lower()
    if version == "r2000" and find_dxf2dwg() is not None:
        return "libredwg"
    if find_opencadstudio() is not None:
        return "opencadstudio"
    if find_dxf2dwg() is not None:
        return "libredwg"
    return ""


def converters_status() -> list[tuple[str, Optional[Path]]]:
    """Every DWG satellite and where it was found (``--check``, About)."""
    return [("LibreDWG dwg2dxf", find_dwg2dxf()),
            ("LibreDWG dxf2dwg", find_dxf2dwg()),
            ("Open CAD Studio", find_opencadstudio())]


def _run(cmd: list[str], out_path: Path) -> str:
    """Run a converter; return its stderr so callers can inspect warnings."""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            # The converter echoes names from the drawing into its warnings,
            # and those are in the file's own codepage, not UTF-8: a layer
            # called CAÑERÍAS made the decode raise and took the whole save
            # down with it. Its log is diagnostics — never a reason to fail.
            encoding="utf-8",
            errors="replace",
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


def _read_dxf_lines(dxf_path: Path) -> list[str]:
    r"""Split an ASCII DXF into lines on "\n" only.

    Not ``str.splitlines()``: that also breaks on \x0b, \x0c, \x1c-\x1e and
    \x85, and latin-1 turns byte 0x85 into U+0085. Real drawings do carry that
    byte (binary chunks, accented text), so splitlines() invents phantom lines
    and every tag/value pair after the first one is off by one — which silently
    turns a handle rewrite into a corrupted group code. Latin-1 plus a plain
    "\n" split keeps the byte stream exact in both directions.
    """
    return dxf_path.read_bytes().decode("latin-1").split("\n")


def _write_dxf_lines(dxf_path: Path, lines: list[str]) -> None:
    dxf_path.write_bytes("\n".join(lines).encode("latin-1"))


def _strip_null_handles(dxf_path: Path) -> None:
    """Drop (5, 0) tag pairs from an ASCII DXF.

    LibreDWG 0.14 emits ENDBLK entities with handle 0 ("Empty ENDBLK"
    warning), which ezdxf rejects even in recover mode; with the pair gone,
    recover assigns a fresh handle. Track L: minimized, to be reported upstream.
    """
    lines = _read_dxf_lines(dxf_path)
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
        _write_dxf_lines(dxf_path, out)


#: Sections whose objects carry a handle in group 5. HEADER is excluded on
#: purpose: there group 5 is the *value* of $HANDSEED, not an object handle.
_HANDLE_SECTIONS = frozenset({"TABLES", "BLOCKS", "ENTITIES", "OBJECTS"})

#: Handles above this are already corrupt (real ones stay far below), so they
#: must not drag the fresh-handle counter into nonsense.
_MAX_SANE_HANDLE = 1 << 32


def _dedupe_handles(dxf_path: Path) -> int:
    """Give a fresh handle to objects that reuse one; returns how many.

    LibreDWG emits some objects (LAYOUT, GROUP, ACDBPLACEHOLDER...) with a
    handle that already belongs to a table record. Handles must be unique, so
    ezdxf resolves the handle to whichever object it read *last*, and one
    collision is enough to lose the whole drawing: when handle 2 (the
    ``*Model_Space`` BLOCK_RECORD) is stolen, ezdxf reports either
    ``expected BLOCK_RECORD(#2) for layout 'Model'`` or
    ``Invalid DXF attribute "paperspace" for entity LAYOUT`` and refuses the file.

    The first user of a handle keeps it — table records are written before the
    OBJECTS section, so the first one is the legitimate owner — and later
    claimants are renumbered above every handle in the file. Anything that
    referenced a renumbered object was already ambiguous, so nothing that
    resolved before stops resolving.

    Reported upstream as LibreDWG#1356.
    """
    lines = _read_dxf_lines(dxf_path)

    # Pass 1: locate each object's handle line, and the $HANDSEED value line.
    spots: list[tuple[int, str]] = []  # (index of the value line, handle)
    seed_at: Optional[int] = None
    section: Optional[str] = None
    expecting = False  # a 0/NAME was just seen, its group 5 is still pending
    i = 0
    while i + 1 < len(lines):
        code, value = lines[i].strip(), lines[i + 1].strip()
        if code == "0":
            if value == "ENDSEC":
                section = None
            expecting = value not in ("SECTION", "ENDSEC", "EOF")
        elif code == "2" and section is None:
            section = value  # the 2/<name> right after 0/SECTION
        elif code == "9" and value == "$HANDSEED" and i + 3 < len(lines):
            seed_at = i + 3 if lines[i + 2].strip() == "5" else None
        elif code == "5" and expecting and section in _HANDLE_SECTIONS:
            spots.append((i + 1, value))
            expecting = False
        i += 2

    def as_int(handle: str) -> Optional[int]:
        try:
            return int(handle, 16)
        except ValueError:
            return None

    # Pass 2: keep the first claimant, renumber the rest.
    seen: set[str] = set()
    collisions: list[int] = []
    for idx, handle in spots:
        if handle in seen:
            collisions.append(idx)
        else:
            seen.add(handle)
    if not collisions:
        return 0

    used = {h for _, h in spots}
    sane = [n for n in (as_int(h) for _, h in spots) if n is not None and n < _MAX_SANE_HANDLE]
    nxt = (max(sane) if sane else 0) + 1
    for idx in collisions:
        while format(nxt, "X") in used:
            nxt += 1
        fresh = format(nxt, "X")
        used.add(fresh)
        lines[idx] = fresh
        nxt += 1

    # Keep $HANDSEED above everything we handed out, or a later writer collides.
    if seed_at is not None:
        lines[seed_at] = format(nxt, "X")

    _write_dxf_lines(dxf_path, lines)
    return len(collisions)


def dwg_to_dxf(dwg_path: Path) -> Path:
    """Convert a DWG to a temporary DXF; returns the DXF path.

    The temp file lands in a fresh ASCII-only directory: satellite argv
    encoding is a known gotcha family (skp2dae), so the *output* side stays
    plain even when the input drawing name carries accents.
    """
    tool = find_dwg2dxf()
    dwg_path = Path(dwg_path)
    out_dir = Path(tempfile.mkdtemp(prefix="ingecad-dwg-"))
    out_dxf = out_dir / "converted.dxf"
    if tool is not None:
        try:
            _run([str(tool), "-y", "-o", str(out_dxf), str(dwg_path)], out_dxf)
            _strip_null_handles(out_dxf)
            _dedupe_handles(out_dxf)
            return out_dxf
        except DwgBridgeError:
            # LibreDWG could not read it: Open CAD Studio gets a turn before
            # the user sees an error (a drawing BricsCAD writes that trips the
            # r2018 AcDs walker, for one).
            if find_opencadstudio() is None:
                raise
            out_dxf.unlink(missing_ok=True)
    if find_opencadstudio() is None:
        raise DwgBridgeError(
            "no DWG converter available (LibreDWG dwg2dxf or Open CAD Studio)")
    _ocs_export(dwg_path, out_dxf)
    _dedupe_handles(out_dxf)
    return out_dxf


def _discard_temp_dxf(dxf_path: Path) -> None:
    """Remove a directory ``dwg_to_dxf`` made, once its DXF has been read.

    ``ezdxf.readfile`` loads the whole document into memory, so the DXF is
    disposable the moment it returns — and on most desktops ``/tmp`` is a
    tmpfs, which makes a leaked 50 MB DXF per opened drawing 50 MB of RAM that
    never comes back. Recognised by prefix and no other way: tests monkeypatch
    ``dwg_to_dxf`` to hand back fixture paths that must survive.
    """
    parent = dxf_path.parent
    if parent.name.startswith("ingecad-dwg-"):
        shutil.rmtree(parent, ignore_errors=True)


def load_dwg(dwg_path: Path):
    """Open a DWG as a Document via LibreDWG.

    LibreDWG reads up to r2018. Output is validated — for some r2013+
    drawings (AcDs segments) it can emit structurally broken DXF where
    recover salvages the entity database but modelspace comes out empty.
    A published sheet with content only in a paperspace layout is a
    legitimate empty-modelspace case (the renderer falls back to it).
    """
    from core.document import Document

    from core.encoding import decode_escapes_in_document, repair_invalid_defaults
    from core.layouts import repair_viewport_status

    dwg_path = Path(dwg_path)
    dxf_path = dwg_to_dxf(dwg_path)
    try:
        document = Document.load(dxf_path)
    finally:
        _discard_temp_dxf(dxf_path)
    # \U+xxxx is what AutoCAD writes for a character its codepage cannot
    # hold — and what we write ourselves on save (see core.encoding). ezdxf
    # does not decode it, so without this the canvas shows the raw code.
    decode_escapes_in_document(document.doc)
    # DWGs IngeCAD saved before v0.4.5 carry zeroed MTEXT spacing (the
    # missing-group-becomes-zero bug this same module now writes around):
    # normalize them so those files render right again.
    repair_invalid_defaults(document.doc)
    # A DWG does not store the DXF viewport status; LibreDWG derives it from
    # entmode and gets it wrong for every layout but the one that was current
    # on save, which left those sheets blank.
    repair_viewport_status(document.doc)
    document.path = dwg_path
    if len(document.doc.modelspace()) > 0:
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
        back_dxf = dwg_to_dxf(dwg_path)
        try:
            n_back = _modelspace_count(back_dxf)
        finally:
            _discard_temp_dxf(back_dxf)
        # A drop means geometry was lost. Allow tiny bookkeeping deltas.
        if n_src and n_back < n_src:
            warnings.append(
                f"some drawing objects did not survive the save "
                f"({n_src} → {n_back})")
    except Exception:
        warnings.append("could not re-open the saved DWG to verify it")
    return warnings


def write_dwg(dxf_path: Path, dwg_path: Path, version: str = "r2000") -> list[str]:
    """Write a DWG from a DXF, then verify it. ``version`` r2000 goes through
    LibreDWG (bundled); r2018 through Open CAD Studio (native writer), which
    also stands in for r2000 when LibreDWG is missing (Windows).

    IngeCAD ships a patched LibreDWG and writes AutoCAD r2000 (opens in every
    AutoCAD/BricsCAD since 2000). r2000 is an older container, so paper-space
    layout settings and a few r2013+ display features are simplified on the
    way out; the geometry, layers, blocks, text and hatches round-trip
    faithfully. Returns verification warnings (empty list = clean save).
    """
    stderr = dxf_to_dwg(dxf_path, dwg_path, version)
    return verify_dwg(Path(dxf_path), Path(dwg_path), stderr)


def dxf_to_dwg(dxf_path: Path, dwg_path: Path, version: str = "r2000") -> str:
    """Convert a DXF to DWG; return the converter's stderr. The engine is
    :func:`dwg_write_engine`'s pick for *version*; Open CAD Studio writes
    its native r2018 container whatever *version* says."""
    engine = dwg_write_engine(version)
    dwg_path = Path(dwg_path)
    if engine == "libredwg":
        tool = find_dxf2dwg()
        return _run(
            [str(tool), "-y", "--as", version, "-o", str(dwg_path), str(Path(dxf_path))],
            dwg_path,
        )
    if engine == "opencadstudio":
        src = Path(dxf_path)
        if version.lower() in ("r2018", "r2013", "r2010", "r2007", "r2004"):
            # Open CAD Studio keeps the source DXF's version: an r2000 DXF
            # comes back as an r2000 DWG. "DWG 2018" means a 2018 DWG, so
            # the intermediate is lifted to that version first.
            src = _upgrade_dxf(src, version)
        return _ocs_export(src, dwg_path)
    raise DwgBridgeError(
        "no DWG writer available (LibreDWG dxf2dwg or Open CAD Studio)")
