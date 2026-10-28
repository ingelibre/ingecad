# Changelog

## v0.6.8.2 — 2026-10-21

- **Plot opens again in a layout whose page setup has a scale outside
  the list** (1:37, a custom ratio from another program...). The dialog
  failed while it was being built and nothing appeared; it now opens on
  Custom with that page setup's ratio.

## v0.6.8.1 — 2026-10-20

- **A drawing opened from the file manager while IngeCAD runs becomes a
  tab of its window**, instead of a second IngeCAD with a window of its
  own. Several drawings opened together arrive as a tab each; IngeCAD
  started from the menu with nothing to open still gets its own window.

## v0.6.8 — 2026-10-20

What testers found while recording tutorials, fixed first; data that
Save as DWG lost, kept; and two tools a drafter reaches for every
day: PEDIT Join and the UCS.

### Two tools of the daily flow
- **PEDIT Join** (#89): lines, arcs and open polylines that touch become
  one polyline, closed when the contour closes, so AREA and HATCH take
  it. It keeps the properties of the object picked first.
- **UCS** (#91): a moved and turned origin, three points, Named
  (Restore/Save/Delete/?), Object, Previous, View, World and Z, plus
  Tools ▸ New UCS. Typed coordinates, the coordinate readout, snap,
  ORTHO, POLAR, tracking, the grid and the cursor follow it, and so do
  RECTANG, POLYGON, XLINE, ARRAY, INSERT, TEXT, MTEXT, the hatch angle,
  DIMLINEAR, DIMORDINATE, ID and DIST. It travels in the DXF and the DWG.
  A plan UCS only; sheets and the block editor stay in world coordinates.

### What testers ran into
- **A dimension too narrow for its text sets the text beside it**, as
  ISO 129 does (#102).
- **The status-bar toggles come back as you left them** (#103).
- **Annotative text styles scale dimension text** with the annotation
  scale (#85); **associative dimensions follow grip and Properties
  edits** (#90).
- **A hatch's scale and angle set in Properties redraw its pattern** (#86).
- **The dots of DASHDOT, CENTER and PHANTOM are drawn**, on screen and
  on paper (#87).
- **An attribute definition can be edited, and BLOCK keeps its
  attributes** (#88).
- **Zoom Extents frames what was just drawn** (#96).
- **A click, window or crossing no longer takes objects on hidden
  layers** (#97).
- **Construction lines look infinite** and stay out of the extents (#98).
- **The Layers panel's state icons** are painted, not font glyphs (#100).

### Data kept
- **Justified text no longer jumps to 0,0 after Save as DWG** (#95; fixed
  in LibreDWG, upstream #1463).
- **Save as DWG no longer warns about every recent plan** (LibreDWG,
  upstream #1464 and #1465).

### Screen and paper
- **A large text is no longer hidden** with its layer's small ones.
- **Polylines with a lineweight close their corners.**
- **Plotted TrueType text and solid hatches** get no outline.
- **PLOT in a layout starts from that layout's page setup**, in its units.
- **Typed DRAWORDER** and its undo redraw at once.

### For plugin authors
- A plugin's toolbar takes separators; a plugin tags XDATA under its own
  APPID (`docs/plugins.md`).

## v0.6.7 — 2026-10-11

The colleague's drawing, edited as its author would: every dimension of a
1576-plan corpus redrawn in place and compared with what the author's CAD
drew, a whole staircase plan drawn again from scratch, and what testers
ran into. Plus drawing tabs and associative dimensions.

### Several drawings, one window
- **Drawing tabs** (#71): several drawings open in one window, each with
  its own view; a drawing opens where its author left it.
- **Copy in one IngeCAD window and paste in another** (#75).

### Dimensions as their author drew them
- **Associative dimensions** (DIMASSOC 2): a dimension follows the object
  it measures, and the tie survives opening and saving DWG.
- **Editing a colleague's dimension keeps it as it was drawn**: its text
  height (a fixed-height text style no longer grows 305 times), its
  number (aligned dimensions read 0, zeros and decimals changed, a
  negative DIMLFAC read negative, halves rounded down, near-vertical
  dimensions at UTM coordinates rounded to whole units), hand-placed text
  where the author put it, suppressed arrows suppressed, angular
  dimensions on the right side and with the right points (also fixed in
  LibreDWG, upstream #1438), arc lengths without a stray "( ".
  99.5 % of the corpus's linear dimensions now redraw identical.
- **ROTATE, SCALE and MIRROR redraw a dimension** instead of turning its
  picture: readable text, the new length, copies where they belong.
- **Dragging a dimension's text carries its line** (DIMTMOVE 0).
- **DIMANGULAR, complete**: live, on polylines, with extension
  lines and degrees/minutes/seconds.
- The **dimension style editor** writes only what you changed (OK no
  longer turned 0.0025 m text into 0.01), takes metric sizes, and shows
  every tab.

### Commands with their usual options
- **MOVE, COPY, STRETCH**: Displacement, and Enter takes the first point
  as the displacement; **COPY** Exit and Undo; **ROTATE, SCALE** Copy;
  **UNDO** takes a count; **OOPS**; **TRIM, EXTEND** Fence, Crossing, Undo,
  Quick and Standard modes, arcs extended along their circle; **FILLET**
  and **CHAMFER** on polylines with all their options; **MULTIPLE**;
  typed answers at "Select objects" (ALL, Last, Previous, Window…).
- **ARRAY** asks only the spacings it needs; **OFFSET** starts at Through;
  **TEXT** ends on an empty line; **EXPLODE** shows a block's attribute
  definitions.
- **DIMASSOC, CELTSCALE, DIMSCALE, LWEIGHT, LWDISPLAY, ZOOMFACTOR, SETVAR,
  PROPERTIES, REDRAW, TEXTEDIT** and their usual short aliases (R, CH,
  PR, ED…), which used to run other commands.
- **Objects on a locked layer can no longer be erased or moved.**
- **Undo gives back the whole object**: dimension blocks, polyline
  vertices, block attributes, hatch patterns.
- **TRIM, EXTEND, BREAK, OFFSET and JOIN keep a contour's height and
  width**, and PEDIT Reverse its widths.
- **Linetypes**: a Linetype Manager, -LINETYPE, the ISO linetypes in
  metric drawings, CELTSCALE and PSLTSCALE.

### Drawings in metres, on screen and on paper
- **Dashes and dots show** at the linetype scale a drawing in metres needs.
- **A Model-tab plot carries the layers' lineweights**; Plot gets a
  custom scale ("1000 mm = 25 units"), "Plot object lineweights" and a
  preview.
- **TEXT, MTEXT and MLEADER start at a paper size** in the drawing's
  units, not 2.5 m.
- **Polyline widths survive Save as DWG and opening a DWG** (LibreDWG,
  upstream #1437): 962 polylines in 44 of 197 corpus plans opened thin.

### Smaller
- Object snaps reach inside block inserts; ZOOM Window with snaps (#80);
  BOUNDARY keeps curves (#83); Intersection finds crossing curves (#82);
  the Properties panel takes a decimal comma; the rest of what testers
  reported.

## v0.6.6 — 2026-10-09

The colleague's drawing, without scares: what stopped the people already
working with IngeCAD -- Rafael, Arthur, Riccardo -- fixed before anything
new is opened. And the first IngeCAD for **Windows**.

### Windows
- **IngeCAD for Windows** (#28): an installer (Start menu, "Open with" for
  `.dwg` and `.dxf`, a clean uninstaller) and a portable zip, with the same
  patched LibreDWG as on Linux. Not signed yet: Windows SmartScreen warns
  the first time -- *More info* ▸ *Run anyway*.

### Fixes that stopped work
- **External references survive Save as DWG** (#66): the attached drawing
  is still there after saving and reopening, with no "-2" suffix, and a
  file chosen through the Flatpak portal keeps its real path. (The
  LibreDWG half went upstream as LibreDWG #1431.)
- **INSERT ▸ Browse…** inserts another drawing as a block (#70).
- **Copy in one drawing, paste in another** brings its blocks, text and
  dimension styles and layers along (#75).
- **A model-space plot comes out on white paper** with dark lines, not on
  the dark canvas (#62).
- **A layer or dimension style emptied by ERASE can be deleted** (#64).
- **Page Setup** shows its margins on their own sides of a picture of the
  sheet (#61).
- **Save as DWG no longer freezes the window for a second**: the
  "Saving…" window keeps moving, keyboard and mouse are held until it
  ends, and opening a drawing got faster too (worst pause 0.6 → 0.35 s).
- **A polyline being drawn snaps to its own points**: close
  it on its start point by Endpoint, or snap the midpoint of a segment
  already drawn.

### Drawing to the standard
- **Plot model space at 1:1, 1:2, 1:5, 2:1, 5:1…** in the drawing's own
  unit (#68).
- **Radius and diameter dimensions** with the text outside put the arrows
  outside, pointing at the centre; a diameter with its text inside spans
  the whole circle (#67).
- **Annotative scaling the way drafters use it** (#73): Properties ▸
  *Annotative* for existing texts and dimensions, **Add / Delete Current
  Scale** (also the + on the status bar), and the viewport follows.
- **Point style** (#69): DDPTYPE, PDMODE and PDSIZE, sizes relative to the
  screen kept at each regeneration, and the Node snap on the point itself.

### Everyday editing
- **Grips obey ORTHO, POLAR and Perpendicular** from where they were
  grabbed (#60); Perpendicular lights with the cursor over the object.
- **Several texts at once** in Properties: style and justification (#57,
  #77).
- **OFFSET** trims the loops a large offset makes and simplifies the shape
  (#58).
- **TEXT takes its height and angle from the mouse** as well as typed, with
  a rubber band from the start point, and is typed inside a shaded box that
  reads on the dark model and on the white sheet.
- **A selection filter by object type** (FILTER on the status bar): select
  only dimensions, only text…
- IngeCAD **reopens at the size and place it was closed at** (#72).

### Layouts, references, interface
- The **External References** palette lists images and PDFs too, with
  *Attach DWG / Image / PDF*.
- A new drawing comes with **Layout1 and its viewport**; **PAGESETUP** works
  on the Model tab; PLOT remembers its last setup; WBLOCK proposes DWG.
- **A live language switch translates the whole window** (#74), not only
  the menus. French joins as a community language pack.
- **Help ▸ About IngeCAD** names the people whose work is in it.

### Under the hood
- A closed window is destroyed instead of hidden for the rest of the
  session (it leaked memory; the test suite went from an hour to a minute).
- The open, save and regeneration workers each have one owner, and the
  garbage collector never runs on a worker thread.

## v0.6.5 — 2026-09-28

The commands a colleague's drawing asks for: external references,
block attributes, leaders, the dimension family, cleanup, plot style tables
and a multi-page PUBLISH -- each with its standard prompts, in their usual order.
Viewports became fast to enter and to switch between, and the model
regenerates on several cores.

### CAD commands
- **External references** (#33). A drawing that references others now shows
  them where they belong, found the standard way (the saved
  path, then next to the drawing), each file read once. **XATTACH** (XA)
  attaches a DWG or DXF, **-XREF** lists, detaches, reloads, unloads,
  re-paths and overlays, and the new **Xrefs** tab of the sidebar does the
  same with buttons. Object snaps reach the referenced geometry, and a click
  selects the whole reference. Saving keeps every reference untouched.
  Not yet: Bind, nested references beyond one level.
- **Block attributes** (#35), which title blocks are made of. **ATTDEF**
  (dialog) and **-ATTDEF**; **INSERT** asks each value with its prompt and
  default; a **double-click** on the block opens the Enhanced Attribute
  Editor; **-ATTEDIT** one at a time or globally, **ATTSYNC**, **BATTMAN**,
  **ATTDISP**. Untouched attributes round-trip byte for byte.
- **Leaders** (#34): **MLEADER** (MLD) with its Options, **QLEADER** (LE)
  and **LEADER**, the text typed or written in the in-place editor.
- **Dimensions** (#39): **DIM**, the unified command that picks the type by
  what you point at; **QDIM** series (continuous, staggered, baseline,
  ordinate, radius, diameter); **DIMBREAK**, **DIMJOGGED** (JOG) and
  **DIMSPACE**.
- **Cleanup** (#37): **PURGE** (dialog) and **-PURGE** with its three
  prompts -- never layer 0, the current layer or a block still in use --
  **OVERKILL** for duplicate and overlapping lines and arcs, and **WBLOCK**
  (W) to write a block or a selection to its own drawing.
- **LENGTHEN** (LEN), **ALIGN** (AL), **BOUNDARY** (BO), **DONUT** (DO) and
  **SCALETEXT** (#38).
- **Annotative objects can be created** (#43, what Rafael asked for): an
  *Annotative* box in the text and dimension styles, text and dimensions
  born at the current annotation scale, the scale of the view on the status
  bar (the Model tab's CANNOSCALE, or the active viewport's), ANNOAUTOSCALE,
  ANNOALLVISIBLE and **OBJECTSCALE**.
- **Dynamic blocks** show their current state and keep every
  parameter on save (#36; changing the state from its grips comes later).

### Plotting
- **Plot style tables** (#41): PLOT and Page Setup offer the `.ctb` tables
  (the default, monochrome, Grayscale, Screening 50%, and any a colleague sends,
  dropped in `~/.config/IngeCAD/PlotStyles`); a layout plots with its own
  table unless you choose another.
- **PUBLISH** (File ▸ Publish): the layouts you tick, in one PDF, each page
  the size of its sheet at 1:1.
- **Plot area Window** (#52): *Window <* asks the two corners on the drawing
  with a rectangle following the cursor, and the dialog
  comes back with everything as you left it.
- **File ▸ Export ▸ DXF** and **DXFOUT** (#51): a DXF copy for Blender or
  QGIS that leaves the open file as it was.

### Scripts
- **APPLOAD** (AP) runs a Python file over IngeCAD's commands -- everything
  it draws is one undo step -- and **SCRIPT** (SCR) runs a `.scr`
  (#44). `docs/plugins.md` has worked examples.

### Viewports
- **An active viewport navigates; it does not edit.** Double-click into a
  viewport and the wheel, pan, ZOOM (nXP, Extents, Window) and VPLOCK work
  on its view; drawing and editing happen in the Model tab, and a command
  typed inside a viewport says so. Entering used to index the whole model
  for editing through the paper -- 2 s of work and a freeze on the first
  pan on a real plan.
- **Switching between sheets no longer rebuilds the model for each one**
  (2.3 s saved per switch on Planos Constructivos), and going back to a
  sheet already seen is instant.

### Interface
- **A "Loading <name>…" window** while a big drawing opens (#50): the file,
  the phase (converting the DWG, reading, regenerating), the time, and
  Cancel. It also shows during a long regeneration and Save as DWG.
- **The status bar is yours to arrange**: right-click it, or press the ≡
  button at its end, and tick what it shows -- as in other CAD programs.
  Out of the box it shows the classic SNAP, GRID, ORTHO, POLAR and OSNAP;
  tracking, dynamic input and lineweight are one tick away, and F11/F12
  work either way. The layout tabs no longer shrink to "...".

- **The right sidebar folds away with one click** (#47), as in IngeTrazo: a
  slim handle sits on the line where the sidebar is resized, half-way down
  the drawing; click it and the drawing takes the whole width, click it
  again and the sidebar comes back at the width it had. **View ▸ Sidebar
  (Ctrl+F5)** is the same toggle, the next session opens the way this one
  closed, and LA, PROPERTIES or STYLE unfold it on their own. It replaces
  the small `›` button and the thin strip it left behind.
- **The Layers panel starts without the Description column**: almost nobody
  fills it in, and in the sidebar it took the room the values need.
  Right-click the column headers to bring it back; the choice is kept.
- **A new PAN icon** (#32): the familiar open hand in outline, like the rest
  of the toolbar, instead of a box with four lines. The cursor while
  panning is the same hand -- open to hover, a fist while dragging -- with
  a light outline over a dark fill, so it reads on the dark model, the
  white sheet and a satellite image alike.
- **LAYFRZ, LAYTHW, LAYLCK, LAYULK** (#40), with their standard prompts and in
  Format ▸ Layer Tools: freeze the layer of each object you pick (Undo
  takes back the last one; the current layer is refused), thaw every
  layer in one undo step, and lock or unlock a layer by picking one of
  its objects -- LAYULK reaches objects on the locked layer itself.

### Speed
- **Regenerating the model uses several cores** (#31, Linux). A full regen
  is ezdxf's drawing frontend, pure Python, and ran on one core: the plan
  is now drawn by forked workers, each taking runs of entities through the
  very same drawing path, and stitched back in order. Plaza Yanque (10 000
  objects): 4.2 s → 1.2 s, pixels identical within the serial noise. A
  worker that dies or hangs costs a serial regen, never the drawing;
  `INGECAD_SERIAL_REGEN=1` turns it off. Windows and macOS keep the
  serial path. Sheets too: every worker draws the whole sheet, in each
  viewport only its share of the model. Planos Constructivos' sheets
  3.8 → 1.7 s and 2.7 → 1.3 s; Casa Peregrinos' 1.5 → 0.45 s.
- **A block placed many times is drawn once** (#29). ezdxf exploded a block
  again for every reference; now, per regen of the model, each block is
  recorded once and every reference replays it rotated and moved. Casa
  Peregrinos' model 1.6 s → 1.0 s, Planos Constructivos' 5.4 s → 4.4 s.
  It also fixes filled dots (a donut wider than its diameter)
  that came out with a notch.

### Georeferencing
- **Any projected coordinate system, through PROJ** (#27). GEOREF's new
  *Coordsys* option takes an EPSG code — `27700` for the British National
  Grid — and every conversion (LATLON, KML, the DEM, the satellite image)
  goes through PROJ with its grids: OSTN15 is fetched on first use and
  cached, and offline the next most accurate path answers. UTM on WGS84 or
  PSAD56 keeps IngeCAD's own maths, which PROJ matches to a nanodegree.
  pyproj (≈34 MB) now ships in every package; `--check` proves it converts.

### Fixes
- **Panning inside a viewport (MSPACE) no longer lags.** On the sheets
  colleagues send, the live navigation never engaged: a clipping-boundary
  handle that points at nothing (most viewports after a DWG conversion),
  a plain rectangular boundary, or a view twist of 720° (a full turn)
  each sent the whole sheet to a full regen on every mouse move -- 60
  moves, 60 regens, and the picture trailing by seconds. Those cases now
  go live like a plain viewport, the model for the live view is built in
  the background from the double-click (it used to freeze the first pan
  tick, 5.8 s on a real sheet), each viewport draws only the model it
  shows, and the GPU buffers survive between gestures. A drag now costs
  the same as panning the paper. The model for the live view is now
  prepared as soon as the sheet tab is shown, so the double-click finds
  it ready.
- **Editing inside a viewport no longer freezes the next pan.** After an
  edit the model for the live view is stale, and the next pan tick rebuilt
  it on the interface thread (2.4 s frozen on a real sheet). The rebuild
  now starts in the background with the edit itself, and the display
  catches up when it lands.
- **A twisted viewport navigates live too.** One viewport with a view
  twist kept the whole sheet on the slow path -- every pan tick inside
  any viewport of Planos Constructivos' A-01 (one at 60°) re-baked the
  sheet. The live matrix now turns as the bake does.
- **Zooming and panning inside a viewport no longer re-bakes the sheet
  after every burst.** Each pause used to rebuild the whole sheet (a full
  regen per pause, twelve in a minute of zooming on a real sheet) while
  the live view already showed the right picture; the sheet is now
  rebuilt once, when you leave the viewport.
- **ZOOM Extents, ZOOM nXP and ZOOM Window inside a viewport show the new
  view at once** (0.3 s on a real sheet instead of 5.7 s): the fitted view
  goes up through the live matrix, like a pan, while the sheet re-bakes
  behind it.
- **Inside a viewport, the pointer is an arrow over the rest of the
  sheet**: the crosshair stays clipped to the active
  viewport, and the ordinary arrow shows where a double-click on the paper
  would take you back to paper space. It used to vanish out there.
- **Lineweights inside a viewport were drawn at the paper's scale while
  navigating live**: a 0.5 mm wall in a 1:50 viewport became a black bar
  50 times too wide (Marco's video). They are now the same width live as
  on the baked sheet.
- **A viewport with a view target no longer draws empty.** The culling
  that skips the model a viewport does not show centred its rectangle on
  the raw view centre, which is relative to the view target: with a UTM
  target the rectangle sat near the origin and the whole model was
  skipped -- Plaza Yanque's Layout1 showed its main viewport blank, and
  ZOOM Extents inside it "did nothing". Fixed; and ZOOM Extents in a
  twisted viewport now fits the turned extents, so the model no longer
  spills out of the frame.
- **A sheet no longer loses part of a block now and then.** The viewport
  culling cached bounding boxes by object identity, and a block's content
  is drawn from temporary copies whose identity Python reuses: a later
  copy inherited a stranger's box and was culled. Measured: 8 sheet
  regens in 50 drew a window block incomplete, in v0.6.4 too.
- **Ctrl+S on a big plan no longer freezes the window.** Save as DWG ran on
  the interface thread: on Plaza Yanque (10 000 objects) the window froze
  for 10 s. The save now runs in the background while the window keeps
  drawing (keyboard and mouse wait), and its check reads the
  file as a stream instead of loading the plan twice: 14 s → 7.7 s, and the
  longest pause during the save is 0.02 s. Found by the new release bench.
- **The grid no longer flickers when zooming or panning.** The frame that
  rebuilt the grid (the first after F7, a wheel notch or a pan across a
  cell) drew it, and the red/green axes, with no shader program bound, so
  both vanished until the next repaint -- "activo la grid y no se ve, en
  cuanto paso el ratón se reescala" (Rafael's review).

## v0.6.4 — 2026-09-27

Save as DWG that holds on real drawings, the drafting commands made to
follow the standard CAD flow prompt by prompt, and the multi-second freezes a
performance audit found before this release. LibreDWG is now IngeCAD's
only DWG engine, and the optional DWG 2018 converter entry of Save As is gone.

### Save as DWG
- **213 real drawings saved and reopened: 116 → 185 open cleanly in ODA
  and IngeCAD**; the save itself failing went 55 → 7, and no drawing loses
  entities any more. Fixed in LibreDWG (vendored, re-based on 0.14.8597):
  Proxy objects from other programs keep their graphics and their class, a proxy newer than
  the target format is written as the target's, a large proxy graphic no
  longer corrupts every object after it, FIELD lists keep their fields,
  accents survive in pre-2007 dictionary keys, 3-point angular dimensions
  import. In IngeCAD: a leader with a single vertex is kept (ezdxf dropped
  it on every save, DXF too), FIELD objects and binary blobs no longer stop
  the save.

### Drawing as drafters expect
- **FILLET** with the standard flow: `Current settings: Mode = TRIM, Radius =`,
  `[Undo/Polyline/Radius/Trim/Multiple]`, Shift on the second pick for a
  sharp corner, Trim / No trim shared with CHAMFER (TRIMMODE); fillets
  between lines, arcs and circles (circles are not trimmed), and two
  parallel lines joined by a semicircle.
- **One-shot object snaps**: type END, MID, CEN, TAN, PER, INT, NEA, QUA,
  NOD, INS or NONE at a point prompt (answered with "of"/"to"), or pick one
  from the Shift + right-click menu, now in the standard order; the **FROM**
  and **M2P** point modifiers.
- **Deferred tangent**: a line tangent to two circles.
- **Extension and Parallel** object snaps, with tracking.
- **Draw ▸ Circle** is the classic submenu, with **Tan, Tan, Tan** — CIRCLE
  3P with a tangent on each point, typed or from the menu.
- **MIRROR keeps text readable** (MIRRTEXT = 0, the default; new
  drawings start there, and MIRRTEXT is a system variable).
- **CLAYER** sets the current layer by name.
- **LAYOUT ▸ Copy** and the tab menu's **Move or Copy...**.
- **REINIT** shows the Re-initialization dialog.
- TRIM and EXTEND find tangency points; mirrored arcs are no longer
  "ghosts" that could not be selected; a window selection no longer takes
  an arc outside it.

### Spanish and classrooms
- A **Spanish alias file (.pgp) works** as it is (DE, *DESPLAZA), read in
  ANSI or UTF-8; *Tools ▸ Customize ▸ Edit Program Parameters (.pgp)*
  opens it. The Spanish command names were checked against the standard Spanish names: DESCOMP, ACOANGULAR, ACOESTIL, GUARDAR, GUARDARCOMO
  corrected; GUARDARR, REINICIA, EDITPOL, CALCURAPIDA and more added.
- **Classroom and office defaults**: one folder, `/etc/ingecad/`, with a
  `defaults.ini` and an alias file (`.pgp`) for every account on a machine; each
  user's own settings still win. The README has a classroom example.

### Performance
Measured end to end against 0.6.3 on real plans before this release —
opening, zoom and pan, drawing, window selection, colour changes,
Ctrl+C/X/V, ERASE, COPY, each undone, and Save as DWG:
- Undo of an edit over a whole 10 000-object sheet froze the window 7–8 s;
  now under one second, the redraw finishing in the background.
- The first mouse move on a big plan right after opening no longer stalls.
- MOVE, COPY, ROTATE, SCALE, MIRROR, paste, array and stretch over a
  selection with a proxy object or an OLE object no longer fail half-way
  (and leave no undo): those objects stay put and the command says so.
- Everything else measured the same as 0.6.3.

### Packaging
- 0.6.3 did not open on Arch or Debian testing: the AppImage and tarball
  now leave libstdc++ and fontconfig to the system.

## v0.6.3 — 2026-09-22

What two testers found using 0.6.2 — a second video from Rafael and a
surveyor in Bolivia on WhatsApp — plus what Marco found while checking the
fixes. Two of the four user reports turned out to be bugs shipped in
0.6.2 that touched everyone (importing points died; dimensions could not
take a layer's colour), one was a missing feature (hatching what is drawn
with lines), and one report is still open for lack of a reproducible case
(object snap while drawing polylines). The Topography plugin now has a
user manual at ingecad.org/manual-topografia.

### Changed
- **The dimension being placed is previewed as the dimension it will be.**
  While DIMLINEAR or DIMALIGNED waits for the line's location, the canvas
  drew a schematic with the measurement centred on the line, unlike the
  finished dimension (ISO-25 puts the text above). The preview is now the
  rendered dimension itself, built from the very command the click runs,
  taken back at once so the drawing is untouched.

### Fixed
- **File > New showed the previous drawing's last dimensions** (their lines,
  without arrows or text) on the empty canvas: the entities queued for the
  on-screen overlay since the last full regeneration survived the switch of
  document and were drawn against the new one. The queue is now emptied with
  everything else that belongs to the drawing being left.
- **HATCH finds boundaries drawn with lines and arcs, islands included**
  (a user: "al dibujar el HATCH no detecta las islas"). Pick-internal-point
  only knew closed objects -- a closed polyline, a circle -- so a room
  drawn as four lines, or an island drawn as four lines, answered "No
  closed boundary found" where a hatch should fill. The region is now traced the
  way BPOLY does: every curve in view is cut where it crosses another,
  dead ends fall away, the smallest face around the point is the
  boundary and whatever lies inside it (loops of lines, circles, text) is
  an island. The boundary set is what the canvas shows, the classic
  "current viewport"; on a colleague's 10 000-entity plan a pick answers
  in 0.2-0.6 s.
- **PIMPORT died before importing anything** (a user: "he intentado
  importar puntos, pero no lo logro; la exportación sí funciona"). The
  options dialog set its preview's text format with a plain `0`, which
  the PySide6 the packages ship (6.11) rejects; the dialog never opened
  and the command ended with a traceback. PEXPORT has no dialog, which is
  why it worked. The suite had only exercised the tool headless; it now
  opens the dialog and runs PIMPORT through the window.
- **An exported points file came back with east and north swapped.** The
  column sniffer took the larger coordinate for the northing, which on a
  local grid (N 1037, E 2003) reads PEXPORT's own P,N,E,Z as P,E,N,Z.
  Size decides only when a coordinate is a digit longer than the other
  (a UTM northing always is); same-length coordinates keep N before E.
- **A linear dimension picked right-to-left drew mirrored**: the text
  under the line, the dimension line overshooting the extension lines,
  the arrowheads outside pointing in (a tester's report on 0.6.2). ezdxf
  takes the line's direction from the pick order where it should follow
  the dimension's angle; the renderer now receives the origins in
  reading order -- text from the bottom or the right of the sheet -- so
  DIMLINEAR and DIMALIGNED draw the same whichever corner is clicked
  first. The DIMENSION itself keeps the user's order (DIMCONTINUE and
  DIMBASELINE chain from it).
- **Dimensions moved to a coloured layer stayed white** (the same
  report: a red layer "cotas", the dimensions on it, no change). A
  dimension's block is a block reference in all but name, and a CAD
  resolves its ByBlock strokes and layer-0 content against the
  dimension; the canvas and the plot now do the same, ISO-25 colours its
  lines, arrows and text ByBlock as the ISO template does (so a colour set on the
  dimension itself shows too), and the block content follows the
  dimension onto its new layer in the file, as DWG files write it
  (measured: 3991 of 3991 block entities in three colleagues' plans). A
  style whose colours were set ByLayer used to re-render with its lines
  left on layer 0 -- red text and arrows, white lines -- for the same
  reason.

### Added
- **Czech interface**, a community translation by Michal Josef Špaček
  (PR #2): 817 of the interface's strings, under Tools ▸ Language. The
  prompt options keep their English keys (`Uzavřít(C)`), so what you type
  is what every CAD user types; the strings that arrived after the translation
  show in English until someone fills them in.
- **Store page and desktop integration**: the Flatpak's page in GNOME
  Software shows seven screenshots (it showed none), the running window is
  tied to its launcher inside the sandbox (dock icon, the store's Open
  button), and an AppImage offers on first run to add itself — icon,
  launcher, .dwg/.dxf association — to the applications menu.

## v0.6.2 — 2026-09-16

What a second tester found drawing to the norm (ISO / UNE): ten findings,
all ten addressed, and three bugs underneath them that nobody had reported
(viewports with a view target projected half a million units off, polar
tracking that rounded every point, the live viewport picture drawn white
on white).

### Fixed
- **Loading an ISO linetype loaded something else.** `ACAD_ISO02W100`
  came in as an invisible line and `ACAD_ISO04W100` (long-dash dot) as a
  dotted one: the loader handed ezdxf the bare dashes where it expects
  the pattern length in front, so the first dash was swallowed. All 20
  library linetypes a new drawing lacks were affected — the whole ISO
  family, BORDER and HIDDEN; DASHED and CENTER survived only because the
  template preloads them.
- **Diameter dimensions off the norm.** The two arrowheads came out one
  inside pointing out and one outside pointing in, and the text landed
  across the circle from where you clicked. Now, as ISO 129-1 and
  the ISO-25 style have it: the dimension line runs across the circle
  with both arrowheads inside, tips on the circle pointing outward, and
  the text outside on an extension of the line where you put it; a
  circle too small for the arrowheads gets them outside pointing in.
  Radius dimensions get the same rule (arrowhead inside when it fits).

- **Panning inside a viewport blanked it.** The gesture's live picture was
  dropped when it settled while the sheet's baked copy of the model was
  still hidden, and nothing asked for the regen that brings it back; and
  the live picture itself resolved ACI 7 against the model canvas — white
  on white paper, so a plan drawn in "color 7" vanished the moment a pan
  began. The picture now stays up until the fresh sheet lands, and the
  model is tessellated with the sheet's colours. A sheet whose viewports
  cannot go live (clipped or twisted) no longer pays a 5-second model
  build on the first tick. A double-click on the bare paper leaves the
  viewport instead of reaching a model text through the projection.
- **Viewports with a view target were projected half a million units
  off.** The view centre (group 12/22) is a display-frame offset from the
  view target (17/27), not a WCS point; read raw, eight of the thirty
  viewports of a colleague's plan — the ones with a UTM target — put the
  model "under the window" nowhere near it, so nothing could be picked or
  edited through them. The projection is now ezdxf's own matrix, verified
  on all thirty.

- **The pointer flickered while panning.** The app changed the system
  cursor exactly twice per drag (measured); what flickered was the
  system cursor itself — a closed hand — over a GL surface repainting
  sixty times a second, an artefact some driver/compositor pairs show
  (NVIDIA under XWayland is the classic one). The pan hands and the
  zoom-window cross are now painted into the frame, like the crosshair
  always was; the canvas never hands the OS a cursor.
- **A new layer looked non-plottable.** After New, the highlighted row was
  whatever row index had been current before the list re-sorted — often
  Defpoints, which does not plot, and whose crossed-out printer read as
  the new layer's. The new layer is now the selected row with its name
  open for typing, as a layer manager should. (Every
  new layer did plot; the file was never wrong.)
- **The grid jumped when zooming.** The 1-2-5 ladder re-flowed the whole
  lattice at each step (going from 1 to 2 drops the major line at 15).
  The grid is now a nested adaptive grid: GRIDUNIT times a power
  of GRIDMAJOR, so zooming adds or drops lines and never moves one, with
  a band around each threshold so a wheel notch at the boundary does not
  flip it back and forth. GRIDUNIT, SNAPUNIT and GRIDMAJOR are read from
  and saved into the drawing (its *Active VPORT) — a
  colleague's plan brings its own grid.
- **Polar tracking rounded every point.** With POLAR on the cursor was
  forced to the nearest 45°, so a 30° line could not be drawn; the 45°
  could not be changed. It now locks only near an alignment path, as
  classic polar tracking does, and shows the path with its angle.

### Added
- **Origin as an object snap.** No CAD has it and a tester insisted it is
  elementary: tick *Origin* among the running object snaps and the (0, 0)
  of the current space snaps like a node, with a marker of its own
  (a circle with a +). Off by default; it lives in your settings, never in
  a drawing's $OSMODE.
- **`0` and Enter at the first point is the origin**: a
  direct distance or a relative `@` entered before a command has a point
  of its own is measured from the last point entered (LASTPOINT), which a
  new drawing starts at (0, 0). `5` puts the point five units from it
  toward the cursor.
- **Drafting Settings** (Tools ▸ Drafting Settings…, DSETTINGS / DS, and
  Settings… on the right-click of the status-bar toggles), the classic
  dialog with its Snap and Grid, Polar Tracking and Object Snap tabs:
  the increment angle (90, 45, 30, 22.5, 18, 15, 10, 5 or typed), the
  additional angles, absolute or relative-to-last-segment measurement,
  object snap tracking along all polar angles, the grid and snap
  spacings, the major-line frequency and the adaptive/subdivision
  behaviour. Typed as POLARANG, POLARADDANG, POLARMODE, GRIDUNIT,
  SNAPUNIT and GRIDMAJOR too. The snap spacing follows the grid on
  screen unless the drawing fixes one.
- **Object snap from the sheet through its viewports**, and dimensions
  that read the model: on a layout the cursor over a viewport now snaps
  to the model geometry it shows (endpoints, midpoints, centres…), and a
  dimension whose points all came through the same viewport carries
  DIMLFAC = 1/scale, so it reads 100 for a 100-unit wall drawn 20 mm wide
  on the sheet — the way paper-space dimensions of model
  geometry read. Undo/redo keep it; any CAD honours it.
- **CENTERMARK and CENTERLINE** (menu Dimension), the norm's centre marks:
  chain-line (`CENTER2`) axes running past the circle with a central
  cross and a gap, and the centreline between two lines, as modern CAD
  draws them — but as plain lines, so the plan opens anywhere. Ruled by
  the typed variables CENTEREXE (millimetres of sheet past the circle,
  3.5), CENTERLTYPE, CENTERCROSSSIZE (`0.1x` of the diameter),
  CENTERCROSSGAP (`0.05x`), CENTERLAYER (`.` = current) and
  CENTERMARKEXE. DIMCENTER keeps drawing what DIMCEN says.

## v0.6.1 — 2026-09-09

The first report from outside: a machine with an NVIDIA card on Wayland
where IngeCAD — and IngeTrazo beside it — did not open at all.

### Fixed
- **Would not open at all with an NVIDIA driver on Wayland.** That EGL
  cannot serve the OpenGL 3.3 context the canvas asks for (`Failed to
  create context: 3009` — `EGL_BAD_MATCH`), and since that is the
  *default* surface format it took Qt's own window painting down with it:
  not a broken canvas, an app that does not start. The same driver serves
  the same request through GLX under X11 without a complaint, so IngeCAD
  now checks at startup and either asks for a leaner format (line
  smoothing off) or restarts itself under X11. The Flatpak asks for
  `--socket=x11` so that restart has somewhere to go.
- **Library warnings on AppImage startup.** The host's GIO modules clash
  with the glib inside the bundle and printed two `undefined symbol`
  lines before the app existed. The AppImage no longer loads them.

## v0.6.0 — 2026-09-06

The release the plan called v0.5 and v0.6 together: the first two
discipline plugins, on the plugin contract that makes them possible, plus
the classic CAD keyboard and a crash in the core that the work uncovered.

### Added — plugins: the core stays a lean 2D CAD, the disciplines plug in
A plugin is a folder that, switched on, adds one menu, its commands and
tools, an optional toolbar and options page and its own translations —
and, switched off, removes exactly that (the suite holds every bundled
plugin to "no trace left"). **Tools ▸ Plugins…** (`PLUGINS`) manages them;
the contract is written in `docs/plugins.md` for anyone who wants to write
one; `ingecad --check` lists what it found. A plugin's toolbar is off by
default — the menu is what a plugin adds, the toolbar is yours to switch
on. Everything a plugin draws is plain DXF (POINT, TEXT, LINE, polylines,
3DFACE, HATCH) that any CAD opens, and it survives Save as DWG.

### Added — Topography (the v0.5 promise), menu *Topography*
- **Points**: import a total station's CSV/TXT (`P,N,E,Z,D` and its
  dialects, column order guessed and correctable), export, a traverse
  typed by bearing and distance, renumber, find. NOD snap lands on the
  imported coordinate exactly.
- **Polygons**: bearings and distances annotated, the **construction
  chart** (vertex, side, distance, bearing/azimuth, interior angle, E, N,
  area, perimeter — the table everybody used to build by hand), sums of
  areas, subdivision by area (parallel to a side, about a point, by two
  points), the UTM grid, the **descriptive report** (memoria descriptiva)
  in the wording a Peruvian filing expects, and areas by lot.
- **Surface**: an own Delaunay TIN with breaklines, boundary and maximum
  edge (20 000 points in 0.4 s, Euler count exact), edited (flip, delete,
  insert, clip) and checked; **contours** at their elevation with labels
  and optional smoothing; slope zones with a legend.
- **Profiles and earthworks**: the longitudinal profile of an axis with
  station and elevation bands, a grade line drawn on it, cross sections
  with a template, cut and fill by prismoidal or end-area method, table
  and CSV.
- **Platforms**: a pad at an elevation and slope, side slopes to daylight
  (benches included), the daylight line, hachures, the design surface and
  the exact volume between two surfaces (the cancellation that made a
  13 m³ pad read 1 918 m³ in UTM is handled).

### Added — Terrain (the v0.6 promise), menu *Terrain*
- **GEOREF / LATLON**: the drawing's UTM zone, hemisphere and datum (WGS84,
  or PSAD56 with the EPSG:1208 shift for Peru's older plans), kept in the
  drawing itself and read on open; latitude and longitude of any point,
  typed coordinates in decimal or DMS. The maths is our own, checked
  against PROJ to 0.15 mm; nothing new is installed.
- **DEMPOINTS / DEMPROFILE**: a grid of ground elevations, or an axis'
  profile, from a global 30 m DEM (AWS Terrain Tiles, no key, cached) —
  a terrain with no survey yet, straight into TIN and CONTOUR, and every
  time the command says it is for preliminary design only.
- **SATIMAGE**: the satellite image under the plan from a licensed source
  (Esri World Imagery, Sentinel-2 cloudless, OpenStreetMap, or your own
  XYZ), resampled into the drawing's UTM grid so it lands exactly, saved
  beside the drawing, clipped to the polygon if asked, with the
  attribution the licence requires written on the plan.
- **KMLIN / KMLOUT / KMLOVERLAY**: Google Earth both ways — placemarks in
  as points, polylines and polygons with names and colours; the selection
  out as a KMZ (a lot boundary comes back within 0.1 mm); the plan
  rendered as a ground overlay draped on the terrain.
- The Flatpak now shares the network for these; nothing else uses it.

### Added — the classic CAD keyboard, key by key
SNAP (F9 / Ctrl+B: the cursor jumps by the grid on screen), **object snap
tracking** (F11: pause on a snap point to acquire it, ride the alignment
paths from it, lock where two meet), **dynamic input** (F12: the prompt
and the live coordinates beside the cursor; a bare `x,y` after a first
point is relative, `#x,y` absolute), Shift held as a temporary ortho,
Ctrl+G/L/U/F for grid/ortho/polar/osnap (Ctrl+F is no longer Find), Ctrl+1 Properties, Ctrl+9 the command
line, Ctrl+A select all, Ctrl+W selection cycling, Ctrl+I coordinates,
Ctrl+J/M repeat, Ctrl+[ and Ctrl+\ cancel, Ctrl+PgUp/PgDn layout tabs,
Ctrl+Tab drawing windows, Ctrl+Shift+C copy with base point,
Ctrl+Shift+V paste as block, F1 help. The table is in the README.

### Added — an optional second DWG converter
An external converter, found automatically when installed, added DWG
r2018 export. (Removed in 0.6.4: LibreDWG is IngeCAD's only DWG engine.)

### Fixed
- **A crash in the core, older than the plugins**: Python collected cyclic
  garbage on a worker thread (the index warmer, the regen worker, the
  autosave…) and the garbage held Qt objects made on the GUI thread —
  one segfault in five runs of the suite, reproducible on demand. Every
  worker now runs with the collector paused, so collections only ever
  happen on the GUI thread.
- With two plugins on, **Ctrl+C on the canvas copied nothing**: every menu
  rebuild added the clipboard actions again and Qt fires none of an
  ambiguous shortcut. Also Delete, Ctrl+X and Ctrl+V.
- The layer control, the Layers tab and the Properties tab now follow a
  command that creates or removes a layer, and follow an undo at once
  instead of on the next mouse move; Options' Apply button applies plugin
  pages, as OK did.
- One question, one place: the dimension magnet inside a 1:5 viewport
  reached 5× less than it should; the Block Editor's overlay flattened
  arcs 2 000× coarser than the scene; Properties showed an untranslated
  colour name beside a translated one. Each answer now lives once.

### Changed
- The menu order puts plugin menus between Modify and Tools; Find keeps
  its Edit entry without a key.

## v0.4.7 — 2026-08-29

### Added — edit the model through a viewport (MSPACE)
v0.4.6 made the sheet editable and left the third state of a layout tab
written down but unbuilt: the model, reached **through** a floating
viewport. It exists now. MSPACE — or a double-click inside a viewport —
makes the modelspace current, and drawing, editing, snapping, picking and
grips reach it through that viewport's projection while the canvas keeps
showing the sheet.

The projection lives in one place (scale, view centre and twist), and
The classic rules come with it: a click only counts inside the active
viewport, one in another viewport makes that one current (mid-command
too), one on the bare paper does nothing; the crosshair is clipped to the
viewport and the coordinate readout switches to model units; ZOOM Window
and the wheel both zoom the viewport's view, ZOOM Extents fits the model
in it, Ctrl+R cycles; and the sheet's own commands (MVIEW) still belong to
paper space and say so.

Verified on a real plan (13 viewports at 1:10): a click where the viewport
draws a line selects that line, MOVE by 20 × 10 mm of paper moves the
model by exactly 2 × 1, and undo returns it. First pick 1.9 s (it builds
the model's index), every one after it 12 ms.

### Added — automatic save and drawing recovery
"What happens if I am drawing and it closes on me?" Now: SAVETIME (minutes,
10 by default, 0 turns it off), an `.sv$` copy, and the Drawing Recovery
Manager at the next start or in File ▸ Drawing Utilities — the classic model,
with its Options ▸ Open and Save page.

The part that is ours is the part that had to be measured: writing a real
plan takes 2.2 s, so the copy is written on a worker thread and only starts
after the drawing has been still for 15 seconds. The app can wait exactly
once — if an edit lands while the file is being written — and that is the
case the pause rule removes.

Tested by crashing it: a plan of 88 897 entities, a line drawn and not
saved, SIGKILL. The restart offered the drawing back with its name, age
and object count, and opening it returned every object plus the line that
was never saved — as unsaved work, so a reflex Ctrl+S cannot overwrite the
good file.

### Added — hatches select and edit the classic way
A hatch is picked by **clicking on it** (its real shape, islands excluded),
not only by hitting its boundary, and it is the last candidate for a click
so a line drawn over it still wins. HATCHEDIT (alias HE, Modify ▸ Object ▸
Hatch, or a double-click) changes pattern, scale, angle and colour while
keeping the hatch's boundaries, handle and island style.

The pattern palette is drawn from the definitions themselves — each line
family with its offset and dashes — so ANSI31, ANSI37, BRICK and HONEY look
like themselves, in a grid with categories (ANSI / ISO / Other) instead of
a ragged list. Ten of the 172 predefined patterns were unreachable because
their names carry a lowercase letter and the lookup upper-cased them:
their hatches were created without a definition.

### Added — linetypes with their pattern drawn
The Select Linetype dialog lists what the drawing has loaded as Linetype /
Appearance / Description, with the dashes **drawn**, and a Load button for
a library of 39 standard definitions (25 classic families + 14 ACAD_ISO).
The definitions were read out of 120 real plans, keeping what several agree
on; ezdxf's own table disagrees with them for 13 of 16 names and that was
reported upstream.

### Changed — the Layers panel answers at once
Turning a layer off used to rebuild the whole drawing: 7.7 s on a plan of
88 897 entities, where other CAD programs are instant. The vertices are already on the
GPU, so visibility is now a change of alpha (114-383 ms, no rebuild) and
colour / linetype / lineweight re-tessellate **that layer only** (209-686
ms on a layer of 139 692 vertices). A layer that also lives inside a block
still rebuilds, because its geometry belongs to the INSERT.

The panel's columns were narrower than their own content, so Color,
Linetype and Lineweight were cut at every width of the sidebar; they size
themselves to what they hold now, a width you drag is kept, and the header
has the classic right-click menu to turn columns off. The right sidebar
itself runs to the bottom of the window: the command line used to own that
corner and cut it short.

### Fixed
- Four of five layouts of a real plan opened with an empty sheet — a
  LibreDWG read bug (viewport status), worked around here and sent
  upstream as LibreDWG#1406.
- The Select Color swatches are 1.5× bigger, as asked.

## v0.4.6 — 2026-08-27

### Added — the layout sheet is editable
A colleague sent Marco an A1 layout template. It opened perfectly and
nothing on it could be touched: no move, no erase, no trim, no scale, no
text edit — the title block could not even be **selected**. That was a
deliberate limitation, and the reference settles it in one line:
*"Commands operate in either model space or paper space"* (MSPACE,
p. 1213). There are no commands that stop working on a layout tab; only
the current space changes.

So now a layout tab edits its own sheet, through the very code paths the
model uses:

- **Select anything on the sheet** — click, window, crossing, Shift to
  remove, click again to cycle between overlapping objects.
- **Draw and edit in paper millimetres**: LINE, MOVE, COPY, ERASE, TRIM,
  EXTEND, SCALE, ROTATE, FILLET, dimensions… with object snap to the title
  block's own geometry.
- **Edit a title block's text** by double-clicking it, exactly as a classic CAD
  does (MTEDIT's access method *is* the double click) — and the object's
  own action now wins over entering a viewport, as the reference specifies.
- **A viewport is an object again**: picked by its frame (never by clicking
  inside it, which is the classic rule), caught by window/crossing, moved and
  scaled like anything else. MOVE carries its picture along; SCALE ×0.5
  draws it at half size — which is what refitting an A1 sheet to A3 needs.

The three states of a layout are now the reference's own: the sheet
(PSPACE) is fully editable; inside a viewport (MSPACE) navigation works and
editing the model through its projection is still to come — it says so, and
a click there no longer selects anything, instead of picking paper
coordinates against the model's index.

### Fixed — three faults the same change uncovered
- **A line drawn on the sheet was white on white.** The instant-feedback
  overlay never resolved colours against the canvas it lands on, so ACI 7
  came out white on the white paper — invisible until the next full regen.
- **Undo followed you to another tab.** Erasing an object on a sheet and
  pressing Ctrl+Z from the Model tab resurrected it **in the modelspace**:
  a command asked "which space?" twice and, with the space now mutable, the
  two answers stopped agreeing. Every command asks once and remembers.
- **The background cache warmer could adopt the wrong space**, because a
  tab switch deliberately does not bump the document revision.

## v0.4.5 — 2026-08-24

### Added — the model background is yours (Drawing Window Colors)
Colleagues who draw on white or cream can now have it: **Options ▸ Display
▸ Colors...** opens the *Drawing Window Colors* dialog — context
list (2D model space, Sheet / layout, Block editor), interface elements
(Uniform background, Crosshairs), the colour drop-down with *Select
Color...*, a live preview, and the four restore buttons including
**Restore classic colors** (the black model space of classic CAD).

The choice is more than a clear colour, and this is where being identical
matters: **ACI-7 entities flip** (white over dark, black over light — the
plan stays readable on any canvas), **text background masks fill with the
canvas colour**, the grid switches to light-canvas grays, and the
automatic crosshair inverts — all resolved at tessellation time, so
applying a background change triggers the regen it needs. The sheet desk
and the Block Editor canvas are configurable from the same dialog.

### Fixed — resizing an inserted image took seconds to take effect
Marco: drag a corner grip of a raster reference and wait. Measured: the
drop forced a full re-tessellation of the drawing — **9.4 s on a real
plan** — while a move or resize never changes the texture at all, only the
four corners of its quad. Rewriting those 6 vertices is the whole job:

- **the pixels follow the mouse live** now (0.04 ms per move, was 325 ms
  with a scanned sheet), and the drop costs ~80 ms instead of seconds;
- **MOVE of an image is instant** too (2 ms, no regen), instead of the
  image vanishing until the deferred rebuild;
- **undo/redo reposition the quad surgically** as well, exact against the
  full rebuild to the last float (0.000000 measured error).

The second half of the stall was subtler: drawing an IMAGE through the
render frontend **decodes its file** (a 36 MB PIL decode per mouse move on
a scanned sheet), so raster entities now stay out of the vector overlay
entirely — the live quad is the feedback. The corner math is shared with
the full build through one function, so the surgical path can never drift
from what the next regen draws.

### Fixed — Save as DWG stacked every paragraph onto its first line
Marco, an hour into v0.4.4: original.dwg looked right, the copy saved from
IngeCAD drew every two-line label as two lines superimposed on one. The text
and its line break survived; the round trip corrupted
**`line_spacing_factor` 1.0 → 0.0** (plus flow direction and spacing style
1 → 0), and an interline of zero stacks the paragraph on itself.

The mechanism: DXF says an absent group means its default, so ezdxf omits
groups equal to their default — and LibreDWG's DXF importer stores a missing
group as **zero** instead of applying the default. The same family as its
MINSERT bug (upstream #1385); a one-entity reproducer is ready for the next
Track L run.

Two defences, verified independently and together:
- **The intermediate DXF now writes every optional group explicitly**,
  materializing the spacing defaults on MTEXT that never had them set. On
  Marco's plan this also stopped two LEADER direction fields from
  corrupting — field mismatches against the original fell from 1084 to 765,
  and the remaining ones are fields LibreDWG does not write at all.
- **Files already saved with the broken writer are repaired on open**: 0 is
  not a valid spacing factor (the range is 0.25–4.0), so the repair can
  never touch a real value. His guardado.dwg renders within 13 pixels of
  the original, of 19 867 with ink.

## v0.4.4 — 2026-08-24

Marco opened a fence plan next to another CAD and reported three things. All
three were real, and none was what it looked like.

### Fixed — every leader label was a blank white box
The model's 302 labels ("CERCO CON ALAMBRE DE PÚAS", "MALLA DE ALAMBRE…")
are MULTILEADERs, and ezdxf draws a MULTILEADER only from its **proxy
graphic** — the picture the saving program baked into the file. That picture
hard-codes the text's background mask as a HATCH in the *saving* machine's
window colour — white — and the text in colours white swallows. IngeCAD now
renders the real content through ezdxf's native leader engine: the text, its
leader lines and the arrow, with the mask correctly left unfilled. The proxy
picture stays as the fallback for leaders the engine cannot digest.

### Fixed — the title block's text was erased by its own mask
The sheet's WIPEOUT (layer "0", filled in paper white) painted **over** the
labels of layer "-Textos": batching by (layer, colour) re-orders what the
file interleaves, and "0" sorts after "-Textos". Text now draws after every
fill of its draw-order group — a label is never meant to sit under a mask.
An explicit DRAWORDER "bring to front" still wins over text, as asked.

The same mechanism hid one layer deeper, and the sheet exposed it: a masked
label's own background quad and its glyphs land in sibling buckets keyed by
colour, and alphabetical order painted paper-white masks **after** black
glyphs — every masked label on a sheet erased its own text. The model tab
survived by pure luck: its canvas colour happens to sort first. Text masks
now carry a kind of their own and pack between the ordinary fills and the
glyphs, so the order is right by construction, in both spaces, whatever the
colours.

### Fixed — switching Model/Layout tabs took seconds, every time
Each tab switch launched a full re-tessellation of an unchanged drawing.
The window now keeps the built scene per tab and re-adopts it when you come
back: on the fence plan, **~1 s per switch became 5 ms / 1 ms**. Two things
made it honest: the tab switch itself no longer bumps the document revision
(it dirties the file — $TILEMODE must be saved — but changes no drawable
content), and the scene built while *opening* the file seeds the cache, so
the very first switch away and back already benefits. Any ordinary regen
request still empties the cache, because display settings such as VIEWRES
change the tessellation without touching the revision.

## v0.4.3 — 2026-08-24

### Fixed — File ▸ Open put up an error before showing the chooser
Marco, an hour after installing the Flatpak: opening a drawing answered
**"No se pudo encontrar «/app/ingecad»"**, and only after dismissing it did
the file chooser appear, in the home folder.

Every dialog in the app passed `""` as its starting directory, and Qt
resolves that against the process's working directory. From a terminal that
is harmless. In the Flatpak the launcher worked in `/app/ingecad` — a path
that exists **inside** the sandbox, while the file chooser is drawn
**outside** it by the desktop portal, which quite correctly reported that no
such directory exists. The same trap sat in every save dialog, where a bare
`plano.pdf` is just as relative as an empty string.

Both halves are fixed, and the fix is worth more than the bug:
- **Dialogs now open where you were last**, then in the folder of the drawing
  you have open, then Documents, then home — which is
  what the app should have done from the start. All seven dialogs (open,
  save as, template, PDF, image, PDF underlay, startup) go through one
  helper, and a test fails if a new one bypasses it.
- **The Flatpak launcher no longer works inside `/app`**, so nothing that
  resolves a relative path can leak a sandbox-only location to the host
  again.

## v0.4.2 — 2026-08-23

Three stalls Marco felt while working on real plans, all of them measured to
a cause; the graphics-quality complaint underneath them answered with
antialiasing and `VIEWRES`; a crosshair that is finally yours; and the object
groups audited against the reference and given the tests they never had.
IngeCAD also ships as a **Flatpak** from now on, out of a signed repository
of its own — one click to install, and later versions arrive by themselves.

### Added — IngeCAD installs like an application now
- **A Flatpak, from its own signed repo** at
  [downloads.ingecad.org/flatpak/ingecad.flatpakref](https://downloads.ingecad.org/flatpak/ingecad.flatpakref):
  one click opens it in the software centre, and every later version arrives
  through `flatpak update` without anyone visiting a download page. This is
  the install the target user gets — the civil engineer who never opens a
  terminal. Deliberately not Flathub yet: self-distribution, the road
  IngePresupuestos already walks. The bundle compiles LibreDWG from the
  pristine release plus this project's patches, exactly as the AppImage does,
  and asks the sandbox for no network at all, because IngeCAD needs none.
- **771 → 345 MB installed, 194 → 72 MB to download.** PySide6 ships
  QtWebEngine and its family, which IngeCAD never imports. The manifest trims
  by *blocklist*, not by allowlist, on purpose: a library nobody recognised
  stays in, so a future Qt upgrade cannot leave the app blank. Verified by
  importing the seven Qt modules the app actually uses from inside the
  sandbox, and by opening a real drawing there.

### Fixed — the drawing keeps up with the hand
- **Dragging a selection window no longer sticks.** The scene itself was
  never the problem: it costs a constant 2.7 ms a frame. What cost 18 ms was
  the overlay drawn on top of it — a Qt pen and brush set *per grip*, and
  thousands of highlight segments walked one at a time in Python, most of
  them off-screen. Both are now transformed in one pass, clipped to the
  window and drawn in a single call. A frame with 3000 objects selected:
  **20.6 ms → 6.7 ms**.
- **Grips follow GRIPOBJLIMIT**: past 100 selected
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
- **MATCHPROP: 2.76 s → 37 ms per click, from the second click on.**
  MATCHPROP keeps painting destinations until you press Enter, so the click
  *after* the first is the ordinary case — and it was the slow one. Two
  conditions that had to agree did not: the display code patched the pick
  index and the snap engine for any command carrying its list of targets,
  while the invalidation above it only knew a list of classes. It threw both
  caches away, the patch that followed was a no-op by design, and the next
  pick rebuilt the whole index from scratch. One predicate now answers for
  both, so they cannot drift apart again.

### Added — Options ▸ Display ▸ Display resolution
Marco, after the responsiveness work: the lines look a little worse than
they did, is there a graphics-quality setting? Measured first: rendering the
same view twice from the **same** build differs by more pixels (1.72%) than
old-vs-new does (1.09%), so nothing had regressed — that spread is process
noise. But the complaint underneath was real and long-standing:
- **Nothing was ever antialiased.** Measured on a real sheet, blended edge
  pixels were 0.1% of the ink; every slanted line and every letter was a
  staircase. **Line smoothing** is now on by default at 4× — edge pixels go
  to 31%, and the frame from 1.6 ms to 2.3 ms. Off / 4× / 8× in the dialog.
  This is multisampling in the widget's own framebuffer, which is where the
  project's Wayland gotcha says it belongs — verified under a native Wayland
  session, not just XCB.
- **A 40 cm circle was drawn with eight segments** — a visible octagon when
  you zoom in, which is exactly what VIEWRES exists to prevent. **`VIEWRES`** now exists, as a command and as "Arc and circle
  smoothness" in the dialog, with the standard scale and its default of 1000.
  Raising it to 8000 makes the circle round; measured on two real plans that
  costs +0.6% vertices and no measurable regen time, because a civil drawing
  is overwhelmingly straight lines.

### Added — the cursor is yours now
Under their standard names, since that is where the muscle memory looks:
- **Crosshair size** (`CURSORSIZE`, Options ▸ Display) — 1 to 100 % of the
  screen. IngeCAD keeps drawing it full-screen by default, because that is
  what it has always done; the usual default of 5 is one number away.
- **Crosshair colour** — any colour, or *Automatic*, which is the behaviour
  there has always been: light over the dark model, dark over a white sheet.
- **Pickbox size** (`PICKBOX`, Options ▸ Selection) — and this one is more
  than a preference. The square you see and the aperture that actually picks
  were two separate constants that happened to read 8; since one was a full
  width and the other a half-size, **the box on screen was half the size of
  what it caught**. One number drives both now, and the default changes
  nothing.

Both variables are typable at the prompt, like every other system variable:
`CURSORSIZE 30`, `PICKBOX 12`, or bare to see the current value.

### Fixed — every display setting was being read from the wrong place
`_configure_surface_format()` has to run before `QApplication` exists, and it
reads `QSettings` — but the application and organization names were set
*after* it, so it read an empty config under "Unknown Organization" and
ignored whatever was there. **The vsync toggle had therefore never done
anything since it shipped.** The names are static setters for exactly this
case and now come first.

### Added — leaders finally have grips
- **A LEADER now shows a square on every vertex**, so its
  direction can be changed by dragging instead of only being selected.
  Marco found the gap on a real sheet: "esa línea con el texto PEDESTAL VER
  DETALLE... en IngeCAD sólo se selecciona". **MULTILEADER** got the same
  treatment — it appears in 5 of 60 of his drawings, so the gap was waiting
  there too. The annotation deliberately stays put when the leader moves:
  the association runs text → leader, not the other way round.

### Fixed — three grip edits that survived their own undo
Giving leaders grips exposed something worse, so instead of fixing the one
type every grip-editable type was swept at once: move a grip, fingerprint
the geometry, undo, demand it comes back. Three failed, silently:
- **LEADER**, **SPLINE** and **HATCH** kept the new shape through Ctrl+Z.
  Undo restores DXF *attributes*, and none of those three keep their
  geometry in one — a moved hatch simply stayed moved. LWPOLYLINE and MTEXT
  already had their own lines there for exactly this reason; now the rule is
  a test that walks every type, so the next one to gain grips gets caught.

### Fixed — object groups (GROUP, p. 861)
- **Selectable now reaches the file.** The flag lived in a Python set on the
  document, so every "not selectable" group came back selectable after a
  save and reload. It belongs in the GROUP object (code 71), which is where
  DWG files keep it and where a colleague's CAD will look for it.
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
- **Commands in Spanish**, with their usual Spanish names: `LINEA`,
  `CIRCULO`, `BORRA`, `DESPLAZA`, `RECORTA`, `ACOLINEAL` — 58 names, and
  English never stops working: `L`, `LINE` and `_LINE` all draw with any
  language active, as does the `_` global prefix. Localized prompt
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
- **`SELECTSIMILAR`** with its Select Similar Settings dialog and the usual
  default (layer plus block name).
- **`ADDSELECTED`**: the picked object's general properties become current
  and the command that draws its type starts.
- **`QSELECT`**: Apply to, Object type, Property, Operator, Value,
  Include/Exclude and Append — with the operators each property actually
  accepts, as p. 1586 specifies.
- **`GROUP`**: the Object Grouping dialog, names validated to the
  documented rule, and picking one member selecting the whole group
  (per-group Selectable, all of it off under PICKSTYLE 0). Groups live in
  the drawing's own dictionary, so one made here is a group in any CAD that reads the DWG.
- **`FIND`**: find and replace across the drawing, a layout or the
  selection, with the results list, Zoom to and Select — undoable, and it
  reaches text, MTEXT, attributes and dimension overrides.
- **`QUICKCALC`**: input, history, number pad, scientific functions and
  unit conversion over the reference's four unit types. Expressions are
  evaluated by walking the parse tree and refusing anything that is not
  arithmetic.
- **`OPTIONS`** (`OP`): the settings window, under the familiar tab names
  — Files, Display, Drafting and User Preferences. Among them a real new
  setting: **Right-click Customization**, so the right button on an idle
  canvas can be the shortcut menu or Enter, the way many drafters set up their CAD.
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
- **The dimension style preview drew no dimensions at all** for any style with a standard arrowhead (`_ARCHTICK` — every architectural style), and
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
  is pre-escaped to `\U+xxxx`, the standard DXF notation for a character the
  codepage cannot hold, which is pure ASCII and leaves nothing to
  mistranslate. Opening a DWG decodes those escapes again, so drawings that
  other CAD programs wrote that way now show the character instead of the raw
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

A second dogfooding day against another CAD program, on a real plan (`casa bueno`).
This one is mostly **bugs Marco hit while drawing** — the kind only real use
finds — plus the quick wins from a review of classic CAD menus.

### Added
- **The Standard toolbar** (New/Open/Save/Plot/Undo/Redo/Cut/Copy/Paste/
  Zoom/Pan), sharing one row with Modify. **Clean Screen (Ctrl+0)** clears
  every panel and toolbar but the command window.
- **Raster images**: `IMAGEATTACH` (PNG/JPEG/BMP/GIF/TIFF, referenced like
  a reference — the file is linked, not embedded), corner grips that resize
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
  SOLID, HATCH — and **DIMENSION grips**: drag an extension
  origin to re-measure, the dimension line to relocate, the text grip to
  move the label. Dragging a dimension grip near another dimension snaps to
  its line, with a green alignment square.
- **`DRAWORDER`** (send to back / bring to front, written as the standard
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
  now copies the *effective* height and colour (the inline `\H` and
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

A day of dogfooding against other CAD programs, command by command:
Marco drew in IngeCAD with another CAD open beside it and every divergence
became a fix or a feature. The headline is the MTEXT in-place editor,
built from the documented in-place text editor behaviour
of classic CAD.

### Added — the MTEXT in-place editor
- **Edit on the canvas**, at the text's real size and position, drawing
  visible behind: Enter is a paragraph break, Ctrl+Enter / OK / clicking
  outside commits, Esc asks before discarding. Double-click an MTEXT to
  edit it; TEXT keeps its single-line in-place editing.
- **The Text Formatting toolbar**: style, font, height, bold, italic,
  underline, overline, colour, justification (all nine positions) — each
  written as the standard MTEXT inline codes (`\f`, `\H`, `\L`, `\O`, `\C`),
  so the file reads identically in any CAD.
- **The ruler**: first-line and hanging indent sliders, tab stops with the
  L/C/R tab-type button, the width arrow (drag to resize, double-click to
  fit), all stored as `\px` paragraph codes.
- **Line spacing** (1.0x/1.5x/2.0x/2.5x/More…/Clear) and **bullets and
  numbered/lettered lists**: Enter continues the list, Enter on an empty
  item ends it, `1.` or `-` plus Tab starts one — plain text plus indents,
  exactly the standard construction.
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

### Added — editing, to the standard prompt trees
- **STRETCH** (crossing selection semantics), **BREAK** (first/second
  point, `@` for break-at-point), **JOIN**, **CHAMFER** (distances,
  angle, polyline, Undo), **ARRAY** (rectangular/polar), **MATCHPROP**
  with its Settings list, **PEDIT** (open/close, join, width, and vertex
  editing).
- **OFFSET grown to the full tree**: distance by mouse (two picks),
  Through, Erase, Layer — and it offsets **polylines as one entity**,
  arcs included.
- **ROTATE and SCALE preview live**: the selection turns/scales under the
  cursor around the base point, with Reference and Copy options.
- Object snaps work **on curves** (circles, arcs, ellipses, splines,
  polyline arc segments), plus **QUA** on every round shape, **TAN**,
  **INS** and **GCE** (geometric center) — with their snap markers.
- **The running object snap list** on the status bar, the classic one
  (right-click the OSNAP button): per-mode checkboxes, Select All /
  Clear All, and the Drafting Settings dialog.

### Added — the working session
- **SAVE / Ctrl+S** (with save-as when untitled), **UNITS** (mm/cm/m,
  the classic dialog), and the inquiry commands **DIST / ID / AREA /
  LIST**.
- **A startup window**: pick the template unit, or reopen
  a recent drawing from its thumbnail.
- **Command prefix autocomplete**: an unambiguous prefix runs the command
  (`OFF` → OFFSET), aliases still win, ambiguity resolves alphabetically
  — the usual autocomplete rule.
- **Properties bar completed**: linetype, lineweight and colour of the
  selection, and the current-properties defaults for new entities
  ($CECOLOR/$CELTYPE/$CELWEIGHT round-trip to the DXF header).
- **The Modify toolbar icons redrawn in the classic style** (traced from a
  screenshot, not from memory — the first attempt proved memory draws
  the wrong icons).
- The crosshair yields to the classic pickbox-only cursor while a command
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
built the same way: take the documented behaviour of classic CAD first (other CAD
cross-checked — option lists match in every command we compared),
then implement the exact prompt tree, then verify the result live against the
reference. If a classic CAD prints `Specify dimension line location or
[Mtext/Text/Angle/Horizontal/Vertical/Rotated]:`, so does IngeCAD.

### Added — paper space (Model/Layout, the classic idiom end-to-end)
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
- **PAGESETUP** rebuilt as the classic Page Setup dialog, group by group
  (printer/paper/area/offset/scale/orientation/options), stored per layout in
  the DXF plot settings, the standard place.
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
  standard geometry.
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
  length, Normal/Calligraphy styles — the classic scalloped cloud.

### Changed — drawing commands brought to prompt-tree parity
- **ARC**: the full 11-way construction matrix (3P, S-C-E, S-C-Angle,
  S-C-chord Length, S-E-Angle, S-E-Radius, S-E-Direction, center-first forms,
  Continue from last). **CIRCLE**: 2P/3P/TTR and Diameter with sticky radius.
  **LINE**: Continue chain, tangent lock after an arc, real mid-command Undo.
  **PLINE**: arc mode with tangent chaining, Width/Halfwidth taper, Close in
  both modes. **RECTANG**: Chamfer/Fillet/Width/Elevation/Thickness, Area,
  Dimensions, Rotation. **POLYGON**: Edge, Inscribed/Circumscribed with the
  standard drag semantics. **ELLIPSE**: Arc (parametric) and
  Rotation; the axis-swap rule fixed to match the spec. **TEXT**: the 14
  justification anchors, Style, Align/Fit. **-HATCH**: the command-line hatch
  with Properties/Solid/User-defined/draW/Advanced/COlor.
- Session-sticky defaults where classic CAD has them (CIRCLERAD, PLINEWID,
  POLYSIDES, rectangle modes, hatch pattern), and new toolbar icons for every
  new command.

### Added — the Dimension Style Manager (DIMSTYLE)
- `DIMSTYLE` (`D`) opens **the Dimension Style Manager**: styles list
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
  included — the standard semantics.

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
  saved") moved to the command line, where a CAD user reads them and where
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

First usable release: the free classic 2D CAD workflow for Linux, end to end.

### Highlights
- Faithful rendering of real-world DWG/DXF (nested blocks, MTEXT, hatch
  patterns, linetypes, dimensions, OCS, paperspace layouts) on a GPU
  viewport that stays fluid on 90k+ entity drawings.
- Transparent DWG open/save through GNU LibreDWG (r2000 write, with a
  verified-save round-trip check) and optional ODA File Converter export
  (r2018). Numerous LibreDWG encoder/decoder fixes were developed against
  a 1,385-file corpus (99% now convert) and are being upstreamed.
- Classic pre-ribbon UI with a real command line and `.pgp`-compatible
  aliases; Model/Layout tabs; Layers, Properties and Styles panels.
- Full 2D drafting set: draw (line, circle, arc, polyline, rectangle,
  polygon, text, hatch, dimensions), edit (erase, move, copy, rotate,
  scale, mirror, offset, trim, extend, fillet, explode), grips,
  window/crossing selection, object snaps with their markers,
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
