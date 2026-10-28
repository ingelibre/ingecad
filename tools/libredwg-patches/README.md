# LibreDWG patches (Track L)

IngeCAD embeds LibreDWG's `dwg2dxf`/`dxf2dwg` as satellite converters
(`vendor/libredwg/bin`, gitignored).

## 2026-10-19: no false errors saving a recent AutoCAD plan

Appended to `current/ingecad-vendor-0.14.8597.patch`. Every AutoCAD 2013+
plan saved as DWG ended in "Saved with a warning" (found by a plugin
author filtering the log; three AutoCAD 2018 plans of the corpus: 16 to 37
errors each).

- **`add_HATCH` dropped a boundary line's end Y of exactly 0** (`&&
  pair->value.d != 0.0` on code 21 only; code 11 never had it), logging
  "Unknown DXF code 21 for HATCH". The point was zero-initialised anyway,
  so the geometry was right and only the log lied; a spline fit point
  with Y = 0 went the same way.
- **DETAILVIEWSTYLE / SECTIONVIEWSTYLE read their colors only from an
  R2004+ DXF** (`FIELD_CMC2004`). A DXF writer that keeps an object it
  does not know -- ezdxf writing the R2000 intermediate of a 2018 plan --
  passes the 62s on; the reader lost its place at the first one and the
  style reached the DWG with its sizes and text style zeroed. Now the
  color is read whenever it is there (`dxf_read_CMC` backs up if not).

ODA as the judge: the styles of a 2018 plan saved by IngeCAD read back in
ODA with the original's heights, offsets and text styles (zeroed before).
Their colors still come back ByBlock instead of ByLayer, but already in
`dwg2dxf`'s DXF of the original: a read-side bug, not this one. `make
check` 286/0; `dwg_fuzz` 500 seeds identical, seed by seed. Of four AutoCAD 2018 plans,
three now save without a warning; the fourth still logs "Illegal
BLOCK_HEADER *Model_Space.entities[7]", which loses nothing there (ODA:
7601 entities in, 7601 out, type by type) but is not understood yet, so
it still warns. Upstream: #1464 (HATCH) and #1465 (view styles), 2026-10-20.

## 2026-10-19: justified text keeps its alignment point in the DWG

Appended to `current/ingecad-vendor-0.14.8597.patch`. Reported by a user
(IngeCAD #95): a DXF opened and saved as DWG reopened with every centred
text at 0,0.

- **`dwg_set_dataflags` dropped the alignment point when it equalled the
  insertion point** (bit 0x02 = "not stored"). ezdxf, like other DXF
  writers that do not compute the left baseline point, writes a justified
  TEXT/ATTDEF/ATTRIB with both points alike; the point a non-left
  alignment places the text by was then left out, and an absent alignment
  point reads back as 0,0 -- in LibreDWG and in ODA. The same macro already
  keeps the horizontal and vertical alignments that use it; now a non-zero
  alignment keeps the point too.

ODA as the judge: 10 justifications (LEFT ... FIT) written by `dxf2dwg`
read back in ODA at their alignment points, ODA recomputing the insertion
as AutoCAD does (all but LEFT/ALIGNED/FIT at 0,0 before). `make check`
286/0; `dwg_fuzz` 500 seeds identical, seed by seed. Upstream: #1463 (2026-10-20).

## 2026-10-11: 2-line angular dimensions keep their points

Appended to `current/ingecad-vendor-0.14.8597.patch`. Found by re-rendering
every dimension of the corpus in place: 2-line angular dimensions read
nonsense (521 of 646 differed from the author's block).

- **`dwg.spec` read the points in the wrong order.** In the DWG stream the
  arc point (DXF 16) comes first, as a 2RD, and the second line's end (DXF
  10) last, as a 3BD (ODA spec); the spec read the 2RD into `def_pt` and
  the last 3BD into `xline2end_pt`, swapping 10 and 16 both ways. The
  pre-R13 branch above already treats `xline2end_pt` as the arc point.
  DXF and JSON output keep their order.

ODA as the judge: 123 of 123 such dimensions in 40 corpus drawings now
have ODA's points (0 before), and a DWG written by `dxf2dwg` reads back in
ODA with its points (swapped before). With IngeCAD's sector fix in
`core/ezdxf_patches.py`, 132 of 138 redraw to the author's own text (0
before; the rest are a `\M+` degree sign and one extra text). `make check`
286/0; `dwg_fuzz` 500 seeds identical; 150 corpus drawings read with the
same entity counts. Upstream: #1438.

## 2026-10-11: polyline widths survive both ways

Appended to `current/ingecad-vendor-0.14.8597.patch`. Found by a GUI sweep:
`PLINE` with Width, saved as DWG, reopened hairline.

- **`in_dxf` flagged per-vertex widths with bit 4**, which in the DWG is
  "has const_width"; "has widths" is 32. The writer then wrote a constant
  width of 0 and no width list. Also the 41 test.
- **The width list was allocated only by vertex 0's 40.** `dwg2dxf` writes
  no 40/41 for a vertex without width, so a polyline whose first segment is
  thin made `CHK_array` abort the import. Now the first 40 allocates, as the
  first 42 does for bulges.
- **`dwg2dxf` wrote the widths only when the polyline had bulges**
  (`num_bulges == num_points` copied into the widths test): a colleague's
  plan opened with its wide polylines thin.

ODA as the judge: a DWG written by the new `dxf2dwg` reads back in ODA with
every width; on two corpus plans ODA's polylines with widths (2 and 6) are
exactly what the new `dwg2dxf` gives (0 before). Read sweep, 197 corpus
drawings old vs new `dwg2dxf`: same entity counts everywhere, and 962
polylines in 44 drawings get their widths back. `make check` 286/0;
`dwg_fuzz` 500 seeds identical, seed by seed. Upstream: #1437 (all three
were still on master as of a3d51f13).

## 2026-10-10: associative dimensions survive open and Save as DWG

Appended to `current/ingecad-vendor-0.14.8597.patch`. IngeCAD 0.6.7 ties
dimensions to their objects (DIMASSOC = 2, `core/dimassoc.py`); 10 of 40
corpus plans converted by ODA carry DIMASSOC objects (Yanaquihua: 73).

- **DIMASSOC was UNSTABLE**, so `dwg2dxf` wrote none: a colleague's
  associative dimensions opened untied. Made stable.
- **The refs were indexed by bit.** They follow one another: one per set
  bit of `associativity`, each followed by its last-point companion when
  `has_lastpt_ref` (a perpendicular's "from" point, no bit of its own).
  With a companion every later ref was lost -- decoding too: a dimension
  with two perpendiculars has 5 refs for its 2 bits. `dwg2.spec` now reads
  and writes them in sequence.
- **DXF layout as ODA writes it:** the dimension's 330 first; no 74 count
  before the 332s (a DWG count, like the 331s').
- **`in_dxf` `add_DIMASSOC`** rewritten for the sequential layout (6 refs,
  92/301/302, the spec's handle codes), and the 330 in `AcDbDimAssoc`
  imported as `dimensionobj`: left to the generic search it was lost, and
  ODA drops a DIMASSOC that names no dimension.

ODA as the judge: `dwg2dxf` on the 18 corpus plans with DIMASSOC gives 217
of 217 objects identical, tag by tag, to ODA's DXF. A sheet saved by
IngeCAD reads back in ODA with its ties identical to ODA's own conversion,
and Yanaquihua opened in IngeCAD and saved as DWG reads back in ODA with
all 73 identical. Through IngeCAD's save and open the dimension still
follows its line. `make check` 270/0; `dwg_fuzz` 500 seeds identical.
Read sweep (200 corpus drawings, old vs new `dwg2dxf`, IngeCAD's reader):
200/200 the same entities and audit errors, and now 5305 DIMASSOC in 102
of them (none before). Write sweep (120 drawings through IngeCAD's save,
ODA as judge): no drawing worse, and 10 that ODA rejected now read --
the old `dxf2dwg` mis-wrote the DIMASSOC the new reader brings, so both
halves of this patch go together. Upstream: #1434.

## 2026-10-10: annotative scales and viewports survive Save as DWG

Appended to `current/ingecad-vendor-0.14.8597.patch`. Found making Rafael's
annotative dimensions measure the same in a 1:1 and a 2:1 viewport, then
saving as DWG (he works in DWG): every scale came back lost.

- **`object_alias` tested `ACAD_`** in its `ACDB_*OBJECTCONTEXTDATA_CLASS`
  branch -- its own comment says `ACDB_` -- so `dxf2dwg` logged "Unhandled 0
  ACDB_..._CLASS (objects)" for every context object and dropped it: TEXT,
  MTEXT and dimension scale representations all vanished on DXF -> DWG.
- **A dimension context's common body** (`AcDbDimensionObjectContextData`) is
  the embedded `Dwg_OCD_Dimension`, which the generic field search does not
  see: with the prefix right, its `2` (the `*D` block, by name) aborted the
  whole import. `dxf_set_ocd_dimension` sets those groups.
- **RADIM and DMDIM context classes** moved out of `DEBUG_CLASSES` and made
  stable like ALDIM (#1424): they are ALDIM's body plus their arc points.
  No corpus drawing carries one; ODA reads IngeCAD's back.
- **Pre-r2004 viewports were all off.** A viewport is on or off in the
  `VX_TABLE_RECORD` `in_dxf` makes for it, whose `is_on` was never set (a
  commented-out line): every sheet saved as r2000 opened in ODA (and AutoCAD)
  with its viewports off. Now from the DXF 68 status (0 off, else on).
- **A context's own 70 became the class version.** The 70 that follows the
  body's subclass (MTEXT attachment, ...) overwrote `class_version` of
  `AcDbObjectContextData`. `dxf_set_context_70` sends it to the body.
- **MTEXT context columns.** `72` counts the `46` heights that follow; the
  generic search warned "Ignore ... column_heights VECTOR" and kept the
  count, so the writer read the heights from NULL and ODA segfaulted on the
  DWG of a real bridge plan (the A/B sweep below caught it). Now the vector
  is allocated from 72 and filled from each 46.

ODA as the judge: IngeCAD's sheet with linear, aligned, radius and diameter
dimensions at 1:1 and 2:1 goes through `dxf2dwg` and reads back with no audit
error, every scale of every dimension with its own block, and the viewports
on (a viewport whose 68 is 0 stays off). Through IngeCAD's own save and open
the 1:1 and 2:1 viewports draw the same text (1014/1014 px). `make check`
270/0; `dwg_fuzz.py run --count 500` identical seed by seed to the build
without it. A/B sweep of 120 corpus drawings through IngeCAD's save path
(load_dwg -> intermediate DXF -> old and new `dxf2dwg` -> ODA): 120/120 the
same (102 read by both, 15 rejected by both, 3 IngeCAD cannot open); before
the columns fix one bridge plan crashed ODA with the new build only.
Upstream: #1432 (context import: prefix, dimension body, 70, columns) and
#1433 (r2000 viewports on). The RADIM/DMDIM promotion stays vendor-only.

## 2026-10-08: xref blocks survive Save as DWG (IngeCAD #66)

Appended to `current/ingecad-vendor-0.14.8597.patch`. An r13+ DXF has no 70
in BLOCK_RECORD: a block's xref bits (70: 4 xref, 8 overlay, 32 resolved)
and its path (1) are only in the BLOCK entity, while a DWG keeps them in
the BLOCK_HEADER. `new_object` threw away BLOCK's 70 and 1 as "DXF
artifacts", and the 1 that dynapi did take landed in `BLOCK.xref_pname`,
which no DWG writes. So every xref saved through `dxf2dwg` came back as an
empty plain block: an attached title block vanished after save and reopen
(Rafael, review 6). Now the 70 bits go to the owning BLOCK_HEADER and the
path is copied to it when the BLOCK is linked (upstream PR #1431). ODA reads the result as an
xref (70 = 4, 1 = `./FormatoA4.dxf`; before: 0 and empty). `make check`
270/0; `dwg_fuzz.py run --count 500` identical seed by seed to the build
without it.

## Current state — 2026-09-27: re-based on 0.14.8597

`current/ingecad-vendor-0.14.8597.patch` carries everything below onto the
0.14.8597 release (2026-09-10; 15 commits since 0.14.8580, among them an
undersized realloc in `bit_copy_chain`, bounds on the codepage index, the
MTEXT background scale read as BD, and two `cquote` fixes). #1392 (EED
1070/1071 signed) is in that release and left the patch; every other hunk
applied unchanged. `build-vendor.sh` and the Flatpak manifest point at it.

Measured against the 0.14.8580 build with the same patches: `dwg2dxf` over
all 1657 corpus drawings gives the same result and entity count in every
one; the save sweep over 213 drawings opens in ODA and IngeCAD 182 -> 185,
none worse. `make check` 270/0.

## Previous state — 2026-09-27: the 2026-09-24 stack + Save-as-DWG fixes for fields, accents and proxies

Same base and patches as below, plus three fixes to `src/in_dxf.c` found by
sweeping the corpus through IngeCAD's real save path (`load_dwg` →
`save_as` DWG → reopen, ODA File Converter as the judge), appended to
`current/ingecad-vendor-0.14.8580.patch`:

- **`Invalid DXF code 16 for DIMENSION_ANG3PT`.** Our July patch 0009 was
  reimplemented upstream as `strEQc (name, "DIMENSION")`, but `name` is the
  subtype by then, so it never matched: one 3-point angular dimension
  aborted the whole import. `memBEGINc` makes it match. Hits every drawing
  where a user dimensions an angle by three points.
- **Dictionary keys lost their accents.** A pre-r2007 DXF is in the
  drawing's codepage; `add_dictionary_itemhandles` and seven more importers
  passed its bytes to `dwg_add_u8_input`, which expects UTF-8 and drops the
  rest. A layout "Presentación1" came back as "Presentacin1" in
  `ACAD_LAYOUT` and ezdxf could not reopen the file (9 of 266 drawings).
  `dxf_add_text` copies the bytes for pre-r2007 DXF, as `dynapi_set_helper`
  does.
- **FIELDLIST without its fields.** Each 330 after the count was taken for
  the owner, so `fields[]` stayed empty and ODA/AutoCAD refused the whole
  DWG ("Object improperly read: AcDbFieldList"). Every drawing with fields.

Branches `fix-dimension-subtype-groups`, `in_dxf-codepage-dictionary-keys`
and `in_dxf-fieldlist-fields` in `~/Proyectos/externos/libredwg`, one fix
each, for upstream PRs.

Then proxy entities (Civil 3D, AutoCAD Architecture, MEP objects: 262 of
the corpus drawings carry them, 152 645 proxies), appended as a second
block of the same patch. Before it, saving any such drawing lost every
proxy's graphics, and ODA/AutoCAD refused many of them outright
("Object improperly read: <AcDbProxyEntity>, No ClassId"):

- **Class number (`dwg.spec` ENCODER, `out_dxf.c`).** The DWG keeps the
  application's class number in the proxy (`proxy_id`); the encoder wrote
  the DXF 90 (always 498) there. And `dwg2dxf` numbered 91 by DWG class
  index, which drifts from the CLASSES section once r2004+ skips
  `ACDBPLACEHOLDER`/`LAYOUT`: `dxf_class_number` counts only the classes
  actually emitted. PROXY_ENTITY/OBJECT now write 90 = 498/499 and that 91
  in every version, as ODA does.
- **Graphics in `AcDbProxyEntity` (`out_dxf.c`, `common_entity_data.spec`).**
  They went out at `AcDbEntity` level (160 since r2010), where ezdxf keeps
  them on reading but drops them on writing: the proxy came back empty
  from IngeCAD's save. Now 92/310 inside the proxy subclass, once.
- **92 of a proxy is its graphics (`in_dxf.c`).** The field matcher gave
  it to `proxy_data_size` and ignored the 310s; it now goes to
  `ent->preview` in every version.
- **No second copy of the graphics in the DWG (`dwg.spec`).** The decoder
  read `preview_size` bytes of `proxy_data` that the format does not have
  (the graphics are the common entity preview), and the encoder wrote them
  back as zeros — the application's data turned into zeros, doubled in size.

- **The proxy's format version (group 95).** It packs the maintenance
  release in the high word and the AcDbDwgVersion in the low one
  (`0x7D001F` for r2013, what ODA writes); `dwg2dxf` wrote the saving
  application's header byte shifted by 8, the spec and `in_dxf` unpacked it
  the same wrong way, and a proxy saved as r2000 still claimed a newer
  format — ODA refuses that whole file ("Out of range"; 28 of 213 drawings
  after the fixes above). `dwg2dxf` now writes the source drawing's version
  from `dwg_versions[]`, and the encoder clamps an object newer than the
  target to the target's version.

- **A large preview was written without its bytes (`common_entity_data.spec`).**
  The `preview_size < obj->size` bound belongs to the reader; in the encoder
  `obj->size` is not known yet, so a proxy with 185 KB of graphics had its
  size written and its bytes skipped, and every object after it was
  misread (0619: 3112 entities came back as 78, ODA refused the file). The
  bound is now the decoder's only.

Measured: `make check` 270/0; `dwg2dxf` old vs new over the 262 proxy
drawings: same entities in all, decoded proxy graphics equal in 243 and
more in 10, fewer in none; letrina 0028: 128 graphic entities → ODA reads
128 with no error → IngeCAD reopens 128.

## Previous state — 2026-09-24: the 2026-08-13 stack + two EED fixes + annotative context data

Same base and seventeen patches as below, plus two fixes to `add_eed` in
`src/in_dxf.c`, appended to `current/ingecad-vendor-0.14.8580.patch` and
opened upstream as PRs #1422 and #1423:

- **Several applications' XDATA fused into one** (#1422). The slot a
  `1001` fills with its APPID handle was wiped by a `memset` when the
  group's first value reused it (every group but the first), and the search
  for the group's header walked down without stopping, so it always found
  the first group. On 42 real drawings: 851 objects with two or more EED
  groups, **0 intact before, 851 after**; single-group objects unchanged.
  What it was erasing on every Save as DWG: `AcadAnnotative` flags,
  Topografía's `INGECAD` point data, any other application's data.
- **`ACAD` hard-coded at 5.1.12** (#1423). ezdxf creates it at 2A, so
  in every drawing started in IngeCAD the EED pointed at the wrong object;
  ODA/AutoCAD audited it away and a dimension lost its DSTYLE overrides —
  including the DIMLFAC = 1/scale that makes a dimension drawn through a
  viewport read model units. Now looked up in the APPID table, 5.1.12 only
  as the fallback.

- **Annotative scale representations reach the DXF** (#1424). `dwg2dxf`
  decoded the TEXT/MTEXT/ALDIM/BLKREF/LEADER context-data objects but kept
  them out of DXF as unstable classes, so every annotative object opened
  at its default scale only. Promoted, with their DXF layout fixed to ODA's
  (MTEXT 10/11 order, no own subclass markers, BLKREF scales 41-43, 2D
  ALDIM text point): 5 275 TEXT, 755 MTEXT, 184 ALDIM, 402 BLKREF and 7
  LEADER context objects in eight drawings identical to ODA tag by tag;
  104 drawings with these classes convert with the same category and entity
  count as before. `dxf2dwg` still does not import them — Save as DWG warns.

Found while measuring annotative scaling (the flags were being erased).
Verified: upstream `make check` 284/284 on each fix alone and on both; ODA
reads the written DWG like the source DXF; `tests/test_xdata_roundtrip.py`
fails on the previous vendor and passes on this one; 340 DWG-related
IngeCAD tests green; `main.py --check` OK.

## Previous state — 2026-08-13: base 0.14.8580 + seventeen patches, taken FROM THE PRs

Re-vendorized onto release **0.14.8580** (`current/ingecad-vendor-0.14.8580.patch`,
built by `build-vendor.sh`). The seventeen are exactly the seventeen pull requests
still open upstream: #1358, #1359, #1360, #1364, #1365, #1368, #1369, #1371, #1372,
#1373, #1375, #1378, #1381, #1382, #1385, #1387 and the new #1392.

⚠️ **The rule this re-vendorization exists to enforce: every hunk comes from the
pull request's own head** (`git fetch origin pull/N/head`), never from a local
branch. The previous vendor carried a **stale draft of #1375** — an early attempt
that converted inside `dwg_add_u8_input` with no source-version guard — and it
corrupted MTEXT in every pre-r2007 drawing. It was mistaken for an upstream bug and
reported as issue #1393 before the comparison against stock caught it. A local
branch is a workbench; the PR is what exists upstream.

**What changed for the user.** Accents now survive a save in every place a string
can live. The same drawing carrying `CAÑERÍA Ø m² Nº45°`, through
`dxf2dwg --as r2000` and back, byte-checked:

| place | old vendor (R2018 source) | new |
|---|---|---|
| layer / text style / block name | `DESAGÃœE` | correct |
| TEXT, ATTRIB, dimension text | `CAÃ‘ERÃA` | correct |
| XDATA string | `CAÃ‘ERÃA` | correct |
| MTEXT (pre-r2007 source) | `CAхŔ ؠm N` | correct |

All sixteen cells of that matrix (eight places × two source versions) are correct
now; the old vendor had seven of them wrong.

**New in this stack: #1392** — EED groups 1070/1071 were emitted unsigned, so every
negative value in the data other applications attach to entities came back as its
unsigned complement (`-6700` as `58836`). 2595 corrupted values across 200 real
drawings, in 146 of them.

**Verified:** upstream `make check` 254/254; the combined patch reproduces the built
tree source-for-source from a pristine tarball; `main.py --check` OK; 682 IngeCAD
tests green; accents round-trip end to end through `Document.save_as`.

⚠️ **r2004 as a save target stays OFF** — unchanged, see the note below.

## Previous state — 2026-08-10: base 0.14.8578 + SEVENTEEN patches

Re-vendorized onto release **0.14.8578** (`current/ingecad-vendor-0.14.8578.patch`,
built by `build-vendor.sh`). Upstream absorbed **10 of our fixes** between 0.14.8556
and this tag (the whole a8ce2489..0.14.8578 window is our merged PRs: SEQEND
#1370, SPLINE fit-only #1374, CMC #1376, true color #1377, MTEXT 50 #1379,
`--as r12` #1380, pre-R13 addresses #1381 (rurban's version), $MODEL_SPACE #1384,
sentinel search #1362-redo, trailing newline #1366-redo). The 17 still carried:

- the 8 unmerged read fixes of the 2026-08-06 wave (#1358, #1359, #1360,
  #1364, #1365, #1368, #1369 + the TIMEBLL spec halves),
- the unmerged write/import fixes: subentity ownership #1371, stale-subentity
  #1372, BLOCK_HEADER-without-BLOCK #1373, UTF-8→codepage #1375 (dynapi/MTEXT
  parts), next-handle-max #1382, MINSERT defaults #1385, r14 linetype #1378,
  proxy-graphics preservation **#1387** (Civil 3D UNKNOWN_ENT → ACAD_PROXY_ENTITY,
  now actually shipped in the app),
- the TV-NUL comment refinement.

Verified: 304 IngeCAD tests green; read parity exact on the capturas plans
(10 084 = 10 084, 9 847 = 9 847 entities old vs new); write-path fuzz over 80
seeds improves from 4 OK / 12 EMPTY / 8 LOST / 17 EXTRA (old vendor) to
10 OK / 33 DIFF with **zero** EMPTY/LOST/EXTRA.

⚠️ **r2004 as a save target stays OFF.** Any model built by `in_dxf` (the
dxf2dwg path IngeCAD uses) encodes an r2004 whose object stream LibreDWG
cannot re-read (objects truncate at ~21-39, ownership handles broken) — on
stock 0.14.8578, on the patched stack, and on the pre-window base alike.
Minimal repro: `ezdxf 1-line DXF → dxf2dwg --as r2004 → dwg2dxf → empty
ENTITIES`. The L4 notes' "r2004 works" was measured on `dwgrewrite` of a
same-version DWG-decoded model + the ODA oracle — a different path. Next
Track L target; IngeCAD keeps writing r2000.

## Previous state — 2026-08-07: THIRTEEN patches, all submitted upstream

> **`vendor/libredwg` is no longer stock.** It is built from `0.14.8556` plus the
> thirteen fixes below, every one of them open as a PR upstream. Each exists because
> it recovers real drawings that stock refuses; each goes away the moment
> upstream merges it and we take a new release.
>
> The stock build it replaced is kept at `vendor/libredwg.stock-0.14.8556`.

| Patch | PR | What it recovers |
|---|---|---|
| `dwg.spec` — `INSERT.has_attribs` pre-R13 normalized to 0/1 | [#1352](https://github.com/LibreDWG/libredwg/pull/1352) | invalid DXF group 66, no drawing lost |
| `out_dxf.c` — R11 `JUMP` records not written as entities | [#1353](https://github.com/LibreDWG/libredwg/pull/1353) | 3 upstream test files, unreadable → readable |
| `decode.c` — r2004 sections whose declared size exceeds the page estimate | [#1358](https://github.com/LibreDWG/libredwg/pull/1358) | `cerco perimetrico` + both `Planos Constructivos`: 0 → 2222 / 26583 / 26583 |
| `dwg.c` — skip unresolvable owned entities instead of ending the layout | [#1359](https://github.com/LibreDWG/libredwg/pull/1359) | `sedapar` 93 → 8588; `yanaquihua` and `cofopri` +47k and +69k inside blocks |
| `decode.c` — resync the object map when a modular char fails to parse | [#1360](https://github.com/LibreDWG/libredwg/pull/1360) | `frontal` 0 → 1039, identical to ODA |
| `decode.c` — pre-R13 sentinel search widened to the ±1000 it documents | [#1362](https://github.com/LibreDWG/libredwg/pull/1362) | `primer piso` and `segundo piso`: no output at all → 1246 and 1459, identical to ODA |
| `decode_r2007.c` — Reed-Solomon decode uncompressed data pages too | [#1363](https://github.com/LibreDWG/libredwg/pull/1363) | `sedapar` 8588 → 10847 = ODA, and its 33 188 garbage vertices → 0. Closes #1361 |
| `decode_r11.c` — a missing table sentinel no longer rejects the drawing | [#1364](https://github.com/LibreDWG/libredwg/pull/1364) | **another user's [#767](https://github.com/LibreDWG/libredwg/issues/767), open since 2023-06**: 0 → 553 entities, identical to ODA |
| `dwg2SVG.c` — blank output, four independent causes | [#1365](https://github.com/LibreDWG/libredwg/pull/1365) | **[#523](https://github.com/LibreDWG/libredwg/issues/523) (4 reporters, open since 2022-11) and [#1012](https://github.com/LibreDWG/libredwg/issues/1012)**: on 95 real drawings, 1 → 68 render a drawing. Not used by IngeCAD |
| `dwg.c` — the `'\0'` was written over the appended `'\n'` | [#1366](https://github.com/LibreDWG/libredwg/pull/1366) | any DXF whose last byte is not a newline was rejected outright, reported as "Out of memory". Partly [#474](https://github.com/LibreDWG/libredwg/issues/474) |
| `bits.c` — UTF-16 surrogates encoded into the UTF-8 output | [#1367](https://github.com/LibreDWG/libredwg/pull/1367) | one damaged APPID name made AutoCAD refuse a whole DXF. Partly [#1021](https://github.com/LibreDWG/libredwg/issues/1021) |
| `dwg_api.c` + `decode.c` + `out_dxf.c` — pre-R13 paper space had no BLOCK_HEADER | [#1368](https://github.com/LibreDWG/libredwg/pull/1368) | **[#1337](https://github.com/LibreDWG/libredwg/issues/1337)**, the direction michal-josef-spacek and rurban agreed: an AC1009 goes from 8/0 to 3/5 entities per space, matching AutoCAD |
| `common.h`/`common.c`/`bits.c`/`dwg_api.c`/`in_json.c` + 2 specs — TIMEBLL's day fraction, spelled three incompatible ways | [#1369](https://github.com/LibreDWG/libredwg/pull/1369) | **[#1309](https://github.com/LibreDWG/libredwg/issues/1309)**: every `$TD*` timestamp was 0.864× short, up to 3.3 h. Three now match ODA to every digit |

Eight of the thirteen touch **other users' issues**: `#1358` closes
[#1294](https://github.com/LibreDWG/libredwg/issues/1294) (stalled since June
2026 for want of a shareable reproducer), and `#1364` closes
[#767](https://github.com/LibreDWG/libredwg/issues/767) (open since June 2023 —
Reini Urban had sketched the direction there and nobody had taken it up), and
`#1365` closes [#523](https://github.com/LibreDWG/libredwg/issues/523) (four
reporters since November 2022) together with
[#1012](https://github.com/LibreDWG/libredwg/issues/1012). `#1360` corrects a root cause I had posted wrongly in
[#1355](https://github.com/LibreDWG/libredwg/issues/1355).

`#1363` closes [#1361](https://github.com/LibreDWG/libredwg/issues/1361), which
I had filed with the wrong diagnosis: I read the `LWPOLYLINE` point arrays as
"desynchronising mid-list" when they were being read out of Reed-Solomon
codewords. Corrected publicly in that issue. `render/batches.py::_world_extents`
still filters against the drawing's declared `$EXTMIN`/`$EXTMAX` — it costs
nothing and no longer has anything to catch on our corpus, but a viewer should
not frame 10³⁰¹ because one vertex says so.

Still open and **not** patched here:
[#1356](https://github.com/LibreDWG/libredwg/issues/1356) — duplicate handles in
the emitted DXF (1150 of them in `sedapar`, unchanged by #1363). IngeCAD works
around it with `formats/dwg_bridge.py::_dedupe_handles`.

Verified with `make check` 270 PASS / 0 FAIL, the 146 upstream DWGs re-converted
identically, a 190-drawing corpus sweep going `OK` 160 → 172 and `NO_OUTPUT`
3 → 1 with zero regressions, an A/B over all 18 pre-R13 drawings for #1364
(4115 entities before and after, nothing changed), and — for #1363, whose blast radius is exactly
AC1021 because `decode_R2007` is reached only for `R_2007a..R_2007` — an A/B over
**all 47 AC1021 drawings** in a 1657-file corpus: **+28 714 entities, 6 drawings
gaining, 0 losing**.

**Six of the seven make the code do what it already said about itself** — three
sibling lines already normalized the flag (#1352), the `else` eight lines below
already computed the right size (#1358), the failed `bit_read_UMC` was already
detected and then ignored (#1360), the recovery path already existed and the
comment already promised ±1000 (#1362), and `read_data_page()` already separated
RS decoding from decompression while its one caller conflated them (#1363 — the
`TODO` in that very comment asked the right question). The two fixes I tried to invent from the format
instead, both for #1355, both failed and are documented as such in that issue.

Rebuild recipe below. The tree it comes from is
`~/Proyectos/externos/build-libredwg/libredwg-0.14.8556`, which carries the seven
patches plus `0030`, and a `NO-ES-STOCK-LEEME.txt` saying so. **Read that file
before copying anything out of that tree.**

## Before this: 2026-08-04, the first patch stack was dropped

The state that this section replaces: `vendor/libredwg` was built from the
**stock `0.14.8556` release, with no patches at all**, because everything in the
first 29-patch stack had landed upstream.

The twelve PRs from the first round (#1311–#1322) all landed: four merged as
PRs (#1311, #1313, #1315, #1318), the rest reimplemented by Reini Urban from
our descriptions on 2026-07-26. Verified mechanically — our `af364d4c` is an
ancestor of `origin/master`.

The 29 patches are kept in `applied-upstream/` for the record; they apply to
the old `0.14` tarball and must NOT be reapplied on top of a current release.

### Bench: 0.14 + 29 patches vs 0.14.8556 stock

Same 502 real DWGs through `tools/dwg_bench.py`, one run per converter
(that is what `--dwg2dxf` is for):

| | patched 0.14 | stock 0.14.8556 |
|---|---|---|
| usable (OK) | 492 (98.0%) | 492 (98.0%) |
| category changes | — | **0** |
| entities recovered | — | **+283 across 23 drawings** |
| drawings losing entities | — | **0** |
| wall clock | 1461 s | 1454 s |

Identical categories, strictly more entities recovered, same speed. That is
the evidence for dropping the stack: not "the new one looks fine", but "no
file got worse and 23 got better".

Upstream's own suite: **270 PASS / 0 FAIL** (gcc 15.2.0) — after `0030` below.

Full sweep afterwards: **1657 drawings, 98.2% usable, 19.1 M entities**, only
24 failures across 9 distinct signatures — and **15 of those 24 are LibreDWG's
own test files**, so the next round of reports needs no client drawings at all.
See `docs/bench-libredwg-2026-08-04.md`.

## Pending patch

| Patch | Status |
|---|---|
| `0030-add_test-const-correct-version-string-scanners.patch` | Ours — submitted as [LibreDWG#1350](https://github.com/LibreDWG/libredwg/pull/1350). `make check` does not COMPILE on gcc 15: `add_test.c` keeps `strchr()` results over `const` strings in plain `char *`, and the test suite builds with `-Werror`. One line. Test-only: it does not affect the shipped binaries, so `vendor/` does not need it. |

## Rebuilding vendor/libredwg

**One command**, and it is what the release workflow runs on a clean checkout:

```sh
tools/libredwg-patches/build-vendor.sh
```

It fetches the `0.14.8556` tarball, verifies it against the project's own
`dist.sha256`, applies `current/ingecad-vendor-0.14.8556.patch` (the thirteen
patches above, combined), builds with `--disable-shared` so the converters end
up statically linked, and installs **only** `dwg2dxf` and `dxf2dwg` into
`vendor/libredwg/bin` — the other ten programs add ~118 MB and IngeCAD never
invokes them.

Verified reproducible: rebuilding from scratch gives a `dwg2dxf` that differs
from the shipped one in **20 bytes**, all inside `.note.gnu.build-id`, and reads
the same nine drawings to the same entity counts.

The combined patch is generated from the `vendor-0.1.2` branch of the fork
(`git diff origin/master..vendor-0.1.2`), which holds the same file contents this
tree is built from. It exists because `vendor/libredwg` is gitignored, so
without it a fresh clone has no converters; it shrinks as the PRs land.

## Rebuilding by hand

```sh
cd ~/Proyectos/externos/build-libredwg
V=0.14.8556
curl -LO https://github.com/LibreDWG/libredwg/releases/download/$V/libredwg-$V.tar.xz
curl -L  https://github.com/LibreDWG/libredwg/releases/download/$V/dist.sha256 -o dist.sha256
grep "$V.tar.xz" dist.sha256 | sha256sum -c -     # do check it
tar xf libredwg-$V.tar.xz && cd libredwg-$V
./configure --disable-shared --disable-bindings --disable-python \
            --prefix="$PWD/../prefix-$V"          # PKG_CONFIG=/bin/true if pkg-config is missing
make -j"$(nproc)" && make install-strip
cp -a "../prefix-$V/bin/." ~/Proyectos/ingecad/vendor/libredwg/bin/
```

Before swapping the binaries in, run the bench both ways and diff the CSVs —
`tools/dwg_bench.py <corpus> --dwg2dxf <other-build>/bin/dwg2dxf`. Keep the
previous tree as `vendor/libredwg.anterior-<version>` until the new one has
been used for real work.

## The CLA, and what it means for L4

Reini Urban, closing #1317 and #1320:

> *Excellent. But too big. Needs a CLA*
> *Fixed independently by myself, thanks to your description. Dont want to
> wait for the CLA*

So: **small patches get merged as PRs; big ones do not, without assigning
copyright to the FSF.** At best the maintainer rewrites them from the
description and the credit stays in the thank-you. **L4 (the r2013/r2018
writer) is by definition a big contribution** — decide whether to sign the FSF
CLA before starting it, or accept that it can only live in the fork.

Four PRs (#1312, #1314, #1319, #1321) that were still marked OPEN although
already applied upstream were closed on 2026-08-04 pointing at the commit that
superseded each. Nothing from the first round is left open.

Note for the second round: Reini Urban has not committed since 2026-07-25, while
Michal Josef Špaček, nameloCmaS and Saddam have. Silence on our threads is his
absence, not a verdict — eight commits authored by us are already in master.
