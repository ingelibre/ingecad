# Changelog

## v0.3.0 — 2026-08-11

A day of dogfooding against AutoCAD and BricsCAD V26, command by command:
Marco drew in IngeCAD with BricsCAD open beside it and every divergence
became a fix or a feature. The headline is the MTEXT in-place editor,
built from the official In-Place Text Editor chapter of the AutoCAD 2011
Command Reference (pp. 1221–1244).

### Added — the MTEXT in-place editor
- **Edit on the canvas**, at the text's real size and position, drawing
  visible behind: Enter is a paragraph break, Ctrl+Enter / OK / clicking
  outside commits, Esc asks before discarding. Double-click an MTEXT to
  edit it; TEXT keeps its single-line in-place editing.
- **The Text Formatting toolbar**: style, font, height, bold, italic,
  underline, overline, colour, justification (all nine positions) — each
  written as AutoCAD's own inline codes (`\f`, `\H`, `\L`, `\O`, `\C`),
  so the file reads identically in AutoCAD.
- **The ruler**: first-line and hanging indent sliders, tab stops with the
  L/C/R tab-type button, the width arrow (drag to resize, double-click to
  fit), all stored as `\px` paragraph codes.
- **Line spacing** (1.0x/1.5x/2.0x/2.5x/More…/Clear) and **bullets and
  numbered/lettered lists**: Enter continues the list, Enter on an empty
  item ends it, `1.` or `-` plus Tab starts one — plain text plus indents,
  exactly the construction AutoCAD writes.
- **Background mask** (border offset factor, fill colour or drawing
  background) and **static columns** with the Column Settings dialog.
- Formatting the editor cannot represent losslessly (stacked fractions,
  fields, oblique/width/tracking overrides) opens in a raw-code mode
  instead of being silently mangled — by-construction: the rich mode only
  opens when serializing back reproduces the original bytes.
- Fixed along the way: bold/italic rendered exactly like regular text on
  the canvas (ezdxf's font matcher filtered by style before weight and
  never reached the bold face — runtime-patched); a background mask on
  unformatted text never rendered; masks vanished at low zoom (the LOD
  culling treated the mask quad as illegible text); the caret opened
  below the visible area; the mouse pointer vanished over the toolbar
  and ruler (the canvas hides the OS cursor — the crosshair is the
  cursor — and child widgets inherited it).

### Added — editing, to AutoCAD's prompt trees
- **STRETCH** (crossing selection semantics), **BREAK** (first/second
  point, `@` for break-at-point), **JOIN**, **CHAMFER** (distances,
  angle, polyline, Undo), **ARRAY** (rectangular/polar), **MATCHPROP**
  with its Settings list, **PEDIT** (open/close, join, width, and vertex
  editing).
- **OFFSET grown to the full tree**: distance by mouse (two picks),
  Through, Erase, Layer — and it offsets **polylines as one entity**,
  arcs included, like AutoCAD.
- **ROTATE and SCALE preview live**: the selection turns/scales under the
  cursor around the base point, with Reference and Copy options.
- Object snaps work **on curves** (circles, arcs, ellipses, splines,
  polyline arc segments), plus **QUA** on every round shape, **TAN**,
  **INS** and **GCE** (geometric center) — with their AutoSnap markers.
- **The running object snap list** on the status bar, AutoCAD's own
  (right-click the OSNAP button): per-mode checkboxes, Select All /
  Clear All, and the Drafting Settings dialog.

### Added — the working session
- **SAVE / Ctrl+S** (with save-as when untitled), **UNITS** (mm/cm/m,
  the AutoCAD dialog), and the inquiry commands **DIST / ID / AREA /
  LIST**.
- **A startup window** like BricsCAD's: pick the template unit, or reopen
  a recent drawing from its thumbnail.
- **Command prefix autocomplete**: an unambiguous prefix runs the command
  (`OFF` → OFFSET), aliases still win, ambiguity resolves alphabetically
  — AutoCAD's AutoComplete rule.
