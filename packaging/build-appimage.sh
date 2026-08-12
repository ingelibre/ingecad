#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
#
# Build a single-file IngeCAD AppImage for x86_64.
#
#     packaging/build-appimage.sh [outdir]
#
# Needs: the project venv with the runtime deps, and vendor/libredwg/bin built
# (see tools/libredwg-patches/README.md). Downloads appimagetool on first run.
#
# WHERE TO BUILD THIS: an AppImage links against the glibc of the machine that
# made it, so one built on Ubuntu 26.04 will not start on 24.04 or 22.04. The
# release workflow uses the oldest runner we support for exactly that reason;
# building here is for testing on this machine.
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
OUT=${1:-$ROOT/dist}
WORK=${INGECAD_BUILD_DIR:-$ROOT/build}
PYTHON=${PYTHON:-$ROOT/venv/bin/python}
ARCH=${ARCH:-x86_64}

cd "$ROOT"
VERSION=$("$PYTHON" -c 'from core.version import __version__; print(__version__)')
APPDIR="$WORK/IngeCAD.AppDir"
APPIMAGE="$OUT/IngeCAD-$VERSION-$ARCH.AppImage"

echo "==> IngeCAD $VERSION -> $APPIMAGE"

for tool in dwg2dxf dxf2dwg; do
    if [ ! -x "vendor/libredwg/bin/$tool" ]; then
        echo "!! vendor/libredwg/bin/$tool is missing." >&2
        echo "   Build it first: tools/libredwg-patches/README.md" >&2
        exit 1
    fi
done

echo "==> PyInstaller"
"$PYTHON" -m PyInstaller --version >/dev/null 2>&1 \
    || "$PYTHON" -m pip install --quiet pyinstaller
rm -rf "$APPDIR" "$WORK/pyi"
INGECAD_ROOT="$ROOT" "$PYTHON" -m PyInstaller --noconfirm \
    --distpath "$WORK/pyi" --workpath "$WORK/pyi-work" \
    packaging/ingecad.spec

echo "==> the bundle finds its own data"
# Before wrapping it in an AppImage, ask the bundle itself. A missing shader or
# converter starts fine and only fails when the user opens a drawing.
"$WORK/pyi/ingecad/ingecad" --check

echo "==> tarball"
# The same bundle, without the AppImage wrapper: extract and run. For users
# whose distro lacks FUSE (the classic AppImage complaint) or who want to
# unpack under /opt. Ships the desktop file and icon for manual integration.
TARDIR="$WORK/IngeCAD-$VERSION"
TARBALL="$OUT/IngeCAD-$VERSION-linux-$ARCH.tar.gz"
rm -rf "$TARDIR"
mkdir -p "$TARDIR" "$OUT"
cp -a "$WORK/pyi/ingecad/." "$TARDIR/"
cp resources/ingecad.desktop resources/icons/ingecad_256.png "$TARDIR/"
cat > "$TARDIR/README.txt" <<'TXT'
IngeCAD — portable Linux build
==============================

Run it:            ./ingecad            (or: ./ingecad drawing.dwg)
Self-diagnosis:    ./ingecad --check

No installation required. To add a launcher and the .dwg/.dxf icons,
edit the Exec= line of ingecad.desktop to this folder's path and copy
it to ~/.local/share/applications/.

Prefer the AppImage from the same release if your distro has FUSE.
TXT
tar -C "$WORK" -czf "$TARBALL" "IngeCAD-$VERSION"
printf '%s  (%s)\n' "$TARBALL" "$(du -h "$TARBALL" | cut -f1)"

echo "==> AppDir"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/applications" \
         "$APPDIR/usr/share/icons/hicolor/256x256/apps" \
         "$APPDIR/usr/share/metainfo"
cp -a "$WORK/pyi/ingecad/." "$APPDIR/usr/bin/"

# AppImage wants the icon and desktop file at the AppDir root as well.
cp resources/icons/ingecad_256.png \
   "$APPDIR/usr/share/icons/hicolor/256x256/apps/ingecad.png"
cp resources/icons/ingecad_256.png "$APPDIR/ingecad.png"
sed 's|^Exec=.*|Exec=ingecad %f|; s|^Icon=.*|Icon=ingecad|' \
    resources/ingecad.desktop > "$APPDIR/usr/share/applications/ingecad.desktop"
cp "$APPDIR/usr/share/applications/ingecad.desktop" "$APPDIR/ingecad.desktop"

# AppRun: keep the launcher tiny and let Qt find its own plugins, which the
# PyInstaller bundle already lays out next to the binary.
cat > "$APPDIR/AppRun" <<'SH'
#!/bin/sh
HERE=$(dirname "$(readlink -f "$0")")
# Wayland first, X11 as the fallback, unless the user forces one.
[ -z "$QT_QPA_PLATFORM" ] && export QT_QPA_PLATFORM="wayland;xcb"
exec "$HERE/usr/bin/ingecad" "$@"
SH
chmod +x "$APPDIR/AppRun"

echo "==> appimagetool"
TOOL="$WORK/appimagetool-$ARCH.AppImage"
if [ ! -x "$TOOL" ]; then
    mkdir -p "$WORK"
    curl -fsSL -o "$TOOL" \
        "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-$ARCH.AppImage"
    chmod +x "$TOOL"
fi

mkdir -p "$OUT"
rm -f "$APPIMAGE"
# --appimage-extract-and-run: appimagetool is itself an AppImage and needs FUSE
# otherwise, which a CI container does not have.
ARCH="$ARCH" "$TOOL" --appimage-extract-and-run "$APPDIR" "$APPIMAGE"

echo "==> the AppImage answers --check"
"$APPIMAGE" --check

printf '\n%s  (%s)\n' "$APPIMAGE" "$(du -h "$APPIMAGE" | cut -f1)"
