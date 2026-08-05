# LibreDWG patches (Track L)

IngeCAD embeds LibreDWG's `dwg2dxf`/`dxf2dwg` as satellite converters
(`vendor/libredwg/bin`, gitignored).

## Current state — 2026-08-04: the patch stack is GONE

`vendor/libredwg` is now built from the **stock `0.14.8556` release, with no
patches at all**. Everything that used to live here is upstream.

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

Four PRs (#1312, #1314, #1319, #1321) are still marked OPEN although their
content is already applied upstream; worth closing with a pointer to the
commit that superseded them.
