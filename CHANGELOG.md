# Changelog

## v0.1.2 — 2026-08-07

The drawings colleagues send now open. Every one of the nine that used to fail
reads exactly what ODA File Converter reads from it, and `vendor/libredwg`
carries thirteen fixes — all of them submitted upstream. And there is finally
something to download: a self-contained AppImage.

### Added
- **A Linux AppImage** (`IngeCAD-<version>-x86_64.AppImage`, 112 MB). Python, Qt
  and both DWG converters travel inside it; download, `chmod +x`, run. Built by
  `.github/workflows/release.yml` on Ubuntu 22.04 — an AppImage links against
  the glibc of the machine that made it, so building on a current distro would
  produce a file that only starts on current distros.
- **`main.py --check`**, a self-diagnosis. It reports where the app found its
  shaders, translations, app icon and converters, whether the converters are the
  bundled ones, and exits non-zero if anything is missing. CI asserts on it after
  building the AppImage; run it when an install misbehaves.
- **`tools/libredwg-patches/build-vendor.sh`** rebuilds `vendor/libredwg` from a
  pristine LibreDWG release plus the thirteen patches, verifying the tarball
  against the project's own `dist.sha256`. `vendor/` is gitignored, so before
  this a fresh clone had no converters at all — and no way to get the patched
  ones. Verified reproducible: a from-scratch rebuild gives a `dwg2dxf` differing
  in 20 bytes, all inside `.note.gnu.build-id`.
- **`packaging/`** — the PyInstaller spec and the AppImage build script, so the
  packaging can be reproduced and reviewed rather than living in CI only.

### Fixed
- **Duplicate handles no longer cost the whole drawing.** LibreDWG emits some
  objects (LAYOUT, GROUP, ACDBPLACEHOLDER…) with a handle that already belongs
  to a table record. One collision on handle `2` (the `*Model_Space`
  BLOCK_RECORD) was enough for ezdxf to refuse the file outright.
  `formats/dwg_bridge.py::_dedupe_handles` gives the later claimant a fresh
  handle; the first user keeps its own. Reported upstream as LibreDWG#1356.
- **A single corrupt coordinate no longer swallows the drawing.** `cofopri`
  loaded its 5725 entities and showed a blank canvas, because one `LAYOUT`
  reached 6.7e+301 and `Zoom Extents` framed 10³⁰¹. `render/batches.py::
  _world_extents` now frames using the drawing's own `$EXTMIN`/`$EXTMAX`, with a
  safeguard that distrusts a stale box (if it would reject more than 5% of the
  vertices, it is ignored).
- **A DXF byte `0x85` no longer corrupts the file we rewrite.**
  `str.splitlines()` also breaks on `\x0b \x0c \x1c-\x1e \x85`, and latin-1
  maps `0x85` to U+0085, so real drawings gained phantom lines and every
  tag/value pair after the first one went off by one. `_read_dxf_lines` /
  `_write_dxf_lines` split on `"\n"` alone.
