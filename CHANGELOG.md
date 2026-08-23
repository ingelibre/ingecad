# Changelog

## v0.4.2 — unreleased

Three stalls Marco felt while working on real plans, all of them measured to
a cause, plus the object groups audited against the reference and given the
tests they never had.

### Fixed — the drawing keeps up with the hand
- **Dragging a selection window no longer sticks.** The scene itself was
  never the problem: it costs a constant 2.7 ms a frame. What cost 18 ms was
  the overlay drawn on top of it — a Qt pen and brush set *per grip*, and
  thousands of highlight segments walked one at a time in Python, most of
  them off-screen. Both are now transformed in one pass, clipped to the
  window and drawn in a single call. A frame with 3000 objects selected:
  **20.6 ms → 6.7 ms**.
- **Grips follow AutoCAD's GRIPOBJLIMIT** (p. 2339): past 100 selected
  objects they are suppressed *entirely*, as the reference says, instead of
  being thinned to the first 200 entities — which on a cadastre meant 2448
  squares repainted every frame for a display nobody can use at that size.
  The limit is yours to move in **Options ▸ Selection** (0 = always show).
- **Releasing a big selection window: 95 ms → 31 ms.** Of the old 95, some
  91 were the properties panel and the properties toolbar recomputing over
  the whole selection — rebuilding four combo boxes, with an icon rendered
  per row, and walking the entire entity database to compute a flag the
  layer control does not even show. The lists now rebuild only when the
  drawing's tables actually change, and "do these objects share a value?"
  stops at the first difference instead of collecting them all.
- **Moving a dimension by its grip: 3.4 s to grab, 3.1 s to drop → 34 ms and
  100 ms.** Dropping a dimension grip demanded a full regen, which
  re-tessellates the whole drawing; but the overlay has been able to draw a
  dimension since v0.1.3, so the surgical path — hide the stale copy, draw
  the new one — is enough, exactly as it already was for MATCHPROP. And the
  magnet that snaps a dimension line onto a neighbouring one was querying
  every DIMENSION in the drawing on **every mouse move**.
- **"A veces se queda pegado"**, the one that came and went: every single
  edit queued a rebuild of the entire drawing 2.5 s later. It runs in a
  worker, but a pure-Python worker holds the GIL, so it landed as a
  multi-second freeze right when the user reached for the next grip. That
  merge exists only to bound the overlay's growth, so it now follows the
  same rule the drawing path always had: below the threshold, nothing is
  scheduled.
- **Drawing a dimension on a big plan: 163 ms → 25 ms**, from the same
  entity-database walk as above.

### Fixed — object groups (GROUP, p. 861)
- **Selectable now reaches the file.** The flag lived in a Python set on the
  document, so every "not selectable" group came back selectable after a
  save and reload. It belongs in the GROUP object (code 71), which is where
  AutoCAD keeps it and where a colleague's CAD will look for it.
- **The dialog stopped losing your place.** Every action ended by rebuilding
  the list, which left no row selected — so the *next* Add, Remove or
  Selectable click silently did nothing at all.

