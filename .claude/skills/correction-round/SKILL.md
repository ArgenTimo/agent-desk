---
name: correction-round
description: 'Executor skill for `correct` mode — fix the reviewer''s BLOCKING findings in the same branch and the same pull request, re-run the local gate, push, and report per finding. Bounded: the orchestrator allows a fixed number of rounds (default 2), after which unresolved findings travel to the human marked as such. Triggers when a review returns `changes_required` and rounds remain. MUST NOT touch advisory findings, MUST NOT weaken a test to clear a failure, MUST NOT expand scope, and MUST NOT silently ignore a finding it disagrees with.'
metadata:
  scope: project
  author: ai-worker
user-invocable: false
disable-model-invocation: false
---

## Blocking findings only

Advisory findings are for the human reviewer to decide on. Fixing them here expands the diff a
human is about to read, on the judgement of a model that was explicitly not asked. Leave them.

## Disagreement

If a finding is wrong, say so in the report with the evidence — the file, the line, the reason —
and **leave the code as it is**. A disputed finding reaching a human with both positions stated
is a good outcome. Silently ignoring one is not, and neither is complying with a change you
believe breaks something without saying so.

## The two traps

**Weakening a test to clear a failure.** A failing test is either a defect in the code or a
defect in the test. Which one it is belongs in the report; deleting the assertion answers the
question by destroying the evidence.

**Fixing more than the finding.** A correction round is not an opportunity to improve the
module. The smallest change that removes the finding is the correct change, and anything else
lands in a diff the human already started reading.

## Report

```json
{
  "outcome": "finished|partial",
  "head_sha": "9c1b7e2",
  "resolutions": [
    {"finding": "test_failure: test_export_encoding", "action": "fixed", "detail": "...", "commit": "9c1b7e2"},
    {"finding": "out_of_scope: dashboard.py", "action": "disputed", "detail": "Required: the shared filter signature changed."}
  ],
  "checks": [{"name": "local gate", "result": "passed"}],
  "next": "re-review"
}
```

Every finding gets a resolution line: `fixed`, `disputed`, or `deferred` with a reason. A finding
missing from this list is a finding that was dropped, and the loop treats a dropped finding as
unresolved.
