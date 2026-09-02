---
name: test-impact-selection
description: Run the subset of tests a change can actually affect while iterating, and the full suite as the gate — without letting the narrow run be mistaken for the gate. ACTIVATE while iterating on a change in a slow suite, and when deciding what to run before pushing. Triggers on "run the relevant tests", "быстрый прогон", "which tests should I run". MUST NOT report a narrow run as a passing gate, and MUST NOT be used when the change touches shared infrastructure, configuration or a base class.
metadata: {scope: project, author: ai-worker, adapted_from: internal test-impact practice}
user-invocable: true
disable-model-invocation: false
---

## Two different questions

**"Is my current edit going the right way?"** — a narrow run: the tests for the module you are
editing, selected by path, by name, or by the stack's impact tool
(`toolchain.<lang>.test_changed` in the profile). Fast, iterative, and **not** evidence.

**"Is this branch safe?"** — the full suite, unfiltered, which is the gate. Nothing narrow ever
substitutes for it, and a report that presents a narrow run as a gate is dishonest in the same
way as a fabricated check.

## Selecting well

| Change | Run |
|---|---|
| one module's logic | that module's tests, plus its direct consumers |
| a shared helper or base class | **the full suite** — impact analysis is unreliable here |
| a configuration or dependency change | the full suite; the blast radius is everything |
| a data model or schema change | the full suite plus the migration tests |

The rule behind the table: impact selection is trustworthy exactly where the dependency is
visible in an import graph. Configuration, dependency injection, monkey-patching and inheritance
make it unreliable, and those are precisely where the surprising breakage lives.

## Where the stack has a tool

Use it, and record the command in the profile under `toolchain.<lang>.test_changed`. Where the
entry is null, do not invent one: select by path, and say in the report that no impact tool was
available.

## What goes in the report

```
Checks:
- tests (full suite, gate): 214 passed, 3 skipped
While iterating: narrow selection by path (not the gate)
```

Naming the narrow run as "not the gate" is the whole point of mentioning it at all.