### Added — the rest of the Object Grouping dialog
- **Add and Remove** members (the reference's "Change Group", pp. 863–864),
  with exact undo. Removing every member keeps the group defined, and the
  objects stay in the drawing, both as documented.
- **Description** (64 characters, p. 863) and **Find Name**, which lists the
  groups an object belongs to.
- **`PICKSTYLE`** as a command and a switch in the dialog — the escape hatch
  the group machinery was missing: without it, once an object was grouped it
  could never be selected on its own again.
- **43 tests** covering groups and the responsiveness fixes, where there
  were none. Two of the three group bugs above were found by driving the
  dialog rather than reading it.

## v0.4.1 — 2026-08-23

The Block Editor, dimensions that appear the instant you place them, the
whole interface speaking Spanish again — commands included — and the first
outside contributor's two reports both answered with machinery.

### Added — the Block Editor (BEDIT / BSAVE / BCLOSE)
- **`BEDIT`** (alias `BE`) opens a block definition in its own environment,
  matched against the reference (pp. 215–273): only the block on screen,
  base point at the origin, a distinct background so you always know which
  room you are in, and the classic **Block Editor toolbar** with Save and
  Close spelled out. All three documented ways in: a name with the command
  (`BEDIT ?` lists), a selected insert — including the right-click menu's
  "Block Editor" — or the dialog, where a **new name creates a new block**.
- **Every insert updates on save**, because references point at the
  definition by name. Discard is an exact rollback to the last save point,
  through the same undo machinery as everything else; `BSAVE` moves that
  point, so save-then-discard keeps what was saved. `U` cannot cross the
  session's start, layout tabs wait until `BCLOSE`, and the INSERT picker
  hides any block that would nest the edited one into itself.
- **Selection cycling**: click the same spot again and the next overlapping
  object answers — the dimension under the text somebody typed over it.
  A cycled click swaps the selection ("the other one", not "both"), and
  Shift never cycles. What one click selects is unchanged by construction.
- **Commands in Spanish**, the way a Spanish AutoCAD spells them: `LINEA`,
  `CIRCULO`, `BORRA`, `DESPLAZA`, `RECORTA`, `ACOLINEAL` — 58 names, and
  English never stops working: `L`, `LINE` and `_LINE` all draw with any
  language active, as does AutoCAD's `_` global prefix. Localized prompt
  keywords too: with Spanish active, `Suprimir`, `D` and `_D` all delete a
  layout, read straight out of the translation's `[Suprimir(D)]`.
- **A language is now a folder** (`i18n/<code>/meta.json + ui.json`): adding
  one needs no Python and appears in the menu by existing. The old flat
  files still load. Czech is on its way from the first outside contributor.
- **Help ▸ Report a Problem...** opens the guided issue forms — the drawing
  attached is what makes a report fixable, and the forms say so. Spanish
  welcome.

### Fixed
- **A new dimension appeared after seconds** on a real plan (2.3–2.9 s on a
  5 406-entity survey, 10–16 s on a 10 847-entity one): the display rebuilt
  the whole drawing to show one entity, on the strength of a comment that
  had stopped being true. Now 40–300 ms — and `MATCHPROP` onto a dimension,
  which carried the same stale comment and read as "it did not select it",
  shows instantly too.
- **The Spanish interface offered words it then refused** (`[Suprimir]`
  accepted only `D`) — 17 prompts fixed, and a test now walks every
  language file so no translation can lose its English keys again.
- **274 strings reached a Spanish user in English**: everything v0.3/v0.4
  added went untranslated. Spanish is complete again (1 106 strings), and
  coverage is enforced for the maintained language, only reported for
  community ones.

### Faster
- Regenerating a drawing: **1.9×** on the heaviest real plan (10.5 s →
  5.4 s) — the tolerance walk, a dictionary per polyline vertex, and
  387 543 point-in-ring tests that a bounding box now answers.
- Layout tabs: **up to 2.5×** (4.7 s → 1.9 s on a ten-viewport sheet) —
  each viewport now skips the 82–99 % of the model it does not show,
  conservatively enough that the rendered sheet is pixel-identical.

### Infrastructure
- LibreDWG vendor at **0.14.8580 + the 17 upstream patches** from our PRs.
- CI runs the suite under a real X server (Xvfb): same code paths as a
  desktop, GL included — which is how an entire class of headless-only
  crashes left the project.
- Issue forms, PR template, code of conduct, branch protection, and five
  starter issues for anyone who wants to contribute.


## v0.4.0 — 2026-08-13

The right-click menu, seven commands that were missing behind it, a
settings window, and the sheet navigating at speed.

### Added — the shortcut menu, and what it needed
- **The canvas shortcut menu rebuilt from the reference itself.** 93 of the
  Command Reference's pages name the shortcut menu among their Access
  Methods; every one IngeCAD can honour is now there. With nothing
  selected: Clipboard, Undo, Redo, Pan, Zoom (Extents/Window/Previous),
  Quick Select, QuickCalc, Find, Properties and Options. With a selection:
  Erase, Move, Copy Selection, Scale, Rotate, Draw Order, Isolate, Group,
  Add Selected, Select Similar, Deselect All — plus the entries the
  reference gives a single object of a kind: `Edit` for text, `Polyline ▸
  Edit`, `Image ▸ Adjust / Transparency`, `Dimension Style`.
- **`ISOLATEOBJECTS` / `HIDEOBJECTS` / `UNISOLATEOBJECTS`** — object
  isolation, display-only as the reference insists ("temporarily"): nothing
  in the drawing changes, it never reaches the file, and a hidden object
  cannot be picked either.
- **`SELECTSIMILAR`** with its Select Similar Settings dialog and AutoCAD's
  default (layer plus block name).
- **`ADDSELECTED`**: the picked object's general properties become current
  and the command that draws its type starts.
- **`QSELECT`**: Apply to, Object type, Property, Operator, Value,
  Include/Exclude and Append — with the operators each property actually
  accepts, as p. 1586 specifies.
- **`GROUP`**: the Object Grouping dialog, names validated to the
  documented rule, and picking one member selecting the whole group
  (per-group Selectable, all of it off under PICKSTYLE 0). Groups live in
  the drawing's own dictionary, so one made here is a group in AutoCAD.
- **`FIND`**: find and replace across the drawing, a layout or the
  selection, with the results list, Zoom to and Select — undoable, and it
  reaches text, MTEXT, attributes and dimension overrides.
- **`QUICKCALC`**: input, history, number pad, scientific functions and
  unit conversion over the reference's four unit types. Expressions are
  evaluated by walking the parse tree and refusing anything that is not
  arithmetic.
- **`OPTIONS`** (`OP`): the settings window, under AutoCAD's own tab names
  — Files, Display, Drafting and User Preferences. Among them a real new
  setting: **Right-click Customization**, so the right button on an idle
  canvas can be the shortcut menu or Enter, the way many drafters set
  AutoCAD up.
- **Draw Order in one click** from Tools and from the shortcut menu, and
  **Properties shows the style of every styled object** — a dimension's
  Dim style (editable, re-rendering it), a text's or attribute's style, a
  leader's.

### Performance
- **Pan and zoom inside a floating viewport: 146 ms a tick to 5.2 ms.** The
  model is tessellated once and each tick is a matrix and a scissor
  rectangle instead of a rebuild of the whole sheet. Verified against the
  rebuild it replaces: 0 of 674 370 pixels differ.
- Measured and left alone: model-space navigation. A frame is 0.6 ms even
  on a drawing of 4.5 million vertices — the cost there is the 60 Hz screen
  refresh, now a setting (Options ▸ Display) for whoever prefers lower lag
  to no tearing.

### Fixed
- **Trimmed and extended pieces came back on layer 0.** A trimmed line is
  that line, shortened: pieces now keep layer, colour, linetype, linetype
  scale, lineweight and transparency — and their XDATA, which is somebody
  else's data hanging off that object. Twelve places across TRIM, EXTEND,
  FILLET and CHAMFER.
- **Ctrl+Z did nothing after a command was typed.** The undo was never
  broken; the key was being eaten by the command line, which claims it for
  its own text undo. In a CAD that key means the drawing, wherever the
  focus is.
- **The dimension style preview drew no dimensions at all** for any style
  with an AutoCAD arrowhead (`_ARCHTICK` — every architectural style), and
  no text for styles meant for drawings in metres. The sample sizes itself
  to the style now.
- **The crosshair jumped back to where a pan started** instead of staying
  under the pointer.
- Navigating one viewport blanked the others.

### Upstream (GNU LibreDWG)
- **`vendor/` re-based to 0.14.8580 plus the seventeen open pull requests**,
  each taken from the PR's own head — the previous vendor carried a stale
  draft that corrupted MTEXT in pre-r2007 drawings. Accents now survive in
  all sixteen cells of the matrix (eight places a string can live, two
  source versions); the old vendor had seven wrong.
- Write-path fuzz over 2000 drawings: for a modern source and the r2000
  target, which is what saving does, **1015 of 1015 round-trip unchanged**.

## v0.3.2 — 2026-08-13

A bug-fix release with one headline: **accents survive "Save as DWG"**.

### Fixed
- **Non-ASCII text was mangled on every save to DWG.** Measured on a drawing
  carrying `CAÑERÍA Ø m² Nº45°` in every place a string can live: layer,
  text-style and block **names**, `TEXT`, `ATTRIB`, dimension text and XDATA
  all came back corrupted (`CAÑERÍA` as `CAÃ‘ERÃA`, the layer `DESAGÜE` as
  `DESAGÃœE`); only `MTEXT` survived. Every Spanish, Portuguese or French
  drawing was affected, which made this a hole in the promise the whole
  project is built on — that a colleague's plan comes back sound.

  The cause is in GNU LibreDWG, reported upstream as
  [issue #1393](https://github.com/LibreDWG/libredwg/issues/1393) with
  byte-level evidence against ODA File Converter, which handles it correctly.
  IngeCAD now works around it on both sides: the intermediate DXF handed to
  the converter goes out as R2000 — the version the DWG will have anyway, so
  the downgrade cannot cost anything an r2000 DWG could carry — and `MTEXT`
  is pre-escaped to `\U+xxxx`, AutoCAD's own notation for a character the
  codepage cannot hold, which is pure ASCII and leaves nothing to
  mistranslate. Opening a DWG decodes those escapes again, so drawings that
  AutoCAD itself wrote that way now show the character instead of the raw
  code.
- **Old drawings saved as an empty DWG.** Four R12 files in the test bench
  produced a DWG with no entities at all; they now come back complete. Same
  change, LibreDWG's pre-R13 writer gap
  ([#1386](https://github.com/LibreDWG/libredwg/issues/1386)) sidestepped.
- **Saving could crash outright** when the converter printed a warning naming
  an accented layer: its log was being decoded as strict UTF-8 when it is
  written in the drawing's own codepage.

### Upstream (GNU LibreDWG)
- **XDATA negative values were corrupted.** Every negative value in groups
  1070/1071 — the data other applications attach to entities — came back as
  its unsigned complement (`-6700` as `58836`). Measured across 200 real
  drawings: **2595 corrupted values in 146 of them**. Patch sent as
  [PR #1392](https://github.com/LibreDWG/libredwg/pull/1392); it also fixes a
  format string that read 64 bits of argument for every 32-bit caller.
  Found by widening `tools/dwg_fuzz.py` to carry XDATA, lineweights and
  tilted extrusions.
- Of the 17 patches sent since v0.3.0, **9 are now merged upstream**.

## v0.3.1 — 2026-08-12

A second dogfooding day against BricsCAD V26, on a real plan (`casa bueno`).
This one is mostly **bugs Marco hit while drawing** — the kind only real use
finds — plus the quick wins from the strategic review of BricsCAD's menus.

### Added
- **The Standard toolbar** (New/Open/Save/Plot/Undo/Redo/Cut/Copy/Paste/
  Zoom/Pan), sharing one row with Modify. **Clean Screen (Ctrl+0)** clears
  every panel and toolbar but the command window, like AutoCAD's.
- **Raster images**: `IMAGEATTACH` (PNG/JPEG/BMP/GIF/TIFF, referenced like
  AutoCAD — the file is linked, not embedded), corner grips that resize
  about the opposite corner, `IMAGEADJUST` (brightness/contrast/fade) and
  `TRANSPARENCY` with a degree from 0 to 90 %, in the Properties panel too.
- **`PDFATTACH`**: a PDF page rasterized at 150 DPI and placed as an image —
  the tracing workflow, without leaving the drawing.
- **`TABLE`**: a grid of lines and centred texts (plain geometry, so it
  round-trips everywhere and edits with the normal commands). It is the
  groundwork for the coordinate chart of the coming topography plugin.
- **`SPLINE`**: fit points with live preview, Close and Undo, and its icon
  in the Draw toolbar.
- **Grips on every selectable type**: SPLINE (fit or control points),
  ELLIPSE (centre + four axis ends), IMAGE, TEXT, MTEXT, INSERT, XLINE/RAY,
  SOLID, HATCH — and **DIMENSION grips like AutoCAD's**: drag an extension
  origin to re-measure, the dimension line to relocate, the text grip to
  move the label. Dragging a dimension grip near another dimension snaps to
  its line, with BricsCAD's green alignment square.
- **`DRAWORDER`** (send to back / bring to front, written as AutoCAD's
  SORTENTSTABLE) and the layer tools **`LAYISO` / `LAYOFF` / `LAYON` /
  `LAYUNISO`**.
- **The Select Color palette** (the full 255-index ACI grid) wherever a
  colour is chosen, and **ByBlock** beside ByLayer in the colour dropdown.
- **Closing with unsaved changes asks** — Save / Discard / Cancel.
- **The Layer control reflects the selection**: select an object and the
  Properties bar shows its layer; a mixed selection shows blank. And
  choosing a layer there now **resets the colour to ByLayer** in the same
  gesture, so a file that arrives with `$CECOLOR` = ByBlock (they do)
  stops ignoring layer colours.

### Fixed — the dogfooding harvest
- **Entities on heavyweight layers vanished for seconds after being drawn
  or moved.** The incremental display's overlay skipped the thick-quad
  batch entirely, so anything above 0.25 mm (`casa bueno` has five such
  layers, columns at 0.8 mm) was invisible until the deferred regen folded
  it in. Overlay, drag ghost and stamped moves now all carry it.
- **`baño` drew as `bano`**: the tessellator treated every ring but the
  largest as a hole, so the tilde — a detached glyph part — was punched
  out. Ring nesting is even-odd now, per draw call, which also fixed
  layout text drawing with filled counters (the `o` solid inside).
- **`DIMLINEAR` / `DIMALIGNED` collapsed to a 0 measurement on vertical
  edges**, and dimension text was invisible in drawings in metres or
  centimetres (the renderer read the scale from the style, not the header).
- **Grip edits on a colleague's dimension changed its look**: the line
  turned white, the label flipped from aligned to horizontal, or landed on
  the wrong side of the line. All three preserved now.
- **`MATCHPROP` matched dimensions, text height, and colour properly**: it
  now copies the *effective* height and colour (AutoCAD's inline `\H` and
  `\C` codes, not the attribute residue), and copies "ByLayer" itself
  rather than skipping absent properties.
- **`REVCLOUD` arcs bulged inward** — a saw blade, not a cloud.
- **An attached image never appeared** until some later regen, and
  **inserted PDF pages came out black** (the render leaves no-ink pixels
  transparent; they are composited over white now).
- **Entities created in the session lagged ~4 s** when grip-moved or
  restyled, **pan stuck to the cursor** after releasing over the MTEXT
  editor, and **pan inside a floating viewport trailed a regen behind**.
- A malformed entity that failed mid-render used to make every entity
  drawn after it un-hideable (an unbalanced owner stack in the renderer).

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
