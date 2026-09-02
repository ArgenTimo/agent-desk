#!/usr/bin/env bash
#
# stop-verify.sh — Stop hook: refuse to end a turn on a broken tree.
#
# Stack-agnostic. Every command is resolved from .claude/.ai-worker/project-profile.yml, so this
# file is identical in every project ai-worker serves:
#
#   detected.ci.test_cmd          the exact command the pipeline gate runs (preferred)
#   toolchain.<lang>.test         the per-language full-suite runner (fallback)
#   toolchain.<lang>.lint         formatter / linter
#   toolchain.<lang>.typecheck    type check, where the stack has one
#
# A null entry is NEVER guessed. It degrades to an advisory line naming what is missing, so an
# unknown toolchain produces a warning rather than a false block or a silent pass.
#
# Scope:  lint (blocking) · test (blocking) · typecheck (advisory)
# Loop guard: never blocks twice in a row.
set -uo pipefail

input="$(cat 2>/dev/null || true)"

json_str() {
  local v=""
  if command -v jq >/dev/null 2>&1; then
    v="$(printf '%s' "$input" | jq -r --arg k "$1" '.[$k] // empty' 2>/dev/null || true)"
  fi
  if [ -z "$v" ]; then
    v="$(printf '%s' "$input" | sed -n "s/.*\"$1\"[[:space:]]*:[[:space:]]*\"\([^\"]*\)\".*/\1/p" | head -n1)"
  fi
  printf '%s' "$v"
}

# Bind the gates to the session's OWN worktree, not an inherited CLAUDE_PROJECT_DIR: with one
# worktree per ticket, a hook must never lint another ticket's branch.
hook_cwd="$(json_str cwd)"
root=""
[ -n "$hook_cwd" ] && [ -d "$hook_cwd" ] && root="$(cd "$hook_cwd" && git rev-parse --show-toplevel 2>/dev/null || true)"
[ -z "$root" ] && root="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
cd "$root" || exit 0

session="$(json_str session_id)"; [ -z "$session" ] && session="default"
marker="${TMPDIR:-/tmp}/aiw-stop-verify.$(printf '%s' "$session" | tr -c 'a-zA-Z0-9' '_')"
if printf '%s' "$input" | grep -q '"stop_hook_active"[[:space:]]*:[[:space:]]*true' || [ -f "$marker" ]; then
  rm -f "$marker" 2>/dev/null; exit 0
fi

# --- Profile ------------------------------------------------------------------
# Look for the profile in this worktree, then in the workspace root above it.
profile=""
for p in "$root/.claude/.ai-worker/project-profile.yml" \
         "$root/../.claude/.ai-worker/project-profile.yml" \
         "${CLAUDE_PROJECT_DIR:-}/.claude/.ai-worker/project-profile.yml"; do
  [ -f "$p" ] && profile="$p" && break
done
if [ -z "$profile" ]; then
  echo "stop-verify: no project profile found — run project-bootstrap. Gates skipped." >&2
  exit 0
fi

# Minimal YAML reader: `yq` when present, else an indentation-aware awk fallback.
# Usage: pval <dotted.path>
pval() {
  if command -v yq >/dev/null 2>&1; then
    v="$(yq -r ".$1 // \"\"" "$profile" 2>/dev/null || true)"
    [ "$v" = "null" ] && v=""
    printf '%s' "$v"; return
  fi
  printf '%s' "$1" | tr '.' '\n' > /tmp/.aiw_path.$$ 
  awk -v pathfile="/tmp/.aiw_path.$$" '
    BEGIN { n=0; while ((getline k < pathfile) > 0) { key[++n]=k } depth=1 }
    {
      line=$0
      sub(/[[:space:]]+#.*$/, "", line)
      if (line ~ /^[[:space:]]*$/) next
      match(line, /^[[:space:]]*/); ind=RLENGTH
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", line)
      split(line, kv, ":")
      k=kv[1]
      if (k == key[depth] && ind == (depth-1)*2) {
        if (depth == n) {
          v=substr(line, index(line, ":")+1)
          gsub(/^[[:space:]]+|[[:space:]]+$/, "", v)
          gsub(/^"|"$|^'"'"'|'"'"'$/, "", v)
          if (v == "null" || v == "~") v=""
          print v; exit
        }
        depth++
      }
    }
  ' "$profile"
  rm -f /tmp/.aiw_path.$$
}

langs="$(pval detected.languages)"
[ -z "$langs" ] && langs="$(pval detected.primary_language)"
langs="$(printf '%s' "$langs" | tr -d '[]"' | tr ',' ' ')"
[ -z "$langs" ] && { echo "stop-verify: no languages in the profile — gates skipped." >&2; exit 0; }

# --- What changed -------------------------------------------------------------
base="$(git merge-base HEAD origin/HEAD 2>/dev/null || git merge-base HEAD "origin/$(pval code_host.default_branch)" 2>/dev/null || echo HEAD)"
changed="$( { git diff --name-only --diff-filter=ACMR "$base"...HEAD 2>/dev/null;
              git diff --name-only --diff-filter=ACMR 2>/dev/null;
              git diff --name-only --cached --diff-filter=ACMR 2>/dev/null; } | sort -u || true)"
[ -z "$changed" ] && exit 0

# Docs-only turns are a no-op: no source file, no gate.
if ! printf '%s\n' "$changed" | grep -qvE '\.(md|txt|rst|adoc)$|^docs/'; then
  exit 0
fi

fail=""; note=""
run() { local label="$1"; shift
  local out
  if ! out="$(eval "$@" 2>&1)"; then
    fail="${fail}
--- ${label} ---
$(printf '%s' "$out" | tail -n 40)"
  fi
}

# --- Per language -------------------------------------------------------------
for lang in $langs; do
  [ -z "$lang" ] && continue
  lint="$(pval "toolchain.${lang}.lint")"
  tc="$(pval "toolchain.${lang}.typecheck")"

  if [ -n "$lint" ]; then run "lint (${lang})" "$lint"; else
    note="${note}stop-verify: toolchain.${lang}.lint is null — lint gate skipped (needs_toolchain).
"; fi

  if [ -n "$tc" ]; then
    tc_out="$(eval "$tc" 2>&1 || true)"
    printf '%s' "$tc_out" | grep -qiE '\berror\b' && note="${note}stop-verify: typecheck (${lang}) advisory:
$(printf '%s' "$tc_out" | tail -n 12)
"
  fi
done

# --- Tests: the CI gate command first ----------------------------------------
test_cmd="$(pval detected.ci.test_cmd)"
if [ -z "$test_cmd" ]; then
  for lang in $langs; do
    c="$(pval "toolchain.${lang}.test")"
    [ -n "$c" ] && run "tests (${lang})" "$c"
    [ -z "$c" ] && note="${note}stop-verify: toolchain.${lang}.test is null — test gate skipped (needs_toolchain).
"
  done
else
  run "tests (ci gate command)" "$test_cmd"
fi

[ -n "$note" ] && printf '%s' "$note" >&2

if [ -n "$fail" ]; then
  branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
  {
    echo "stop-verify: BLOCKED — the tree is red in ${root} (${branch})."
    echo "$fail"
    echo
    echo "A red gate is not a reason to summarise progress; it is the work that is left."
  } >&2
  : > "$marker"
  exit 2
fi
exit 0
