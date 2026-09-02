---
name: worktree-workflow
description: One worktree per task off a fresh default branch, never working in the shared checkout. ACTIVATE at the start of any session that will produce a commit, and when a session finds itself editing the shared checkout. Triggers on "start the ticket", "новая ветка", "worktree". MUST NOT be skipped for a small change — the hooks resolve the tree from the session's directory, and a shared tree makes their blocks untrue.
metadata: {scope: project, author: ai-worker}
user-invocable: true
disable-model-invocation: false
---

## Setup

```bash
git fetch origin
git worktree add ../<repo>-<TICKET> -b <branch_prefix><TICKET> origin/<default_branch>
cd ../<repo>-<TICKET>
```

Branch prefix and default branch come from the project profile. One worktree per ticket, always,
regardless of the size of the change.

## Why it is not optional

`stop-verify.sh` and `scope-guard.sh` resolve the tree from the session's own directory and act
on exactly that tree. In a shared checkout a hook fires against whatever branch happens to be
checked out, which produces blocks that have nothing to do with this session's work — and the
predictable response to those is to route around the hook. One worktree per ticket keeps every
block true.

The second reason is concurrency: two tickets in flight means two worktrees, two branches, two
draft pull requests, and no stashing. A stash is a place where work is lost.

## During

- Commits are small, conventional if the project has a convention, and each references the ticket.
- Rebase onto the default branch **deliberately**, not habitually: a rebase creates new revisions,
  which invalidates any approval already given and requires a new pipeline run.
- Run the gates in the worktree, not in the shared checkout.

## Cleanup

```bash
git worktree remove ../<repo>-<TICKET>
git worktree prune
```

After the pull request merges. Stale worktrees accumulate and make `git worktree list` useless,
which is where the next person looks to find out what is in flight.

## If the project forbids worktrees

Some setups cannot use them — a build that hardcodes an absolute path, a toolchain that indexes
one directory. Then use one branch per ticket in the shared checkout, and record the exception in
the project profile so the hooks' behaviour is understood rather than fought.
