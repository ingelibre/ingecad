#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Publish the signed OSTree repo to R2 from this machine, through wrangler's
# OAuth login (no S3 keys). This is the stopgap while the R2_* secrets that
# .github/workflows/publish-flatpak.yml wants do not exist; the moment they
# do, that workflow takes over and this script stays only as a fallback.
#
#   packaging/flatpak/publish-r2-wrangler.sh            # upload what changed
#   packaging/flatpak/publish-r2-wrangler.sh --dry-run  # list it instead
#
# Incremental on purpose. OSTree objects are content-addressed, so a release
# adds objects and rewrites only the metadata at the root; the ~8000
# unchanged ones must not be pushed again over a home connection.
# `.staging/published.tsv` records path+size of everything R2 already holds
# and is extended only with files this run really uploaded, so an interrupted
# run resumes instead of silently skipping.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$HERE/.staging/repo"
MANIFEST="$HERE/.staging/published.tsv"
BUCKET="ingecad-downloads"
PREFIX="flatpak/repo"
JOBS="${JOBS:-6}"
TAB=$'\t'

[ -d "$REPO" ]     || { echo "!! no repo at $REPO — build it first" >&2; exit 1; }
[ -f "$MANIFEST" ] || { echo "!! no $MANIFEST — refusing to guess what R2 holds" >&2; exit 1; }

work=$(mktemp -d); trap 'rm -rf "$work"' EXIT
cd "$REPO"
# .lock is ostree's own local lock and has no business in a served repo.
find . -type f ! -name '.lock' -printf '%P\t%s\n' | LC_ALL=C sort > "$work/current"

# Only the content-addressed part of the repo may be diffed by path+size:
# there, a name change IS a content change. The metadata is the opposite and
# the trap is silent — a re-signed summary.sig is 142 bytes both times, and a
# ref file is a 64-character commit hash both times, so "same size" would
# leave R2 serving the old signature over the new summary. Those always go.
LC_ALL=C comm -23 "$work/current" "$MANIFEST" | cut -f1 > "$work/changed"
grep -E '^(summary|refs/|config$|summaries/|delta-indexes/)' \
    <(cut -f1 "$work/current") > "$work/always" || true
cat "$work/changed" "$work/always" | LC_ALL=C sort -u > "$work/todo"

n=$(wc -l < "$work/todo")
echo "▶ $(wc -l < "$work/current") files in the repo, $n to upload" \
     "($(wc -l < "$work/changed") new or changed," \
     "$(wc -l < "$work/always") metadata always re-sent)"
if [ "${1:-}" = "--dry-run" ]; then sed 's/^/    /' "$work/todo"; exit 0; fi
[ "$n" -gt 0 ] || { echo "✔ nothing to publish"; exit 0; }

upload_one() {
    key="$1"
    # ostree objects are immutable and safe to cache forever; the metadata at
    # the root is what announces a new commit and must never be served stale.
    case "$key" in
        summary*|refs/*|config|summaries/*) cc="no-cache, max-age=0" ;;
        *)                                  cc="public, max-age=31536000, immutable" ;;
    esac
    if npx --yes wrangler r2 object put "$BUCKET/$PREFIX/$key" \
           --file "$key" --remote --cache-control "$cc" >/dev/null 2>&1; then
        echo "$key"
    else
        echo "!! FAILED $key" >&2
    fi
}
export -f upload_one; export BUCKET PREFIX

# The summary names the new commit, so it goes last: a client that reads it
# must already be able to find every object it points at.
grep -v '^summary' "$work/todo" > "$work/objects" || true
grep    '^summary' "$work/todo" > "$work/summary" || true

if [ -s "$work/objects" ]; then
    echo "▶ uploading $(wc -l < "$work/objects") objects, $JOBS at a time…"
    xargs -P "$JOBS" -I{} bash -c 'upload_one "$@"' _ {} < "$work/objects" > "$work/done"
fi
if [ -s "$work/summary" ]; then
    echo "▶ uploading the summary last…"
    while read -r k; do upload_one "$k"; done < "$work/summary" >> "$work/done"
fi

# Extend the manifest with exactly the files that landed.
LC_ALL=C sort -u "$work/done" > "$work/landed"
LC_ALL=C awk -F'\t' 'NR==FNR{ok[$0];next} $1 in ok' "$work/landed" "$work/current" \
    > "$work/entries"
cat "$MANIFEST" "$work/entries" | LC_ALL=C sort -u > "$work/manifest"
mv "$work/manifest" "$MANIFEST"

failed=$(( n - $(wc -l < "$work/landed") ))
[ "$failed" -eq 0 ] || { echo "!! $failed file(s) failed — re-run to finish" >&2; exit 1; }
echo "✔ published; R2 now holds $(wc -l < "$MANIFEST") files at downloads.ingecad.org/flatpak/repo/"