- **The status bar no longer paints two texts in the same pixels.** `main()`
  opened the drawing from `argv[1]` *before* showing the window, and QStatusBar
  only hides the coordinate readout for a message when the readout is already
  visible — so "Opening x…" was rendered on top of the coordinates, both
  illegible. The window is shown first, the coordinate slot has exactly one
  writer, and every notice ("Opened x", "Saved x", the F7/F8/F9 toggles, "PDF
  saved") moved to the command line, where an AutoCAD user reads them and where
  the history keeps them.
- **Every opened `.dwg` used to leak its converted DXF.** 189 orphaned
  `/tmp/ingecad-dwg-*` directories, 2.4 GB — and `/tmp` is a tmpfs on most
  desktops, so that was RAM. The temp directory is removed once ezdxf has the
  document in memory.

### Changed
- **`vendor/libredwg` is no longer stock.** It is built from `0.14.8556` plus
  **thirteen fixes**, every one open as a pull request upstream and every one
  verified on a clean tree with that patch alone. Measured over 190 real
  drawings, stock against the thirteen: **12 drawings improve, 0 get worse,
  +87 314 entities (+5.9%)**. The DWG that `dxf2dwg` writes is byte-identical
  either way, so saving is untouched. `vendor/libredwg.stock-0.14.8556` is kept
  alongside, so one `cp -a` reverts.
- Of the nine drawings that used to fail, **all nine now match ODA File
  Converter entity for entity** — `frontal` 0 → 1039, `cerco perimetrico`
  0 → 2222, both `Planos Constructivos` 0 → 26583, `sedapar` 93 → 10847,
  `primer piso` and `segundo piso` from no output at all to 1246 and 1459.
- Four of the thirteen fix **other people's issues**, three of them long open:
  LibreDWG#1294 (2026), #767 (2023), #523 (2022, four reporters) and #1012.

### Notes
- The thirteen patches are catalogued in `tools/libredwg-patches/README.md`, and
  the session that produced them, with the measurements and the two dead ends,
  in `docs/bugs-libredwg-2026-08-06.md`.
- Still open upstream and worked around here: LibreDWG#1356, the duplicate
  handles. `_dedupe_handles` goes away when it lands.

## v0.1.1 — 2026-07-20

Desktop-integration polish: a refreshed application icon and branded file
icons for the drawings you work with.

### Added
- **Branded document icons for `.dwg` and `.dxf`** — a document sheet with a
  format label and the IngeCAD badge, generated by `scripts/gen_doc_icons.py`
  and fanned out to hicolor mimetype PNGs plus `.ico` files. A freedesktop
  MIME package (`resources/mime/ingecad.xml`) claims the extensions/magic at
  high priority so real drawings resolve to `image/vnd.dwg` / `image/vnd.dxf`
  and show the icon even when another CAD package is installed.

### Changed
- Refreshed the application icon (`resources/ingecad.svg`) and regenerated the
  rasterised sizes.
- `scripts/install-desktop.sh` now installs the document icons into the active
  icon theme **and its parents** (not just hicolor), so they win over a
  theme's generic image icon; it also refreshes the icon and MIME caches.

## v0.1.0 — 2026-07-18

First usable release: the free "AutoCAD LT" workflow for Linux, end to end.

### Highlights
- Faithful rendering of real-world DWG/DXF (nested blocks, MTEXT, hatch
  patterns, linetypes, dimensions, OCS, paperspace layouts) on a GPU
  viewport that stays fluid on 90k+ entity drawings.
- Transparent DWG open/save through GNU LibreDWG (r2000 write, with a
  verified-save round-trip check) and optional ODA File Converter export
  (r2018). Numerous LibreDWG encoder/decoder fixes were developed against
  a 1,385-file corpus (99% now convert) and are being upstreamed.
- Classic pre-ribbon UI with a real command line and `acad.pgp`-compatible
  aliases; Model/Layout tabs; Layers, Properties and Styles panels.
- Full 2D drafting set: draw (line, circle, arc, polyline, rectangle,
  polygon, text, hatch, dimensions), edit (erase, move, copy, rotate,
  scale, mirror, offset, trim, extend, fillet, explode), grips,
  window/crossing selection, object snaps with AutoSnap markers,
  ORTHO/POLAR, coordinate input, blocks, undo/redo.
- Print / PDF / PNG export at exact scale.

### Performance (large drawings)
- Incremental snap/pick caches: drawing, pasting and moving never rebuild
  the whole index (was seconds of freeze per click on big files).
- Ghost previews tessellate once, in the background; big paste/move
  commits reuse them as "stamps" (a 3000-entity paste: 45 s → 0.13 s).
- Vectorized selection (window/crossing ~20 ms on 1.35M segments), cached
  highlight/grips, background cache warm-up at open, 1 ms GIL slicing so
  background regens never stutter the crosshair.

### Fidelity fixes
- Patched an ezdxf 1.4.4 bug where any transform re-rotated hatch
  patterns cumulatively (report to upstream in progress).
- UTF-8 → codepage conversion, MTEXT sizing, handle-collision and many
  more DWG round-trip fixes in the bundled LibreDWG patch set.
