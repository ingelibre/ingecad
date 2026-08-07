# LibreDWG patches (Track L)

IngeCAD embeds LibreDWG's `dwg2dxf`/`dxf2dwg` as satellite converters
(`vendor/libredwg/bin`, gitignored).

## Current state — 2026-08-06: TEN patches, all submitted upstream

> **`vendor/libredwg` is no longer stock.** It is built from `0.14.8556` plus the
> ten fixes below, every one of them open as a PR upstream. Each exists because
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

Five of the ten touch **other users' issues**: `#1358` closes
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
