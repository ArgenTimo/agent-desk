---
name: pre-pr-checklist
description: The gate before a pull request leaves draft or goes to a human — eight checks over the branch as it actually is, each blocking or advisory. ACTIVATE before un-drafting, before asking for review, and again after any rebase, which invalidates every previous run of it. Triggers on "ready for review", "готово", "can this be merged". MUST NOT report a skipped check as passed — a skip is reported as a skip, with its reason.
metadata: {scope: project, author: ai-worker, adapted_from: an internal pre-MR checklist}
user-invocable: true
disable-model-invocation: false
---

### 1. Drift against your own remote (blocking)
`git fetch && git rev-list --count HEAD..@{u}`. Non-zero means the branch is behind its own
remote: a push would drop somebody's work. The push hook blocks it; this check surfaces it before
the hook does.

### 2. Base drift (blocking as a decision, not as a stop)
Behind the base branch is not fatal, but it must be **decided**: rebasing creates new revisions,
invalidating any approval and requiring a new pipeline run. Say which you chose and why.

### 3. Gates in a clean environment (blocking)
Lint, type check, tests — with a fresh dependency install, not the session's warm one. A cached
environment hides a missing declaration, and the runner will not have your cache.

### 4. Acceptance criteria (blocking)
Every criterion on the ticket is implemented **and** covered by a test, or explicitly listed as
untestable with a reason. This is what the reviewer checks; finding a gap here costs one file,
finding it later costs a round.

### 5. Migration safety (blocking, conditional)
When the change adds a migration: one head, upgrade clean on empty and on populated, constraints
re-applied on any rebuilt table, honest downgrade. See `schema-migration-safety`.

### 6. Secret sweep (blocking)
`gitleaks detect` over the branch range, or the fallback patterns. The commit hook scans staged
diffs; this catches anything that arrived by rebase or cherry-pick.

### 7. Scope (blocking)
Every file in the diff has a reason to be there. Formatting churn in an untouched file, a stray
lockfile change, a config edit nobody asked for — each costs a reviewer's attention and each is
removable in ten seconds now.

### 8. Markers and documentation (advisory)
`TODO` / `FIXME` introduced by this branch: resolved, ticketed, or kept with a stated reason.
Documentation updated where the change made a statement false.

## Output

```
pre-pr-checklist — <branch> @ <revision>

1 drift                 PASS
2 base drift            PASS (3 behind; not rebasing — an approval is already on this revision)
3 gates (clean env)     FAIL — 1 test
4 acceptance criteria   PASS (3/3 covered)
5 migrations            SKIP (none in this branch)
...
VERDICT: BLOCKED on 3
```

`PASS` with a `SKIP` in the list is honest. `PASS` where a check never ran is the failure this
checklist exists to prevent.
