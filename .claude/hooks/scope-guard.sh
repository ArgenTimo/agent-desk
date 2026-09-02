#!/usr/bin/env bash
#
# scope-guard.sh — PreToolUse hook for Edit / Write / MultiEdit.
#
# Two rules, both about where a write may land:
#
#   1. Protected paths are never written: CI configuration, .git/config, .env*, the Claude
#      settings file, and the hooks themselves. A guard that can rewrite its own rules is not a
#      guard. CI config is writable ONLY when the session is a ci-bootstrap run, which the
#      orchestrator signals with AI_WORKER_MODE=ci-bootstrap.
#   2. A write must land inside the current worktree. The `deny` globs in settings.json cover the
#      common spellings; this hook resolves the actual path, which is what a symlink or a `../`
#      escape defeats.
#
# Extra protected paths per project come from .claude/.ai-worker/protected-paths.txt (one glob
# per line) — written by project-bootstrap from the console configuration.
set -uo pipefail

input="$(cat 2>/dev/null || true)"

field() {
  local v=""
  if command -v jq >/dev/null 2>&1; then
    v="$(printf '%s' "$input" | jq -r "$1 // empty" 2>/dev/null || true)"
  fi
  printf '%s' "$v"
}

target="$(field '.tool_input.file_path')"
[ -z "$target" ] && target="$(field '.tool_input.path')"
[ -z "$target" ] && exit 0

cwd="$(field '.cwd')"; [ -z "$cwd" ] && cwd="$PWD"
case "$target" in
  /*) abs="$target" ;;
  *)  abs="${cwd%/}/${target}" ;;
esac
# Normalise without requiring the file to exist.
abs="$(cd "$(dirname "$abs")" 2>/dev/null && printf '%s/%s' "$(pwd -P)" "$(basename "$abs")" || printf '%s' "$abs")"

root="$(cd "$cwd" 2>/dev/null && git rev-parse --show-toplevel 2>/dev/null || true)"
[ -z "$root" ] && root="${CLAUDE_PROJECT_DIR:-$cwd}"
root="$(cd "$root" 2>/dev/null && pwd -P || printf '%s' "$root")"

rel="${abs#"$root"/}"

block() { { echo "scope-guard: BLOCKED — $1"; shift; [ $# -gt 0 ] && printf '%s\n' "$@"; } >&2; exit 2; }

# --- 2. inside the worktree ---------------------------------------------------
case "$abs" in
  "$root"/*) : ;;
  *) block "a write outside the worktree: ${abs}" \
           "The worktree is ${root}. Work stays inside the branch this task owns." ;;
esac

# --- 1. protected paths -------------------------------------------------------
mode="${AI_WORKER_MODE:-}"
protected_ci=0
case "$rel" in
  .github/workflows/*|.gitlab-ci.yml|.circleci/*|azure-pipelines.yml|Jenkinsfile|.woodpecker/*|.drone.yml)
    protected_ci=1 ;;
esac
if [ "$protected_ci" = "1" ] && [ "$mode" != "ci-bootstrap" ]; then
  block "a write to CI configuration (${rel})." \
        "Changing the pipeline changes what 'verified' means. CI edits happen only in" \
        "ci-bootstrap mode, where the whole diff is checked to contain nothing else."
fi

case "$rel" in
  .git/config|.git/hooks/*|.env|.env.*|*/.env|*/.env.*|\
  .claude/settings.json|.claude/settings.local.json|.claude/hooks/*)
    block "a write to a protected path (${rel})." \
          "See .claude/settings.README.md for why this one is protected." ;;
esac

# --- per-project additions ----------------------------------------------------
extra="${root}/.claude/.ai-worker/protected-paths.txt"
[ -f "$extra" ] || extra="${CLAUDE_PROJECT_DIR:-$root}/.claude/.ai-worker/protected-paths.txt"
if [ -f "$extra" ]; then
  while IFS= read -r glob; do
    case "$glob" in ''|\#*) continue ;; esac
    # shellcheck disable=SC2254
    case "$rel" in
      $glob) block "a write to a project-protected path (${rel})." \
                   "Listed in .claude/.ai-worker/protected-paths.txt." ;;
    esac
  done < "$extra"
fi
exit 0
