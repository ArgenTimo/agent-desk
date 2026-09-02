---
name: local-gate
description: Runs the project's verification locally — formatter, linter, type check, and the exact test command the CI gate runs (`detected.ci.test_cmd`, else the resolved `toolchain.<lang>.test`) — before anything is pushed, so obvious breakage never reaches the client's runners. Produces a pass/fail report per language. Triggers before a push in implement, correct and test modes, and when the reviewer needs the suite run. MUST NOT report green without an actual run, MUST NOT guess a command when the toolchain entry is null (report `needs_toolchain` instead), and MUST NOT be presented in a report as evidence of correctness — only the client's CI verdict is that.
metadata:
  scope: project
  author: ai-worker
  adapted_from: spec-to-ship/verification-suite/ci-test-gate
user-invocable: true
disable-model-invocation: false
---

## What this proves, and what it does not

It proves the code worked **on this server, at this moment, with whatever is installed here**.
Only the client's pipeline proves anything about the client's product. The distinction is easy
to blur and expensive when blurred: in a report, the local gate is a stage you passed before
spending someone's CI minutes, never a claim that the change is correct.

## Command resolution

1. `detected.ci.test_cmd` — the exact command the pipeline gate runs. Preferred, because it
   reproduces verbatim what blocks a merge.
2. Otherwise `toolchain.<lang>.test` for the language under test.
3. If both are `null`: report `needs_toolchain` for that language, name what is missing, and run
   what you can of the rest. **Do not guess.**

If the project ships a local CI-parity runner (`detected.ci.ci_test_script`), run that instead —
it reproduces the CI environment rather than approximating it.

Polyglot: resolve and run per language, report per language.

## Sequence

```
formatter / linter      fast, catches most model slips
type check              where the stack has one
tests                   the resolved gate command, unfiltered
```

You may narrow the test selection while iterating, but the **gate** is the full unfiltered run.
A green narrow run reported as a green gate is the same class of dishonesty as a fabricated
check.

## When the environment is not ready

Surface exactly what the runner said — missing dependency, stack down, migration pending — bring
it up per the project's documentation, and re-run. If it cannot be brought up, report the gate as
**not run**, not as passed. A check that did not happen is reported as not having happened.

## Policy

The project profile sets `policy.local_gate`:

| Value | Behaviour |
|---|---|
| `required` | a red gate blocks the push; fix it or report `partial` |
| `best_effort` | a red gate is reported; the push proceeds so a human can see the diff |
| `off` | skipped, and the report says the change had no local verification |

A project whose toolchain could not be detected starts at `best_effort` with the reason recorded
— never at `off` pretending everything is fine.

## Output

```json
{"gate": "pytest -q", "languages": {"python": {"result": "passed", "passed": 214, "failed": 0, "skipped": 3}},
 "not_run": [], "needs_toolchain": []}
```
