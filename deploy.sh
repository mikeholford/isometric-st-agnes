#!/usr/bin/env bash
# Publish site/ to GitHub Pages: one fresh commit on the gh-pages branch, force-pushed,
# so the tile pyramid never piles up in the repository history. It is sent in parts, see below.
set -euo pipefail
builtin cd "$(dirname "$0")"
[ -f site/index.html ] || { echo "site/ is empty: run ./build.sh first" >&2; exit 1; }
cp viewer/index.html site/index.html

remote=$(git remote get-url origin)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
cp -r site/. "$tmp"
# The site is too heavy to send in one go on a slow line: GitHub gives up after a couple of minutes. So it goes up
# in parts, each a commit on a branch nobody reads. Then the one fresh commit of the whole site is made: everything
# in it is already there, so that push is small, and it becomes gh-pages.
me=(-c user.name="$(git config user.name)" -c user.email="$(git config user.email)")
send() {  # a push that is dropped is tried again: what did arrive does not have to go up twice
  for attempt in 1 2 3 4 5; do
    git -C "$tmp" -c http.postBuffer=524288000 push -q -f "$remote" "$1" 2>/dev/null && return 0
    echo "the push of $1 was dropped, trying again ($attempt)" >&2
    sleep 5
  done
  return 1
}
git -C "$tmp" init -q -b gh-pages-upload
waiting=0
while IFS= read -r path; do
  git -C "$tmp" add -- "$path"
  waiting=$((waiting + $(du -sk "$tmp/$path" | cut -f1)))
  if [ "$waiting" -gt 25000 ]; then
    git -C "$tmp" "${me[@]}" commit -q -m "A part of the site, on its way up"
    send gh-pages-upload
    echo "sent $((waiting / 1000)) MB"
    waiting=0
  fi
done < <(builtin cd "$tmp" && { find . -mindepth 2 -maxdepth 2 -not -path './.git/*'; find . -mindepth 1 -maxdepth 1 -type f; } | sed 's|^\./||' | sort)
git -C "$tmp" checkout -q --orphan gh-pages
git -C "$tmp" add -A
git -C "$tmp" "${me[@]}" commit -q -m "Publish map ($(git rev-parse --short HEAD))"
send gh-pages
git -C "$tmp" push -q "$remote" :gh-pages-upload 2>/dev/null || true
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
