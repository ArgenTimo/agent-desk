#!/usr/bin/env bash
#
# check-doc-links.sh — every relative link in README.md, CLAUDE.md, docs/ and design/ resolves.
#
# Cheap, and it catches a class of breakage no test suite can see: a document that points at a
# file somebody renamed still reads perfectly and is simply wrong. The documents are the
# specification here (docs/README.md), so a dangling link is a defect in the specification.
#
# Only relative links are checked. http(s) and anchors are left alone.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

fail=0
checked=0

while IFS= read -r src; do
  dir="$(dirname "$src")"
  # Markdown inline links: ](target)
  grep -o '](\([^)]*\))' "$src" 2>/dev/null | sed 's/^](//; s/)$//' | while IFS= read -r target; do
    case "$target" in
      http://*|https://*|mailto:*|'#'*|'') continue ;;
    esac
    path="${target%%#*}"
    [ -z "$path" ] && continue
    if [ ! -e "$dir/$path" ]; then
      echo "  ✗ $src → $target"
      echo x >> /tmp/.adlinks.$$
    fi
  done
  checked=$((checked + 1))
  # A file git ignores is somebody's own notebook, not part of the specification. Checking it
  # fails the gate over a link in a document nobody but its author will ever open.
done < <(find . -name '*.md' -not -path './.git/*' -not -path './.claude/*' \
  -exec sh -c 'git check-ignore -q "$1" || echo "$1"' _ {} \; | sort)

if [ -f /tmp/.adlinks.$$ ]; then
  fail="$(wc -l < /tmp/.adlinks.$$ | tr -d ' ')"
  rm -f /tmp/.adlinks.$$
fi

if [ "$fail" != 0 ]; then
  echo "check-links: $fail broken link(s)"
  exit 1
fi
echo "check-links: ok ($checked files)"