- **Properties bar completed**: linetype, lineweight and colour of the
  selection, and the current-properties defaults for new entities
  ($CECOLOR/$CELTYPE/$CELWEIGHT round-trip to the DXF header).
- **The Modify toolbar icons redrawn from AutoCAD's own** (traced from a
  screenshot, not from memory — the first attempt proved memory draws
  the wrong icons).
- The crosshair yields to AutoCAD's pickbox-only cursor while a command
  is choosing objects, and returns for point picks.
- Fixed: Ctrl+Y did nothing (the redo key was bound twice, so Qt fired
  neither); selecting an ellipse highlighted its bounding rectangle.

### Packaging
- **New artifact: a plain tarball** (`IngeCAD-<version>-linux-x86_64.tar.gz`)
  — the same self-contained build as the AppImage without the FUSE
  requirement: extract and run `./ingecad`. Ships the desktop file and
  icon for manual integration.

## v0.2.0 — 2026-08-10

Paper space and the complete dimension family. Everything in this release was
built the same way: fetch the official AutoCAD documentation first (BricsCAD
cross-checked — its option lists match AutoCAD's in every command we compared),
then implement the exact prompt tree, then verify the result live against the
reference. If AutoCAD prints `Specify dimension line location or
[Mtext/Text/Angle/Horizontal/Vertical/Rotated]:`, so does IngeCAD.

### Added — paper space (Model/Layout, the AutoCAD idiom end-to-end)
- **Layout tabs** under the canvas (Model / Layout1 / …) with the LAYOUT
  command (New/Copy/Rename/Delete/Set), the paper sheet drawn with its
  printable-area margin, and the classic right-click tab menu.
- **MVIEW floating viewports**: model content renders inside viewports on the
  sheet; viewports are real selectable paper-space entities with grips
  (move/resize/erase, undo like everything else).
- **Exact viewport scale**: MSPACE/PSPACE (double-click too) and **ZOOM nXP**
  (`1/50xp` = 1:50), a Viewports toolbar with the standard-scale dropdown,
  wheel zoom + middle-drag pan inside the active viewport, and **VPLOCK** so
  a set scale can't be nudged by a stray wheel tick.
- **PAGESETUP** rebuilt as AutoCAD's Page Setup dialog, group by group
  (printer/paper/area/offset/scale/orientation/options), stored per layout in
  the DXF plot settings like AutoCAD stores them.
- **PLOT of a layout**: the sheet maps to paper at 1:1 (viewports carry the
  scale), pens in physical millimetres (0.25 mm default), viewport frames
  plotted only when their flag says so. Verified with a ruler on the PDF.

### Added — the dimension family, complete
- **DIMANGULAR** (`DAN`): all four official paths — arc, circle, two lines,
  Enter-for-vertex. The location pick chooses *which* angle (90° or its 270°
  explement), and **Quadrant** locks the region.
- **DIMARC** (`DAR`): arc-length dimension of an arc or a polyline arc
  segment, with **Partial**.
- **DIMORDINATE** (`DOR`): X/Y datum with the official auto rule (leader
  direction picks the axis) and Xdatum/Ydatum forcing.
- **DIMCENTER** (`DCE`): center mark or center lines per DIMCEN, the exact
  AutoCAD geometry.
- **DIMCONTINUE / DIMBASELINE** (`DCO`/`DBA`): chain from the session's last
  linear dimension (or Select a base); continue keeps the base's dimension
  line, baseline stacks each line DIMDLI beyond the previous; Undo inside the
  command drops the last link; the chained dims inherit the base's style.
- **DIMTEDIT** (`DIMTED`): move a dimension's text to any point, or
  Left/Right/Center/Home/Angle.
- **Every dim tool** (linear/aligned/radius/diameter included) now offers
  **Mtext/Text/Angle** at the location prompt — `<>` stands for the measured
  value ("`<> m`" renders as "12.50 m", radius keeps its R prefix), a space
  suppresses the text, Angle rotates it. DIMLINEAR adds
  **Horizontal/Vertical/Rotated** and select-object now handles circles (the
  official quadrant rule) and polyline segments.

### Added — construction commands
- **XLINE** (`XL`) with the full option tree (Hor/Ver/Ang+Reference/Bisect/
  Offset+Through) and **RAY**: real construction-line entities.
- **DIVIDE / MEASURE** (`DIV`/`ME`): points or aligned blocks along any curve
  (MEASURE steps from the end nearest the pick, official rule); each command
  is ONE undo step.
- **REVCLOUD**: Rectangular/Polygonal/Freehand/Object (+Reverse), sticky arc
  length, Normal/Calligraphy styles — the scalloped cloud AutoCAD draws.

### Changed — drawing commands brought to prompt-tree parity
- **ARC**: the full 11-way construction matrix (3P, S-C-E, S-C-Angle,
  S-C-chord Length, S-E-Angle, S-E-Radius, S-E-Direction, center-first forms,
  Continue from last). **CIRCLE**: 2P/3P/TTR and Diameter with sticky radius.
  **LINE**: Continue chain, tangent lock after an arc, real mid-command Undo.
  **PLINE**: arc mode with tangent chaining, Width/Halfwidth taper, Close in
  both modes. **RECTANG**: Chamfer/Fillet/Width/Elevation/Thickness, Area,
  Dimensions, Rotation. **POLYGON**: Edge, Inscribed/Circumscribed with the
  AutoCAD drag semantics. **ELLIPSE**: Arc (parametric, like AutoCAD) and
  Rotation; the axis-swap rule fixed to match the spec. **TEXT**: the 14
  justification anchors, Style, Align/Fit. **-HATCH**: the command-line hatch
  with Properties/Solid/User-defined/draW/Advanced/COlor.
- Session-sticky defaults where AutoCAD has them (CIRCLERAD, PLINEWID,
  POLYSIDES, rectangle modes, hatch pattern), and new toolbar icons for every
  new command.

### Added — the Dimension Style Manager (DIMSTYLE)
- `DIMSTYLE` (`D`) opens **AutoCAD's Dimension Style Manager**: styles list
  with the current one in bold, All styles / Styles in use filter, a live
  **preview that is a real render** (a sample drawing dimensioned with the
  selected style), description against the current style, Set Current / New /
  Modify, and the right-click Set current / Rename / Delete (guarded for the
  current and in-use styles).
- **Create New Dimension Style** (name + Start With) leads into the
  **New/Modify dialog with its five real tabs** — Lines, Symbols and Arrows,
  Text, Fit, Primary Units — every control mapped to its DIMVAR, including
  the ones that hide behind a sign or a flag (center-mark type = DIMCEN sign,
  frame-around-text = negative DIMGAP, prefix/suffix = DIMPOST around `<>`,
  the three text alignments = DIMTIH/DIMTOH). Alternate Units, Tolerances,
  Override and Compare are recorded gaps, not silent omissions.
- **Modifying a style re-renders every dimension drawn with it**, undo
  included — AutoCAD's own semantics.

### Added — layers, audited against the manual
- **`-LAYER` (`-LA`)**, the command-line variant with the official option
  loop (`?/Make/Set/New/Rename/ON/OFF/Color/Ltype/LWeight/Plot/Freeze/Thaw/
  LOck/Unlock/Description`), comma name lists, `*` wildcards, and the rules
  that make it feel right: a frozen layer cannot be made current, the current
  layer cannot be frozen, `Set` switches an off layer back on, a negative
  color assigns *and* turns off, an invalid lineweight snaps to the nearest
  fixed value. Each round is one undo step.
- The layer panel gains the **Status** column (current / in use / empty),
  a **Plot** toggle, an editable **Description**, and a live
  **Search for layer** box. A new layer inherits the selected layer's
  properties, and the delete guard now counts references in every layout and
  inside block definitions.
- **The Plot column reaches the plotter**: layers with plotting off still
  display but never print (rendered through ezdxf's export mode).

### Added — command line and menus
- **Transparent commands**: `'ZOOM` (`'Z`), `'PAN`, `'REDRAW` run in the
  middle of another command and print `>> Resuming LINE command.`
- **F2 opens the classic text window** (the full command history), and the
  command line's right-click menu offers Recent Commands / Copy / Copy
  History / Paste.
- **Space stays a space in text prompts** — typing `<> m` at
  `Enter dimension text <>:` works; before, Space executed the command and
  cut the override short.
- **Icons everywhere they were missing**: the whole Dimension menu plus a
  classic **Dimension toolbar** (with the current-style combo), and the
  File / Edit / View / Insert / Format menus.

### Changed — DWG engine
- `vendor/libredwg` re-based to release **0.14.8578 + 17 patches** (upstream
  absorbed 10 of our earlier fixes in the window). Exact read parity verified
  against the previous vendor over the full real-file bench: 0 worse.
- **Save as DWG stays r2000 on purpose.** The planned switch to r2004 hit a
  real LibreDWG encoder bug (object streams truncate on DXF-imported models,
  on stock and patched trees alike); documented upstream-ready in
  `tools/libredwg-patches/README.md` rather than shipping a broken writer.
  ODA File Converter (optional, one click) still covers r2013/r2018 export.

### Fixed
- Menus could vanish under memory pressure: the Qt menus were Python-owned
  with no live reference, so a garbage collection deleted them. Found by the
  new menu-icon test.

362 tests pass. The suite grew by ~110 tests across this release, all
headless, all runnable in CI.

## v0.1.3 — 2026-08-07

Erasing now erases on screen too. Marco reported that cutting a big selection
left the original behind and that deleting one looked partial; the entities were
in fact gone from the document, but most of their pixels stayed until a full
regen caught up seconds later.

### Fixed
- **Erase, cut and move now clear the screen completely.** The viewport removes
  edited geometry without a regen by zeroing the alpha of the entity's vertex
  runs, looked up in a handle → runs map. Two holes in that map meant the lookup
  silently found nothing and the geometry stayed drawn:
  - **Everything inside a block was unowned.** The drawing frontend expands an
    `INSERT` into *virtual* copies whose `handle` is `None`, so no vertex in any
    block could be attributed — and the only handle that could ever hide them is
    the `INSERT`'s, because that is what the selection and the pick index hold.
    Block content is now attributed to the outermost entity that has a handle.
  - **`exit_entity` cleared the drawing context instead of restoring it**, so
    whatever an enclosing entity drew *after* a nested child came out unowned as
    well (and untyped, which also mis-keyed its bucket for text culling).
  - **The thick-line batch never recorded owners at all** — `_pack_thick` was
    the one packer called without the map, so every entity with a lineweight
    above 0.25 mm was unhideable regardless of blocks.

  Measured by erasing every modelspace entity and counting vertices still drawn:
  `casa.dwg` left **75.9 %** of the drawing on screen, the roof-truss sheet
  26.7 %, the Yanaquihua structural sheet 13.2 %, `sedapar` 1.9 %. All four are
  now **0 %**. Scene build time is unchanged. A new invariant test asserts that
  every vertex of every batch is attributable, on a drawing that reaches all
  four batches — the old coverage test used a document with no blocks and no
  thick lines, which is why the hole survived.

### Changed
- **New application icon.** The pencil is gone: the scene is now a model-space
  viewport with the UCS icon (X red, Y green) and the **crosshair cursor** — pick
  box, centre dot and arms reaching the axes — filling the first quadrant. Those
  are the two things a CAD user recognises without reading a label; the pencil
  said "drawing app", the crosshair says "CAD".
  `resources/ingecad.svg` is the single source of truth and
  `scripts/gen_app_icons.py` (new) rasterizes the eight PNG sizes and the `.ico`
  from it, so the committed rasters are no longer produced by hand. Run it before
  `scripts/gen_doc_icons.py`, which composites `ingecad_256.png` as the badge on
  the .dwg/.dxf document icons.
- **Spanish UI is neutral, without voseo** — «Escribe un comando», «Arrastra una
  ventana», «Presiona Esc», «Elige una línea distinta». Six strings in
  `i18n/es.json`; the same correction already applied to the website.

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
