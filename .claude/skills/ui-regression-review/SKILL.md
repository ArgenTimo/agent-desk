---
name: ui-regression-review
description: Review-time check for a change touching a user interface — visual diffs against baselines, accessibility basics, and the states that are easy to break and hard to notice. ACTIVATE when the diff touches UI code and the project has a way to render it. Triggers on "check the UI", "визуальная регрессия", "did this break the layout". MUST NOT claim a design match from a screenshot comparison by eye, and MUST NOT auto-approve changed snapshots.
metadata: {scope: project, author: ai-worker, adapted_from: internal UI verification practice}
user-invocable: true
disable-model-invocation: false
---

## Status first

This skill is `not_applicable` unless the project has a renderable UI, and `needs_toolchain`
unless it has a way to render and compare — a component test runner, a browser harness, or
snapshot baselines. Say which, and stop, rather than substituting a guess.

## Snapshots

Every changed snapshot is **either intentional or a regression**. There is no third category, and
"the diff is tiny" is how regressions ship.

For each: name it, say which change caused it, and either approve it with that reason recorded, or
report it as a defect. Bulk approval defeats the entire mechanism — the baseline exists precisely
so that a change nobody intended has to be looked at once.

## Without baselines

If the project has no visual baselines, do not invent a comparison. A model reading two
screenshots cannot reliably say whether a layout matches a design, and a report claiming it can is
worse than one that admits the gap. Check what is checkable instead:

- the states most often forgotten: **empty**, **loading**, **error**, **long content**, **narrow
  viewport**;
- accessibility basics an automated pass can assert: every interactive element reachable by
  keyboard, form controls labelled, images with alternative text, contrast on new colour pairs;
- console errors and warnings introduced by the change.

Then list "visual match with the design" under not-verified, where it belongs.

## Reporting

```
UI review
Snapshots: 2 changed
  Button/primary — intentional (padding token updated per the ticket) — approved
  Table/empty    — NOT intentional — the empty state lost its icon — defect
States: empty ✓ loading ✓ error ✓ long content — text overflows at 320px (defect)
A11y: new icon button has no accessible name (defect)
Not verified: visual match with the design (no baseline exists)
```
