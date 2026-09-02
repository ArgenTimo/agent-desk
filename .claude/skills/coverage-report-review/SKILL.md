---
name: coverage-report-review
description: Read a coverage report for what it can actually tell you — which changed lines are unexecuted — and not as a score to raise. ACTIVATE when a change adds logic and coverage tooling exists, and when someone proposes a coverage threshold. Triggers on "check coverage", "покрытие", "coverage dropped". MUST NOT be used to justify tests written only to raise a number, and MUST NOT report a global percentage as evidence that a change is tested.
metadata: {scope: project, author: ai-worker, adapted_from: internal test-review practice}
user-invocable: true
disable-model-invocation: false
---

## What coverage measures

That a line was executed. Not that its behaviour was asserted, not that the assertion could fail,
not that the requirement is met. A suite of tests calling every function and asserting nothing
reaches 100 % and detects nothing.

So read it for one thing: **which lines this change added are never executed by any test**. That
list is a real finding. The global percentage is not.

## How to read it

1. Run coverage on the changed files only, with missing-line output.
2. For each uncovered line, decide: needs a test · unreachable and should be deleted · defensive
   code that genuinely cannot be triggered (say so).
3. For each *covered* changed line that matters, apply the mutation question from
   `generated-test-review`: would a test fail if this line were wrong? Coverage says it ran, not
   that anyone was watching.

## Thresholds

A global threshold produces tests written to satisfy it — usually the shallow, assertion-free
kind. If the project wants a gate, a **diff-coverage** gate is the defensible version: new lines
are covered, existing debt is not made worse. Even then it is a floor, not a goal.

## Reporting

```
Coverage (changed files only): 3 lines unexecuted
  export.py:88-90  the empty-result branch — added a test
  export.py:142    defensive guard, unreachable without corrupting the row — left, noted
```

Never write "coverage is 87 %" as though it answered whether the change is tested. It does not,
and putting it in a report invites the reader to believe it does.
