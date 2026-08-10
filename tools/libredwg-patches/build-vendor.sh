#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
#
# Rebuild vendor/libredwg from a pristine LibreDWG release plus the patches
# IngeCAD ships. Reproducible from a clean checkout, which is what the release
# workflow relies on — vendor/libredwg is gitignored, so without this a fresh
# clone has no converters at all.
#
#     tools/libredwg-patches/build-vendor.sh
#
# Needs: a C toolchain, curl, and about 2 GB of scratch space. No autotools:
# the release tarball ships configure and the Makefiles already generated.
set -euo pipefail

VERSION=${LIBREDWG_VERSION:-0.14.8578}
# Pinned: GitHub's dist.sha256 for this release, verified 2026-08-10.
SHA256=${LIBREDWG_SHA256:-2a93a33c56b836d8e4aa3c4009abbc348bd483b640d4b8133b9370c9fafa8e55}
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
PATCH="$ROOT/tools/libredwg-patches/current/ingecad-vendor-$VERSION.patch"
WORK=${LIBREDWG_BUILD_DIR:-$ROOT/build/libredwg}
DEST="$ROOT/vendor/libredwg/bin"
JOBS=${JOBS:-$(nproc 2>/dev/null || echo 4)}

TARBALL="libredwg-$VERSION.tar.xz"
BASE="https://github.com/LibreDWG/libredwg/releases/download/$VERSION"

[ -f "$PATCH" ] || { echo "!! no patch at $PATCH" >&2; exit 1; }

mkdir -p "$WORK"
cd "$WORK"

if [ ! -f "$TARBALL" ]; then
    echo "==> fetching $TARBALL"
    curl -fsSL -O "$BASE/$TARBALL"
fi

# Verify it. The project publishes dist.sha256 next to the tarball; use the
# pinned hash when one was given, otherwise check against theirs.
echo "==> checking the tarball"
if [ -n "$SHA256" ]; then
    echo "$SHA256  $TARBALL" | sha256sum -c -
else
    [ -f dist.sha256 ] || curl -fsSL -o dist.sha256 "$BASE/dist.sha256"
    grep " $TARBALL\$" dist.sha256 | sha256sum -c -
fi

SRC="$WORK/libredwg-$VERSION"
rm -rf "$SRC"
tar xf "$TARBALL"

echo "==> applying the IngeCAD patches"
cd "$SRC"
# --forward so a re-run is not mistaken for a reverse patch; -p1 for git format.
patch -p1 --forward --no-backup-if-mismatch < "$PATCH"

echo "==> building with $JOBS jobs"
# --disable-shared: the converters end up statically linked against libredwg,
# so vendor/ needs no .so and the AppImage carries two self-contained binaries.
./configure --disable-shared --disable-bindings --disable-python \
            --prefix="$WORK/prefix-$VERSION" >/dev/null
make -j"$JOBS" >/dev/null
make install-strip >/dev/null

echo "==> installing into vendor/libredwg/bin"
mkdir -p "$DEST"
# Only the two IngeCAD runs. The other ten add ~118 MB and are never invoked.
for tool in dwg2dxf dxf2dwg; do
    install -m 0755 "$WORK/prefix-$VERSION/bin/$tool" "$DEST/$tool"
done

printf '\n'
"$DEST/dwg2dxf" --version 2>&1 | head -2 || true
printf '%s\n' "vendor/libredwg/bin: $(ls "$DEST" | tr '\n' ' ')"
echo "Patched build — see tools/libredwg-patches/README.md for what is in it."
