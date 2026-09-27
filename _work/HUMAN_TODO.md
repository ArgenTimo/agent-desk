# For a human

Ordered by importance. Each item: what, why, exact commands, which task it depends on.

## H1 · Stop hook: keep it on (depends on A1 — done)
The research recommended switching `stop-verify.sh` off until the suite was hermetic. It is on in
`.claude/settings.json` and nothing in `~/.claude/settings.json` disables it. After A1 (#14) a
`make gate` starts no `claude` and never opens `~/.local/share/agent-desk/` (verified: 0 calls
from a fake `claude`, live DB mtime unchanged). If you turned it off anywhere in your own
environment, turn it back on; there is nothing to change in the repository.

## H2 · Remove 200 junk background jobs (task 3; blocked on the Claude background service)
`claude rm <id>` answers "couldn't remove … the background service may be restarting": the
daemon's supervisor (pid in `~/.claude/daemon.status.json`) is dead since 2026-09-16 and nothing
restarts it. The plan allows this agent only `claude agents --json`, `claude rm`, `claude stop`,
so starting the service is yours.

Classified from `~/.claude/jobs/<id>/state.json` `.intent` (snapshot of all 206 agents and a full
copy of `~/.claude/jobs` are in `~/agent-desk-salvage/`, classification in `classify.tsv` there):
- **199** start with "бери в работу" — made by the un-hermetic test suite (fixed by A1);
- **1** explore job (d289dc12, "Nothing is queued for agent-desk…");
- 196 of the 200 have no worktree; 4 have `.claude/worktrees/beri-v-rabotu`, which `rm` will
  try to remove (it has an untracked `uv.lock`, already salvaged, and a nested worktree
  `do-carries-bench` whose branch is merged) — git refuses a dirty worktree, so expect those four
  to report a worktree it could not remove; that is fine.

Steps:
1. Start the background service — open `claude agents` in a terminal (the agent view starts it),
   or any `claude --bg` session; then quit it.
2. `bash _work/proposed/rm-test-jobs.sh` — prints `removed N, failed M` and the blocked count
   left (expected: 3).
3. The remaining 3 are yours to decide:
   - `e4e08187` — "Пройди по таблице Jira, собери … блокеры" (worktree `mozhesh-sobrat-iz-jira-…`);
     needs: `gh pr create --draft` after `gh auth login`.
   - `4496acc6` — "эта идея относиться к текущему проекту…" (worktree `eta-ideya-…`), needs the same.
   - `dbdc64e2` — "do a thing" (worktree `probe`), asks what to work on. Almost certainly junk.
   `claude rm <id>` each, or `claude attach <id>` to finish one.
No job is `running`/`working` today (all 203 background entries are `blocked`).

## H0 · `.claude/settings.json` is not strict JSON (most important)
The Stop hook is commented out with `//`. JSON has no comments; Claude Code evidently tolerated it
(merges went through after your edit), but any other reader (`jq`, the hooks' own parsing, a
future CLI) fails on it. Delete the `"Stop": [ … ]` entry instead of commenting it, and commit the
file — while it is only an uncommitted change in the working tree, any branch switch that resets
the tree loses it (it happened once in this session and you restored it).

## H3 · Delete stale local branches and the salvaged stash (U1)
The auto-mode classifier refused this as irreversible; everything is in the bundles in
`~/agent-desk-salvage/`, so it is safe:
```
KEEP='^(main|backup/.*|carries-the-bench|dispatch-names-the-session|session-dispatch-context|dispatch-own-worktree|worktree-beri-v-rabotu)$'
for R in ~/PycharmProjects/agent-desk ~/side-projects/agent-desk; do
  git -C $R fetch --prune origin
  git -C $R for-each-ref --format='%(refname:short)' refs/heads | grep -Ev "$KEEP" | xargs -r git -C $R branch -D
done
git -C ~/PycharmProjects/agent-desk stash drop      # = ~/agent-desk-salvage/stash-card-changed-at.patch
```
Optionally on origin: archive-tag then delete `worktree-eta-ideya-…` and `worktree-mozhesh-…`
(`git tag archive/<name> origin/<name> && git push origin archive/<name> && git push origin --delete <name>`),
and delete merged `experiment/insurance-site`, `ideas-from-the-pool`, `worktree-looking-for-something-…`.
