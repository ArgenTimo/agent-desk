#!/usr/bin/env bash
#
# pre-push-guard.sh — PreToolUse hook for `git push`.
#
#   1. never push to the default branch
#   2. never force-push
#   3. never push a branch that is BEHIND its own remote — the phantom revert: the push silently
#      undoes commits somebody else already landed
#
# Worktree-aware: the checks read the branch and HEAD of the repository actually being pushed
# (`cd <wt> && git push`, `git -C <wt> push`), not the session's cwd. A false block teaches an
# agent to obfuscate the push command to evade the matcher, which is worse than no hook.
set -uo pipefail

input="$(cat 2>/dev/null || true)"
cmd=""
command -v jq >/dev/null 2>&1 && cmd="$(printf '%s' "$input" | jq -r '.tool_input.command // empty' 2>/dev/null || true)"
[ -z "$cmd" ] && cmd="$(printf '%s' "$input" | sed -n 's/.*"command"[[:space:]]*:[[:space:]]*"\(.*\)".*/\1/p' | head -n1)"
printf '%s' "$cmd" | grep -Eq '(^|[;&|[:space:]])git[[:space:]]+(-C[[:space:]]+[^[:space:]]+[[:space:]]+)?push' || exit 0

hook_cwd=""; command -v jq >/dev/null 2>&1 && hook_cwd="$(printf '%s' "$input" | jq -r '.cwd // empty' 2>/dev/null || true)"
target="${hook_cwd:-$PWD}"
cd_hint="$(printf '%s' "$cmd" | sed -n 's/.*\bcd[[:space:]]\+\([^[:space:];&|]*\).*/\1/p' | tail -n1)"
c_hint="$(printf '%s' "$cmd" | sed -n 's/.*git[[:space:]]\+-C[[:space:]]\+\([^[:space:]]*\).*/\1/p' | head -n1)"
for hint in "$c_hint" "$cd_hint"; do
  [ -z "$hint" ] && continue
  case "$hint" in /*) cand="$hint" ;; *) cand="${target}/${hint}" ;; esac
  [ -d "$cand" ] && target="$cand"
done

root="$(cd "$target" 2>/dev/null && git rev-parse --show-toplevel 2>/dev/null || true)"
[ -z "$root" ] && { echo "pre-push-guard: could not resolve a worktree; not blocking." >&2; exit 0; }
cd "$root" || exit 0

branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '')"
default="$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##')"
[ -z "$default" ] && default="$(git config --get init.defaultBranch 2>/dev/null || echo main)"

block() { { echo "pre-push-guard: BLOCKED — $1"; shift; [ $# -gt 0 ] && printf '%s\n' "$@"; } >&2; exit 2; }

if [ "$branch" = "$default" ] || printf '%s' "$cmd" | grep -Eq "[[:space:]]${default}(:|[[:space:]]|$)"; then
  block "a push to '${default}'." \
        "The default branch is reached through a reviewed pull request. Always." \
        "Create a task branch, open a draft PR, and let a human merge it."
fi

if printf '%s' "$cmd" | grep -Eq '(--force([^-]|$)|--force-with-lease|[[:space:]]-f([[:space:]]|$))'; then
  block "a force-push." \
        "It destroys the history a review was based on, and silently invalidates the revision" \
        "an approval was bound to."
fi

upstream="$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || true)"
if [ -n "$upstream" ]; then
  git fetch --quiet "$(printf '%s' "$upstream" | cut -d/ -f1)" "$branch" 2>/dev/null || true
  behind="$(git rev-list --count "HEAD..${upstream}" 2>/dev/null || echo 0)"
  if [ "${behind:-0}" -gt 0 ]; then
    block "'${branch}' is ${behind} commit(s) behind ${upstream}." \
          "Pushing now would drop work that is already there." \
          "    git -C ${root} pull --rebase"
  fi
fi
exit 0
