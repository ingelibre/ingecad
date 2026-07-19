# LibreDWG patches (Track L)

IngeCAD embeds LibreDWG's `dwg2dxf`/`dxf2dwg` as satellite converters
(`vendor/libredwg/bin`, gitignored). These patches fix crashes found through
the real-file bench and are applied on top of the **0.14** release tarball.

| Patch | Status upstream |
|---|---|
| `0001-dxf-fix-null-deref-PROXY_ENTITY.patch` | Backport of upstream `af67061c` (fixed after 0.14) — SIGSEGV writing partially decoded PROXY_ENTITYs |
| `0002-dxf-hex-encode-binary-TF-chunks.patch` | Ours — `proxy_data` (group 310) written as raw bytes instead of hex; submitted as [LibreDWG#1311](https://github.com/LibreDWG/libredwg/pull/1311) |
| `0003-dxf-import-dynamic-block-objects.patch` | Ours — four dxf2dwg import fixes (EVALUATION_GRAPH, BLOCKSTRETCHACTION SEGV, EVAL_Edge heap overflow, FIELD childval); submitted as [LibreDWG#1312](https://github.com/LibreDWG/libredwg/pull/1312) |
| `0004-dxf-hatch-boundary-handles-per-path.patch` | Ours — associative multi-path HATCHes lost pattern scale/def lines through the roundtrip (hdl_idx never reset per path); submitted as [LibreDWG#1313](https://github.com/LibreDWG/libredwg/pull/1313) |
| `0005-dxf-string-emission.patch` | Ours — caret-encode C0 controls, embed-before-quote, escape-preserving chunk splits, dxf+2 continuation codes; corpus success 83%→96.6% (1385 real DWGs); submitted as [LibreDWG#1314](https://github.com/LibreDWG/libredwg/pull/1314) |
| `0006-dxf-partial-decode-values.patch` | Ours — fresh handles for objects written with handle 0, out-of-range MTEXT column_type treated as "no columns"; submitted as [LibreDWG#1315](https://github.com/LibreDWG/libredwg/pull/1315) |

0001/0002 were found with a 27 MB r2013 cadastre DWG whose
ACAD_PROXY_ENTITYs decode partially (AcDs segments): the conversion
segfaulted mid-write; with the patches the drawing opens fully (92k
entities). 0003 came from a 4.5 MB AutoCAD 2018 pavement plan with dynamic
blocks that dxf2dwg could not import at all; with it, "save as DWG r2000"
of that plan works end-to-end.

## Rebuilding vendor/libredwg

```sh
curl -LO https://github.com/LibreDWG/libredwg/releases/download/0.14/libredwg-0.14.tar.xz
tar xf libredwg-0.14.tar.xz && cd libredwg-0.14
for p in ../tools/libredwg-patches/0*.patch; do patch -p1 < "$p"; done
./configure --disable-shared --disable-bindings --disable-python \
            --prefix="$PWD/../vendor/libredwg"   # PKG_CONFIG=/bin/true if pkg-config is missing
make -j"$(nproc)" && make install-strip
```

## Batch 2 — patches 0007–0029 upstreamed 2026-07-18

Ported to LibreDWG master (they were written against 0.14; the fork
branches live at `tuxiasumari/libredwg`) and submitted as seven focused
PRs. Full `make check` (254 tests) ran on 0.14+patches; the master ports
are line-identical and compile-checked.

| Upstream PR | Patches | Theme |
|---|---|---|
| [#1316](https://github.com/LibreDWG/libredwg/pull/1316) | 0007, 0008 | quadratic DXF-import slowdowns (19 MB DXF: >5 min → 1.8 s) |
| [#1317](https://github.com/LibreDWG/libredwg/pull/1317) | 0009, 0010, 0011, 0018, 0020 | in_dxf field misreads that abort/corrupt imports |
| [#1318](https://github.com/LibreDWG/libredwg/pull/1318) | 0023, 0024, 0025 | HATCH spline-edge/path corruption |
| [#1319](https://github.com/LibreDWG/libredwg/pull/1319) | 0012, 0016, 0017 | r2000 TV length + bit_write_DD encoder bugs |
| [#1320](https://github.com/LibreDWG/libredwg/pull/1320) | 0019, 0021, 0022, 0026, 0029 | handle/ownership semantics (SORTENTSTABLE, entmode, xref bit, next_hdl) |
| [#1321](https://github.com/LibreDWG/libredwg/pull/1321) | 0013, 0014, 0015, 0027 | MTEXT/DIMENSION fidelity (giant text, distorted dims) |
| [#1322](https://github.com/LibreDWG/libredwg/pull/1322) | 0028 | UTF-8 → codepage conversion for pre-r2007 text (mojibake) |

Not upstreamed: 0001 (backport of upstream af67061c). The dwg.spec
"NULL objids" writer guard from our tree was already fixed independently
on master.
