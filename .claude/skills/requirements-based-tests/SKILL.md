---
name: requirements-based-tests
description: Methodology skill — derive tests from the acceptance criteria and any specification artifacts rather than from the implementation, so every requirement has a traceable test and the tests survive a refactor. Read when writing tests in implement or test mode, and when the reviewer needs to judge whether a criterion is genuinely covered. Triggers on phrases "write tests for this ticket", "cover the acceptance criteria", "напиши тесты по критериям". MUST NOT be used to write tests by reading the implementation back, which produces tests that pass against a broken implementation.
metadata:
  scope: project
  author: ai-worker
  adapted_from: spec-to-ship/test-craft/test-authoring/requirements-based-generation
user-invocable: true
disable-model-invocation: false
---

## The rule

A test derived from the implementation asserts what the code does. A test derived from the
requirement asserts what the code should do. Only the second one can fail usefully.

Concretely: write the assertion **before** looking at how the function computes its result, and
if that is impossible, say so rather than reading the implementation and describing it back.

## Traceability

Every acceptance criterion maps to at least one test, and the mapping is written down — in the
plan, and again in the report:

```
criterion: "Exports the currently filtered rows"
test:      tests/test_export.py::test_export_respects_filters
```

The reviewer checks exactly this mapping. A criterion with no test is a blocking finding, so the
cheapest place to notice is here.

## Deriving cases from a criterion

For each criterion, work through:

| Angle | Question |
|---|---|
| happy path | the stated behaviour, once |
| boundary | empty, one, many, maximum |
| negative | wrong type, missing permission, malformed input |
| persistence | does it survive a restart, a reload, a second request |
| interaction | does it break the neighbouring feature that shares this code |

Not every angle applies to every criterion. Naming the ones you skipped, and why, is more useful
than silently covering three of five.

## What makes an assertion good

- It fails for exactly one reason. A test asserting six things tells you nothing about which
  broke.
- It names the behaviour, not the mechanism: `test_export_respects_filters`, not
  `test_export_calls_build_query`.
- It has no branching. A test with an `if` is two tests wearing one name.
- It does not assert on incidental structure — key order, whitespace, log text — unless the
  requirement is about those.

## Unverifiable criteria

Some criteria cannot be tested: appearance, feel, performance under real load. Do not write a
test that pretends. Record the criterion in `untestable` in the plan and in the report's "not
verified automatically" section. That is where honest gaps live, and the reviewer will not block
on a gap that was declared.
