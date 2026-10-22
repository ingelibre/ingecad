#!/bin/sh
# GPL-3.0-or-later. Use w64devkit 2.10.0's shell/GCC 16.2.0 on Windows x64.
# Run in this sources folder. Patched source already contains the IngeCAD changes.
set -eu
tar -xf libredwg-0.14.8597-patched.tar.xz
windres utf8.rc -O coff -o utf8.o
cd libredwg-0.14.8597
CFLAGS='-O1 -g' ./configure --build=x86_64-w64-mingw32 --host=x86_64-w64-mingw32 \
    --disable-shared --disable-bindings --disable-python --disable-docs --enable-static
make -C src -j2
mkdir -p programs/.deps
make -C programs dwg2dxf.exe dxf2dwg.exe \
    'dwg2dxf_LDADD=../src/libredwg.la -lm ../../utf8.o' \
    'dxf2dwg_LDADD=../src/libredwg.la -lm ../../utf8.o'
# Result: programs/dwg2dxf.exe and programs/dxf2dwg.exe
