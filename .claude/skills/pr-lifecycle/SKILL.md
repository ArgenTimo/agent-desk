---
name: pr-lifecycle
description: Pull-request skill — open and maintain the draft pull request for the ticket's branch, keep its description in sync with what was actually shipped, triage unresolved review comments and route them, and detect conflicts or base drift. One pass per invocation; not a daemon. Triggers in implement, correct and respond modes, and when the orchestrator checks a PR's state. MUST NOT un-draft (the pipeline does that after verification), MUST NOT merge, MUST NOT approve, and MUST NOT resolve a reviewer's thread unless the project's convention says the author does.
metadata:
  scope: project
  author: ai-worker
  adapted_from: spec-to-ship/git-delivery/mr-lifecycle (GitLab MR -> GitHub PR)
user-invocable: true
disable-model-invocation: false
---

## What changed from the source skills

The source split this across four skills built around GitLab merge requests and a local
state file remembering last-seen comments. Inside ai-worker the run record already holds run
state, so the state file is gone; and the code host is reached through the adapter, not through
a hardcoded instance pair. What survives unchanged is the useful part: the triage of review
comments, and the discipline about descriptions.

## Draft-first

The pull request is created as a **draft** and stays one for the whole session. Every
intermediate commit would otherwise trigger the client's pipeline. The draft is removed exactly
once, by the pipeline, after the sentinel passes.

For a pull request that already exists and is being modified: move it to draft during the
session and return it to **its previous state** afterwards. If it was a draft before, publishing
it is the author's decision, not yours.

## Description sync

The description is what a reviewer reads before the diff. Keep it matching what shipped:

```
<one-paragraph summary of the change>

Ticket:        PROJ-118
Design:        <link, if the ticket had one>
Approach:      <the plan's approach, one paragraph>
Out of scope:  <from the plan>
Not verified automatically:
- <from the report>
```

Never write "fully implements the requirements" or any claim you cannot back. A description that
overstates is worse than a thin one: it is read as a promise.

## Review-comment triage

One pass. For each unresolved comment, classify:

| Class | Action |
|---|---|
| actionable | apply it in `correct` or `respond` mode |
| question | answer it in the thread |
| disagreement | state the reasoning once, then do what was asked unless it breaks something — and if it does, say exactly what, with the file and line |
| out of scope | acknowledge, and say it belongs in a separate ticket |

**Address every comment**, including the ones you disagree with. A silently ignored comment is
how a reviewer learns to stop reviewing carefully.

## Conflicts and base drift

Report the state; do not repair it.

| State | Report as |
|---|---|
| `CURRENT` | fine |
| `BEHIND_BASE` | needs a branch update — a human decision |
| `CONFLICTING` | needs a human |
| `UNKNOWN` | the check did not happen. **Not** "fine." Re-check. |

Updating the branch creates a new SHA, which invalidates approvals and requires a fresh CI run.
That is a human's deliberate choice, never a side effect of a maintenance pass.
