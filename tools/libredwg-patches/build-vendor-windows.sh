#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Cross-build IngeCAD's patched LibreDWG converters for Windows (#28).
#
# The same release and the same patch as build-vendor.sh, compiled with
# mingw-w64 on Linux -- how LibreDWG builds its own win64 release -- and
# linked statically, GNU libiconv included (mingw has no iconv, and without
# it the drawing's codepage is not converted: accents come out wrong). The
# result is two self-contained programs, no DLL beside them:
#
#     vendor/libredwg/win64/dwg2dxf.exe
#     vendor/libredwg/win64/dxf2dwg.exe
#
# Needs: x86_64-w64-mingw32-gcc (Debian/Ubuntu: gcc-mingw-w64-x86-64),
# make, curl, gpgv. Check the output with wine:
#     wine vendor/libredwg/win64/dwg2dxf.exe --version
set -euo pipefail

VERSION=${LIBREDWG_VERSION:-0.14.8597}
SHA256=${LIBREDWG_SHA256:-af2646681858a78d756cfb9e0eeb6901f61be3d09ae8f56a98e94b1490dec4ed}
ICONV=${ICONV_VERSION:-1.17}
ICONV_SHA256=${ICONV_SHA256:-8f74213b56238c85a50a5329f77e06198771e70dd9a739779f4c02f65d971313}
HOST=x86_64-w64-mingw32
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
PATCH="$ROOT/tools/libredwg-patches/current/ingecad-vendor-$VERSION.patch"
WORK=${LIBREDWG_WIN_BUILD_DIR:-$ROOT/build/libredwg-win64}
DEST="$ROOT/vendor/libredwg/win64"
JOBS=${JOBS:-$(nproc 2>/dev/null || echo 4)}

[ -f "$PATCH" ] || { echo "!! no patch at $PATCH" >&2; exit 1; }
command -v "$HOST-gcc" >/dev/null || { echo "!! $HOST-gcc not found" >&2; exit 1; }
mkdir -p "$WORK"
cd "$WORK"

echo "==> GNU libiconv $ICONV"
if [ ! -f "libiconv-$ICONV.tar.gz" ]; then
    curl -fsSL -O "https://ftp.gnu.org/gnu/libiconv/libiconv-$ICONV.tar.gz"
fi
echo "$ICONV_SHA256  libiconv-$ICONV.tar.gz" | sha256sum -c -
rm -rf "libiconv-$ICONV" deps
tar xzf "libiconv-$ICONV.tar.gz"
(cd "libiconv-$ICONV" &&
    ./configure --host=$HOST --disable-shared --enable-static \
        --prefix="$WORK/deps" >/dev/null &&
    make -j"$JOBS" >/dev/null && make install >/dev/null)

echo "==> LibreDWG $VERSION + IngeCAD patches"
TARBALL="libredwg-$VERSION.tar.xz"
if [ ! -f "$TARBALL" ]; then
    curl -fsSL -O "https://github.com/LibreDWG/libredwg/releases/download/$VERSION/$TARBALL"
fi
echo "$SHA256  $TARBALL" | sha256sum -c -
SRC="$WORK/libredwg-$VERSION"
rm -rf "$SRC"
tar xf "$TARBALL"
cd "$SRC"
patch -p1 --forward --no-backup-if-mismatch < "$PATCH"

echo "==> building for $HOST with $JOBS jobs"
# --disable-werror: mingw warns about printf-format attributes that the
# Linux build never sees; LibreDWG's own win64 release builds the same way.
./configure --host=$HOST --disable-shared --enable-static \
    --disable-bindings --disable-python --disable-werror \
    CPPFLAGS="-I$WORK/deps/include" LDFLAGS="-L$WORK/deps/lib" >/dev/null
# Only the library and the two programs (the manual wants makeinfo). The
# programs are linked with libtool's -all-static: configure's "-lssp hack
# for mingw" adds -fstack-protector, and a plain -static is dropped by
# libtool for programs, leaving them needing libssp-0.dll.
make -C src -j"$JOBS" >/dev/null
make -C programs -j"$JOBS" dwg2dxf.exe dxf2dwg.exe \
    LDFLAGS="-L$WORK/deps/lib -all-static" >/dev/null

mkdir -p "$DEST"
for tool in dwg2dxf dxf2dwg; do
    install -m 0755 "programs/$tool.exe" "$DEST/$tool.exe"
    "$HOST-strip" "$DEST/$tool.exe"
done
# Self-contained, or fail: nothing but Windows' own DLLs may be imported.
for exe in "$DEST"/*.exe; do
    foreign=$("$HOST-objdump" -p "$exe" | awk '/DLL Name/ {print tolower($3)}' |
              grep -v -E '^(kernel32|msvcrt|advapi32|ws2_32|user32|shell32|ucrtbase|api-ms-win-.*)\.dll$' || true)
    if [ -n "$foreign" ]; then
        echo "!! $exe needs: $foreign" >&2
        exit 1
    fi
done
ls -la "$DEST"
echo "Patched Windows build -- see tools/libredwg-patches/README.md."
