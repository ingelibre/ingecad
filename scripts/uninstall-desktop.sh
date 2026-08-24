#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Undo scripts/install-desktop.sh: remove the launcher, the menu entry and
# the application icon of a source or tarball install.
#
# Written for the move to the Flatpak, where having both installed shows two
# "IngeCAD" entries in the menu and leaves it ambiguous which one a
# double-clicked .dwg opens.
#
#   scripts/uninstall-desktop.sh              # say what would go
#   scripts/uninstall-desktop.sh --yes        # do it
#
# Deliberately NOT removed, because they are useful with any install and
# removing them would take the branded document icons away:
#   ~/.local/share/mime/packages/ingecad.xml   (the .dwg/.dxf MIME types)
#   ~/.local/share/icons/*/*/mimetypes/image-vnd.d*  (the document icons)
# Nor is anything under ~/.config/IngeCAD touched: those are your settings
# and your recent drawings.
set -e

BIN="$HOME/.local/bin/ingecad"
DESKTOP="$HOME/.local/share/applications/ingecad.desktop"
ICONS="$HOME/.local/share/icons/hicolor"
DO_IT=${1:-}

say() { echo "  $1"; }
gone=0

echo "Removing the non-Flatpak install:"
[ -e "$BIN" ]     && { say "launcher : $BIN"; gone=1; }
[ -e "$DESKTOP" ] && { say "menu     : $DESKTOP"; gone=1; }
for f in "$ICONS"/*/apps/ingecad.png "$ICONS"/scalable/apps/ingecad.svg; do
    [ -e "$f" ] && { say "icon     : $f"; gone=1; }
done
[ "$gone" = 1 ] || { echo "  (nothing to remove)"; exit 0; }

if [ "$DO_IT" != "--yes" ]; then
    echo "Re-run with --yes to remove them."
    exit 0
fi

rm -f "$BIN" "$DESKTOP"
rm -f "$ICONS"/*/apps/ingecad.png "$ICONS"/scalable/apps/ingecad.svg

command -v gtk-update-icon-cache >/dev/null 2>&1 \
    && gtk-update-icon-cache -f "$ICONS" >/dev/null 2>&1 || true
command -v update-desktop-database >/dev/null 2>&1 \
    && update-desktop-database "$HOME/.local/share/applications" || true

# The removed entry may still be the default handler for .dwg/.dxf; hand it
# to the Flatpak when that is installed, so a double click keeps working.
if flatpak info org.ingecad.IngeCAD >/dev/null 2>&1; then
    if command -v xdg-mime >/dev/null 2>&1; then
        xdg-mime default org.ingecad.IngeCAD.desktop image/vnd.dwg || true
        xdg-mime default org.ingecad.IngeCAD.desktop image/vnd.dxf || true
        echo "  .dwg / .dxf now open with the Flatpak"
    fi
fi

echo "Done. The versioned bundles under ~/.local/opt/IngeCAD-* are NOT"
echo "touched by this script — delete the ones you no longer want by hand."
