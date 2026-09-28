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

## H4 · The working console is now a service (FYI)
`http://127.0.0.1:8787` is served by `systemctl --user … agent-desk` from `~/opt/agent-desk-prod`
(tag `desk-20260927`). Don't `make run PROD=1` beside it — the A3 lock refuses a second console.
Update: `git tag desk-YYYYMMDD origin/main && git push origin desk-YYYYMMDD && make prod-update TAG=desk-YYYYMMDD`.
Hands or appraise on: `systemctl --user edit agent-desk` → `[Service]` `Environment=AGENT_DESK_HANDS=on`.

## H5 · Re-record `tests/fixtures/stream_json.jsonl` at the current CLI (B2)
It is the stdout of a real `claude -p`, which this work may not run. It stays labelled 2.1.259.
```
claude -p "say hi" --output-format stream-json --verbose > /tmp/stream.jsonl
```
then scrub text and ids as `tests/fixtures/README.md` says, replace the fixture, and set its row in
the README table to the version in its `system` line (`test_fixtures.py` checks the two agree).

## H6 · Decide what the registry's new `waitingFor` means (found in B2)
At 2.1.283 one live `~/.claude/sessions/<pid>.json` carried a `waitingFor` string. If the CLI now
writes "waiting for a human" into the registry, that is the fact rule five says the board cannot
have today — but `docs/03-session-observation.md` requires a human to confirm a meaning before the
reader acts on it. Look at a few values (`jq .waitingFor ~/.claude/sessions/*.json`) and, if it is
that fact, say so in docs/03; reading it is then a small observe/ change with a recorded fixture.
Evidence since (B7): `claude agents --json` printed `"status": "waiting", "waitingFor": "permission
prompt"` for a session that was sitting at a permission prompt. It is recorded in
`tests/fixtures/claude_agents.json`, parsed as `Agent.waiting_for`, and deliberately not rendered.

## H7 · Open pull requests on the board need a read-only token (B3)
The line "PR · repo: N open, oldest X days" is read from GitHub with a token this work may not
hold. Create a fine-grained PAT with **read-only** access (Metadata: read, Pull requests: read)
to `ArgenTimo/agent-desk` and `bagorbenko/DuckyFlow` (the latter needs the org/owner to allow it;
a classic token with `repo` scope also works but is broader), then:
```
systemctl --user edit agent-desk
#   [Service]
#   Environment=AGENT_DESK_PULL_REPOS=ArgenTimo/agent-desk,bagorbenko/DuckyFlow
#   Environment=AGENT_DESK_GITHUB_TOKEN=<the token>
systemctl --user restart agent-desk
```
Expected on the board (2026-09-27): `PR · ArgenTimo/agent-desk: 5 open, oldest 17 days` and
`PR · bagorbenko/DuckyFlow: 1 open, oldest 20 days` (checked against `gh pr list`). Without the
token each repository says why it could not be read, which is also a correct board.

## H8 · Approve the agent-desk MCP server, and add it to ai-worker (B5)
This repository now has `.mcp.json`: the installed copy (`~/opt/agent-desk-prod`, A2) offering
`keep_idea`, `open_ideas`, `ask`, `answer` — nothing that starts work. Claude Code asks once
before it trusts a project's MCP server: accept "agent-desk" the next time a session opens here
(or `claude mcp list` to see it). A session can then write an idea into the inbox without anybody
opening the console.

For the ai-worker repository, the same file at its root (this work does not write there):
```json
{
  "mcpServers": {
    "agent-desk": {
      "command": "${HOME}/opt/agent-desk-prod/.venv/bin/python",
      "args": ["-m", "agent_desk.mcp"],
      "env": { "AGENT_DESK_MCP_TOOLS": "keep_idea,open_ideas,ask,answer" }
    }
  }
}
```
Caveat: it must not reach ai-worker's own runtime containers or its `aiw` user — the server opens
`~/.local/share/agent-desk` of whoever runs it. For interactive sessions on this laptop only.
