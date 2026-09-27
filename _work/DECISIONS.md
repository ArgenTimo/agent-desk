# Decisions taken instead of asking

## D1 · Backup branch is local only
The state before this work (local `main` 75176e3 + untracked `_diagnostics/`, `_research/`,
`_research.zip`) is commit ce3f286 on local branch `backup/2026-09-27-before-autonomy`, created
through a temporary index so the working tree was not touched. It is not pushed:
`ArgenTimo/agent-desk` is public and the research notes carry aggregates of the live database.
Full `git bundle --all` of both checkouts is in `~/agent-desk-salvage/`.
Undo: `git branch -D backup/2026-09-27-before-autonomy`.

## D2 · Which checkout is which
`~/side-projects/agent-desk` (where this work runs) is a `cp -r` of `~/PycharmProjects/agent-desk`
made on 2026-09-27: two separate `.git` directories. Every worktree's `.git` file points at
`~/PycharmProjects/agent-desk/.git`, so worktree and local-branch cleanup (U1) is done against
that repository; code work, branches and PRs go through this one. Both push to the same origin.

## D3 · The plan overrides CLAUDE.md where they disagree (owner confirmed 2026-09-27)
One checkout instead of one worktree per task; PRs are merged (squash) by the agent after a green
isolated gate and a full read of the diff, instead of being left in draft for a human.

## D4 · A1 goes through PR #14 itself
Instead of a new branch, `main` was merged into #14's branch (no force-push) and the A1 work was
added on top, so #14 is the PR that lands A1.

## D5 · PR triage in U1 (closed without merging)
#15 (dup of #16), #8 (patch-identical to #7), #21 (split across #14/#18/#19/#20), #3 (stale
workbench work, frozen), #17 (in favour of #16: a stored `changed_at` is a fact), #12 and #11
(land fixes; land is removed in S1). Branches stay on origin. Undo: `gh pr reopen N`.

## D6 · Worktrees removed
All worktrees of `~/PycharmProjects/agent-desk` except the main checkout and the two inside
`~/.claude/jobs/*/tmp` (removing those writes into `~/.claude`; they go with `claude rm`).
`git worktree remove` keeps branches; the four dirty ones were force-removed after their changes
were saved in `~/agent-desk-salvage/` (U0). Worktrees that three kept jobs pointed at
(`eta-ideya-…`, `mozhesh-…`, `probe`) were clean and are gone; their branches remain — recreate
with `git worktree add .claude/worktrees/<name> <branch>` before `claude attach`.

## D7 · schema_version gets a name, filled by number for old rows
`store/migrate.py` adds `schema_version.name`. Rows recorded before it existed are named from the
files by number — the same trust the old runner gave them. The live database, where that trust
is wrong (66, 78, 79), is reconciled first by `scripts/reconcile-schema-version.py`, which only
rewrites `schema_version` and refuses unless the rest of the schema equals a fresh build.

## D8 · Live database reconciled (A4), 2026-09-27
`scripts/reconcile-schema-version.py ~/.local/share/agent-desk/agent-desk.db` after it ran clean on
a copy: added `schema_version.name`, deleted row 66 (no file in any ref, no trace in the schema),
named 78 `078-a-thing-drawn-from-the-project.sql` and 79 `079-when-a-card-last-changed.sql`
(#16, merged as 079). The rest of the schema equals a fresh build of `main`. Backup taken first
with the sqlite backup API; a restored copy matched the live one table for table.
Undo (console stopped):
`cp ~/agent-desk-salvage/agent-desk.db.before-a4 ~/.local/share/agent-desk/agent-desk.db && rm -f ~/.local/share/agent-desk/agent-desk.db-{wal,shm}`

## D9 · A6 and S2 before A2
A2 installs a systemd unit that starts the console at once from a tag. Before A6 that console
would run the autostart/kicking/engine loops, and before S2 the appraise loop spends model calls on
the idea pool in the background. So A6 and S2 land first and A2 installs a tag that has both.

## D10 · Hands off: one refusal in `dispatch.start`, plus hidden buttons
Every path that starts an agent ends in `dispatch.start` (routes, blocks, autostart, the engine),
so the refusal lives there, and `engine.begin` refuses a run. Buttons hidden: "Get it started",
"Start it now", "Have an agent do it instead", "take it on", the autostart switch, and the card's
"run from here". The kicking buttons are left, since S1 deletes kicking. The suite runs with
`AGENT_DESK_HANDS=on` (conftest) so the frozen paths keep their tests. Undo: `AGENT_DESK_HANDS=on`.
