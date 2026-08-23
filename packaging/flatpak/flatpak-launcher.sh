#!/bin/sh
# IngeCAD's launcher inside the Flatpak sandbox.
#
# Qt is left to auto-detect the platform: under Wayland the sandbox gets
# WAYLAND_DISPLAY but no DISPLAY, so forcing xcb would fail to connect
# (learned in IngePresupuestos' flatpak, same launcher shape).
#
# pip installed the dependencies under /app's prefix; the runtime's python
# does not look there on its own, whatever its version happens to be.
PYVER=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
export PYTHONPATH="/app/lib/python${PYVER}/site-packages:${PYTHONPATH}"
cd /app/ingecad || exit 1
exec python3 main.py "$@"
