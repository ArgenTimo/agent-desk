#!/usr/bin/env bash
#
# pr-create-guard.sh — PreToolUse hook for `gh pr create` and `glab mr create`.
#
#   1. Draft is mandatory (`--draft` on gh, `--draft` on glab). A non-draft pull request means a
#      full pipeline run on every intermediate commit — the client's money, spent by us.
#   2. GitLab only: `--remove-source-branch` must be present and not set to a falsey value, when
#      the project's convention says so (delivery.remove_source_branch in the profile; default on).
#   3. Advisory: an empty body. A reviewer reads the description before the diff.
set -uo pipefail

input="$(cat 2>/dev/null || true)"
cmd=""
command -v jq >/dev/null 2>&1 && cmd="$(printf '%s' "$input" | jq -r '.tool_input.command // empty' 2>/dev/null || true)"
[ -z "$cmd" ] && cmd="$(printf '%s' "$input" | sed -n 's/.*"command"[[:space:]]*:[[:space:]]*"\(.*\)".*/\1/p' | head -n1)"

is_gh=0; is_glab=0
printf '%s' "$cmd" | grep -Eq '(^|[;&|[:space:]])gh[[:space:]]+pr[[:space:]]+create'   && is_gh=1
printf '%s' "$cmd" | grep -Eq '(^|[;&|[:space:]])glab[[:space:]]+mr[[:space:]]+create' && is_glab=1
[ "$is_gh" = "0" ] && [ "$is_glab" = "0" ] && exit 0

if ! printf '%s' "$cmd" | grep -q -- '--draft'; then
  {
    echo "pr-create-guard: BLOCKED — created without --draft."
    echo "Draft-first keeps the expensive pipeline to one run per iteration; the draft flag comes"
    echo "off once, after verification."
    [ "$is_gh" = "1" ]   && echo "    gh pr create --draft ...   # then: gh pr ready <n>"
    [ "$is_glab" = "1" ] && echo "    glab mr create --draft ... # then: glab mr update <n> --ready"
  } >&2
  exit 2
fi

if [ "$is_glab" = "1" ]; then
  want_remove=1
  for p in "${CLAUDE_PROJECT_DIR:-$PWD}/.claude/.ai-worker/project-profile.yml"; do
    [ -f "$p" ] && grep -qE 'remove_source_branch:[[:space:]]*(false|no|off)' "$p" && want_remove=0
  done
  if [ "$want_remove" = "1" ]; then
    if ! printf '%s' "$cmd" | grep -q -- '--remove-source-branch'; then
      {
        echo "pr-create-guard: BLOCKED — 'glab mr create' without --remove-source-branch."
        echo "Project convention: source branches are deleted on merge. Add the flag, or set"
        echo "delivery.remove_source_branch: false in the project profile if this project differs."
      } >&2
      exit 2
    fi
    if printf '%s' "$cmd" | grep -Eq -- '--remove-source-branch[= ](false|0|f|no|FALSE)'; then
      echo "pr-create-guard: BLOCKED — --remove-source-branch is present but disabled." >&2
      exit 2
    fi
  fi
fi

if printf '%s' "$cmd" | grep -Eq -- '--body[[:space:]]+["'"'"']{0,2}([[:space:]]|$)'; then
  echo "pr-create-guard (advisory): the description looks empty. A reviewer reads it before the diff." >&2
fi
exit 0
