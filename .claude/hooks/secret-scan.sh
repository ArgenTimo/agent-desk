#!/usr/bin/env bash
#
# secret-scan.sh — PreToolUse hook for `git commit`.
#
# Scans the STAGED diff for credential material. Backend order: `gitleaks protect --staged` when
# installed, otherwise the patterns in .claude/security-patterns.yaml.
#
# Matches are REDACTED before printing. A hook that echoes a live token into a transcript has
# moved the credential somewhere new rather than protecting it.
set -uo pipefail

input="$(cat 2>/dev/null || true)"
cmd=""
command -v jq >/dev/null 2>&1 && cmd="$(printf '%s' "$input" | jq -r '.tool_input.command // empty' 2>/dev/null || true)"
[ -z "$cmd" ] && cmd="$(printf '%s' "$input" | sed -n 's/.*"command"[[:space:]]*:[[:space:]]*"\(.*\)".*/\1/p' | head -n1)"
printf '%s' "$cmd" | grep -Eq '(^|[;&|[:space:]])git[[:space:]]+commit' || exit 0

cwd=""; command -v jq >/dev/null 2>&1 && cwd="$(printf '%s' "$input" | jq -r '.cwd // empty' 2>/dev/null || true)"
root="$(cd "${cwd:-$PWD}" 2>/dev/null && git rev-parse --show-toplevel 2>/dev/null || true)"
[ -z "$root" ] && root="${CLAUDE_PROJECT_DIR:-$PWD}"
cd "$root" || exit 0

git diff --cached --quiet 2>/dev/null && exit 0

if command -v gitleaks >/dev/null 2>&1; then
  if ! out="$(gitleaks protect --staged --redact --no-banner 2>&1)"; then
    {
      echo "secret-scan: BLOCKED — gitleaks found credential material in the staged diff."
      printf '%s\n' "$out" | tail -n 30
      echo
      echo "If this is a deliberate fixture, give it an obviously fake shape and record it under"
      echo "'Known false positives' in .claude/security-guidance.md."
      echo "If it was ever a real value: removing it is not enough. Rotate it."
    } >&2
    exit 2
  fi
  exit 0
fi

patterns_file="${root}/.claude/security-patterns.yaml"
[ -f "$patterns_file" ] || patterns_file="${CLAUDE_PROJECT_DIR:-$root}/.claude/security-patterns.yaml"
[ -f "$patterns_file" ] || exit 0

pats="$(awk '
  /^  (hardcoded_secrets|credential_leak_paths):/ {inblock=1; next}
  /^  [a-z_]+:/ {inblock=0}
  inblock && /^      - / {
    line=$0; sub(/^      - /, "", line); sub(/[[:space:]]+#.*$/, "", line)
    gsub(/^'"'"'|'"'"'$/, "", line)
    if (length(line) > 3) print line
  }' "$patterns_file")"
[ -z "$pats" ] && exit 0

staged="$(git diff --cached -U0 | grep '^+' | grep -v '^+++' || true)"
[ -z "$staged" ] && exit 0

hits=""
while IFS= read -r p; do
  [ -z "$p" ] && continue
  m="$(printf '%s' "$staged" | grep -Eno -- "$p" 2>/dev/null | head -n 3 || true)"
  if [ -n "$m" ]; then
    redacted="$(printf '%s' "$m" | sed -E 's/(:.{0,6}).*/\1…[redacted]/')"
    hits="${hits}  - ${p}
$(printf '%s' "$redacted" | sed 's/^/      /')
"
  fi
done <<< "$pats"

if [ -n "$hits" ]; then
  {
    echo "secret-scan: BLOCKED — the staged diff matches credential patterns:"
    printf '%s' "$hits"
    echo
    echo "Matches are redacted on purpose. Unstage, remove the value, and rotate it if it was real."
  } >&2
  exit 2
fi
exit 0
