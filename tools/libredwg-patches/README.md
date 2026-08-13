# LibreDWG patches (Track L)

IngeCAD embeds LibreDWG's `dwg2dxf`/`dxf2dwg` as satellite converters
(`vendor/libredwg/bin`, gitignored).

## Current state — 2026-08-13: base 0.14.8580 + seventeen patches, taken FROM THE PRs

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
