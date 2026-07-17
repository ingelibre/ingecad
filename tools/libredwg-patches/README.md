# LibreDWG patches (Track L)

IngeCAD embeds LibreDWG's `dwg2dxf`/`dxf2dwg` as satellite converters
(`vendor/libredwg/bin`, gitignored). These patches fix crashes found through
the real-file bench and are applied on top of the **0.14** release tarball.

| Patch | Status upstream |
|---|---|
| `0001-dxf-fix-null-deref-PROXY_ENTITY.patch` | Backport of upstream `af67061c` (fixed after 0.14) — SIGSEGV writing partially decoded PROXY_ENTITYs |
| `0002-dxf-hex-encode-binary-TF-chunks.patch` | **Ours, still broken in master** — `proxy_data` (group 310) written as raw bytes instead of hex; to be submitted upstream |

Both were found with the same file: a 27 MB r2013 cadastre DWG whose
ACAD_PROXY_ENTITYs decode partially (AcDs segments). Before the patches the
conversion segfaulted mid-write; after them the drawing opens fully
(92k entities).

## Rebuilding vendor/libredwg

```sh
curl -LO https://github.com/LibreDWG/libredwg/releases/download/0.14/libredwg-0.14.tar.xz
tar xf libredwg-0.14.tar.xz && cd libredwg-0.14
for p in ../tools/libredwg-patches/0*.patch; do patch -p1 < "$p"; done
./configure --disable-shared --disable-bindings --disable-python \
            --prefix="$PWD/../vendor/libredwg"   # PKG_CONFIG=/bin/true if pkg-config is missing
make -j"$(nproc)" && make install-strip
```
