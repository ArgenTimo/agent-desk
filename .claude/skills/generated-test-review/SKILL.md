---
name: generated-test-review
description: 'Methodology skill — audit tests that a model just wrote, before they are committed or used as evidence that a criterion is covered. Catches the specific failure modes of generated tests: assertions that mirror the implementation, over-mocking that tests the mock, tautologies, and coverage that is broad but shallow. Read by the executor after writing tests and by the reviewer when judging coverage. Triggers on phrases "review these tests", "are these tests any good", "проверь тесты". MUST NOT be used to weaken or delete a test in order to make a suite green.'
metadata:
  scope: project
  author: ai-worker
  adapted_from: spec-to-ship/test-craft/test-review/llm-generated-test-review
user-invocable: true
disable-model-invocation: false
---

## Why generated tests need their own audit

They are fluent, numerous, and frequently vacuous. A suite of forty generated tests can raise
coverage twenty points while detecting no defect at all, and the number on the report will look
like progress.

## The checklist

| Failure | How to spot it | What to do |
|---|---|---|
| **Mirrors the implementation** | the assertion restates the code's steps; renaming a private helper breaks it | rewrite from the requirement |
| **Tests the mock** | every collaborator is stubbed; the assertion checks a stub was called | assert the observable outcome instead |
| **Tautology** | `assert result == compute(input)` where `compute` is the code under test | delete; it can never fail |
| **No negative case** | only the happy path | add the boundary and the failure |
| **Asserts incidentals** | key order, whitespace, log strings | assert the requirement |
| **Shared mutable fixture** | tests pass alone, fail in a different order | isolate the state |
| **Sleep-based timing** | `sleep(0.5)` waiting for something | wait on the condition, not the clock |
| **Broad, shallow parametrisation** | thirty cases, one assertion shape | keep three, add depth |

## The mutation question

The single most useful check: **would this test fail if I broke the behaviour it names?** Pick
the assertion, imagine the one-line defect it exists to catch, and decide whether it would catch
it. If not, the test is decoration.

Try it on two or three tests, not all forty. The pattern generalises fast.

## Coverage is a diagnostic, not a target

High coverage with the failures above is worse than lower coverage with real assertions, because
it produces confidence nobody earned. When reporting, say what is covered **behaviourally** —
which criteria are asserted — rather than a percentage.

## In review mode

When the reviewer uses this skill, its output feeds `criterion_untested` findings. The bar for
that finding is behavioural: a criterion "covered" by a test that could not fail is **not
covered**, and saying so is the whole point of running this audit before a human does.
