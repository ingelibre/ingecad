#!/usr/bin/env bash
# Build and install IngeCAD's Flatpak (user), optionally emitting the
# distributable single-file bundle a non-terminal user double-clicks.
#
#   packaging/flatpak/build-flatpak.sh            # build + install
#   packaging/flatpak/build-flatpak.sh --bundle   # + IngeCAD.flatpak
#   packaging/flatpak/build-flatpak.sh --repo     # into the signed OSTree repo
#
# --repo is the publishing build: it commits into .staging/repo signed with
# the release key, then refreshes the summary, so that
# publish-r2-wrangler.sh has something to upload. Note that it does NOT
# install: a build installed straight from the builder gets a local origin
# ("ingecad1-origin"), and an install that no longer points at
# downloads.ingecad.org will never see another update.
#
# Mirrors IngePresupuestos' script; the manifest reads the repository tree
# directly (type: dir with skips), so no staging copy is needed here.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
APPID="org.ingecad.IngeCAD"
STATE_DIR="$HERE/.flatpak-builder"
BUILD_DIR="$HERE/.staging/build"

# flatpak-builder is usually NOT installed natively here — it is the
# org.flatpak.Builder Flatpak. Calling `flatpak-builder` directly therefore
# fails with "command not found", and a caller that only checks the exit
# code of a pipeline can read that as a successful build of nothing.
if command -v flatpak-builder >/dev/null 2>&1; then
  BUILDER="flatpak-builder"
else
  BUILDER="flatpak run org.flatpak.Builder"
fi

# The release signing key (backup and notes in ~/Documentos/claves-gpg-ingecad).
GPG_FPR="${GPG_FPR:-0D364E74CE6C0A577D1E0A680E252045461C416E}"
REPO_OSTREE="$HERE/.staging/repo"

if [ "${1:-}" = "--repo" ]; then
  gpg --list-secret-keys "$GPG_FPR" >/dev/null 2>&1 || {
    echo "!! the signing key $GPG_FPR is not in the keyring." >&2
    echo "   gpg --import ~/Documentos/claves-gpg-ingecad/flatpak-signing-private.asc" >&2
    exit 1
  }
  # --force-clean does NOT rescue a build directory a previous --install run
  # left finalized: the build repeats in full and only then dies with
  # "already finalized", after the commit it was supposed to make.
  rm -rf "$BUILD_DIR"
  echo "▶ Building into the signed repo…"
  $BUILDER --user --force-clean --disable-rofiles-fuse \
    --repo "$REPO_OSTREE" --gpg-sign="$GPG_FPR" \
    --state-dir "$STATE_DIR" "$BUILD_DIR" "$HERE/$APPID.yml"
  echo "▶ Refreshing the summary…"
  flatpak build-update-repo --generate-static-deltas --prune --prune-depth=3 \
    --gpg-sign="$GPG_FPR" "$REPO_OSTREE"
  echo ""
  echo "✔ Committed. Publish it with:  $HERE/publish-r2-wrangler.sh"
  exit 0
fi

echo "▶ Building with flatpak-builder…"
$BUILDER \
  --user --force-clean --install --disable-rofiles-fuse \
  --state-dir "$STATE_DIR" \
  "$BUILD_DIR" "$HERE/$APPID.yml"

if [ "${1:-}" = "--bundle" ]; then
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
