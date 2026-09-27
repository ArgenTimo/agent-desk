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
