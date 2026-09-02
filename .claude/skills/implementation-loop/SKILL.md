---
name: implementation-loop
description: Executor skill for `implement` mode — work the plan into code and tests in the ticket's worktree, commit, push, and open or update the DRAFT pull request. Calls `decision-arbitration` at material decision points and `local-gate` before pushing. Ends with a structured report whose every claim is backed by an artifact. Triggers when the orchestrator starts a run in implement mode. MUST NOT un-draft the pull request, push to any branch but its own, edit CI configuration, or report a check it did not run.
metadata:
  scope: project
  author: ai-worker
user-invocable: false
disable-model-invocation: false
---

## Order of operations

1. You are started **inside the ticket's worktree**; the branch already exists.
2. Open the **draft** pull request early, before the implementation is finished. It gives review,
   diff, comments, history, SHA binding and an approval mechanism from a platform that already
   implements all of them — and it gates cost: expensive CI does not run on a draft.
3. Implement the plan. Small conventional commits, each referencing the issue key.
4. Write the tests from the plan.
5. Run `local-gate`. Fix what it finds.
6. Sync the pull-request description with what you actually shipped.
7. Emit the report.

## When to call the arbiter

At a **material** decision point: a choice a reviewer would plausibly object to, or one that is
expensive to reverse. Naming a local variable is not one. Choosing where a module lives, whether
to add a dependency, which of two existing abstractions to extend — those are.

The cap (default 8 per run) exists so an executor cannot outsource its thinking one line at a
time. On reaching it, proceed on a **stated assumption** and say so in the report. The cap must
never silently become a decision.

## Surgical changes

- Touch only what the ticket requires. Do not improve adjacent code, reformat untouched files, or
  refactor what is not broken.
- Match the existing style even where you would do it differently. You are joining a codebase.
- Remove imports and helpers **your** change orphaned; leave pre-existing dead code alone and
  mention it in the report.
- Every changed line should trace to the ticket. The reviewer blocks on `out_of_scope`, and it is
  right to.

## Tests

Tests that would pass against a broken implementation are worse than no tests. Assert behaviour,
not the shape of your own code. Every acceptance criterion in the plan gets its test here — the
reviewer checks exactly this, and finding it now costs one file, later it costs a round.

## When the plan turns out wrong

Stop. Finish the current commit cleanly. Report what you found and why the plan does not hold. A
wrong plan discovered early is cheap; a wrong plan implemented completely is not, and quietly
substituting a different design for the one a human read is worse than either.

## Report

```json
{
  "outcome": "finished|partial|failed",
  "branch": "ai/PROJ-118", "pr_number": 431, "head_sha": "4f2a91c",
  "done": ["..."],
  "arbitrations": [{"decision_id": "d-04", "chosen": "a", "confidence": "high"}],
  "assumptions_proceeded_on": ["..."],
  "checks": [{"name": "local gate", "result": "passed", "detail": "214 tests"}],
  "not_verified_automatically": ["visual appearance of the dialog", "behaviour above 100k rows"],
  "notes_for_reviewer": ["The filter helper is shared with dashboard.py"],
  "next": "developer review"
}
```

An empty `not_verified_automatically` means you did not think about it. Every non-trivial change
has something no test covered, and the section exists because a template that demands only
verifiable-sounding fields gets filled with invention.
