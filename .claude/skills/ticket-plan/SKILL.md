---
name: ticket-plan
description: 'Planning skill — after intake reports ready, produce the approach before touching code: the change in a paragraph, the files to be touched, a test for every acceptance criterion, and what is deliberately out of scope. Structured JSON only; writes nothing. Triggers when the orchestrator starts a run in plan mode. MUST NOT write code, MUST NOT create a branch, and MUST NOT produce a plan touching more than roughly ten files — that is a decomposition proposal, not a plan.'
metadata:
  scope: project
  author: ai-worker
user-invocable: false
disable-model-invocation: false
---

## Why a separate pass

A session that plans and implements in one breath implements first and rationalises after. The
plan exists so a human reviewing the pull request can see what you intended, and so the reviewer
agent has something to check the diff against. It is also the cheapest place to be wrong.

## Process

1. Re-read the ticket, including anything answered since intake.
2. Read the code you will change and the tests around it.
3. Choose the smallest change satisfying the acceptance criteria.
4. Map every acceptance criterion to at least one test you will write.
5. Decide what you will deliberately not do.

## Mapping criteria to tests

This is the part the reviewer agent will check, so do it honestly. A criterion with no test is a
criterion the reviewer will block on later — better to notice now, and to say in the plan that
it is untestable and why, than to have it found after the code exists.

If a criterion cannot be tested at all — visual appearance, feel, performance under real load —
say so in `untestable`, with the reason. It will travel into the report's "not verified
automatically" section, which is where unverifiable claims belong.

## Output

```json
{
  "approach": "One paragraph: what changes and why this way.",
  "files": [{"path": "reports/export.py", "change": "new CSV serializer"}],
  "tests": [{"criterion": "Exports filtered rows", "test": "test_export_respects_filters"}],
  "untestable": [{"criterion": "Download dialog looks right", "reason": "no snapshot baseline"}],
  "out_of_scope": ["pagination above 100k rows"],
  "risks": ["the filter helper is shared with dashboard.py"],
  "arbitration_points": [
    {"question": "Where does the serializer belong?", "options": ["beside the PDF export", "new serializers package"]}
  ]
}
```

`arbitration_points` are the decisions you already know you will face. Naming them in the plan
lets the arbiter resolve them before implementation starts rather than mid-edit, which is both
cheaper and produces a better answer — a decision made with the whole plan in view beats one
made with a half-written file in view.

## What `out_of_scope` is for

Not a disclaimer section. It is what a reviewer needs to know you chose not to do, so they can
disagree **before** the code exists. Anything you decided against for a reason belongs there;
anything you simply did not think about does not, and pretending otherwise is how a plan becomes
theatre.
