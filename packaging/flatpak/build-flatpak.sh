#!/usr/bin/env bash
# Build and install IngeCAD's Flatpak (user), optionally emitting the
# distributable single-file bundle a non-terminal user double-clicks.
#
#   packaging/flatpak/build-flatpak.sh            # build + install
#   packaging/flatpak/build-flatpak.sh --bundle   # + IngeCAD.flatpak
#
# Mirrors IngePresupuestos' script; the manifest reads the repository tree
# directly (type: dir with skips), so no staging copy is needed here.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
APPID="org.ingecad.IngeCAD"
STATE_DIR="$HERE/.flatpak-builder"
BUILD_DIR="$HERE/.staging/build"

if command -v flatpak-builder >/dev/null 2>&1; then
  BUILDER="flatpak-builder"
else
  BUILDER="flatpak run org.flatpak.Builder"
fi

echo "▶ Building with flatpak-builder…"
$BUILDER \
  --user --force-clean --install --disable-rofiles-fuse \
  --state-dir "$STATE_DIR" \
  "$BUILD_DIR" "$HERE/$APPID.yml"

if [ "${1:-}" = "--bundle" ]; then
  REPO_OSTREE="$HERE/.staging/repo"
  BUNDLE="$HERE/.staging/IngeCAD.flatpak"
  echo "▶ Exporting the distributable bundle…"
  $BUILDER --user --force-clean --disable-rofiles-fuse --repo "$REPO_OSTREE" \
    --state-dir "$STATE_DIR" "$BUILD_DIR" "$HERE/$APPID.yml"
  # --runtime-repo lets the user's GNOME Software fetch the Freedesktop
  # runtime from Flathub on its own when the bundle is double-clicked.
  flatpak build-bundle \
    --runtime-repo=https://dl.flathub.org/repo/flathub.flatpakrepo \
    "$REPO_OSTREE" "$BUNDLE" "$APPID"
  echo "✔ Bundle: $BUNDLE"
fi

echo ""
echo "✔ Installed. Run it with:  flatpak run $APPID"
