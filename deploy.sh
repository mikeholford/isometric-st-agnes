#!/usr/bin/env bash
# Publish site/ to GitHub Pages: one fresh commit on the gh-pages branch, force-pushed,
# so the tile pyramid never piles up in the repository history.
set -euo pipefail
builtin cd "$(dirname "$0")"
[ -f site/index.html ] || { echo "site/ is empty: run ./build.sh first" >&2; exit 1; }
cp viewer/index.html site/index.html

remote=$(git remote get-url origin)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
cp -r site/. "$tmp"
git -C "$tmp" init -q -b gh-pages
git -C "$tmp" add -A
git -C "$tmp" -c user.name="$(git config user.name)" -c user.email="$(git config user.email)" \
  commit -q -m "Publish map ($(git rev-parse --short HEAD))"
git -C "$tmp" -c http.postBuffer=524288000 push -q -f "$remote" gh-pages  # one request for the whole pyramid: the default buffer makes GitHub drop it
sha=$(git -C "$tmp" rev-parse HEAD)
echo "Pushed $(find site -type f | wc -l) files to gh-pages"

# Wait for GitHub Pages to build exactly this commit; its builds sometimes fail for no stated reason,
# so ask for one more build before giving up.
repo=$(echo "$remote" | sed -E 's#(git@github.com:|https://github.com/)##; s#\.git$##')
for attempt in 1 2; do
  for _ in $(seq 60); do
    read -r status commit < <(gh api "repos/$repo/pages/builds/latest" --jq '.status + " " + .commit' 2>/dev/null || echo "unknown -")
    [ "$commit" = "$sha" ] && { [ "$status" = built ] || [ "$status" = errored ]; } && break
    sleep 10
  done
  if [ "$commit" = "$sha" ] && [ "$status" = built ]; then
    echo "GitHub Pages is live"
    exit 0
  fi
  echo "GitHub Pages build: $status, requesting another build" >&2
  gh api -X POST "repos/$repo/pages/builds" >/dev/null
  sleep 20
done
echo "GitHub Pages did not build $sha" >&2
exit 1
