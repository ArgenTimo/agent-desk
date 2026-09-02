---
name: qa-gate
description: The adversarial verification protocol for a change you believe is finished — five passes, each assuming the previous one lied. ACTIVATE before a pull request leaves draft, when a change touches anything with state or concurrency, and whenever you catch yourself about to write "should work". Triggers on "qa gate", "verify this properly", "проверь по-настоящему", "прогони качественно". MUST NOT be shortened by skipping the confirmation run, and MUST NOT treat retry-until-green as a pass.
metadata: {scope: project, author: ai-worker, adapted_from: an internal QA protocol}
user-invocable: true
disable-model-invocation: false
---

## Pass 1 — Deterministic gates, in full

Lint, type check, the project's test command, plus the heavier suites the change touches. Full
runs, unfiltered. Record the actual numbers, not "green".

## Pass 2 — Clean environment

Re-run Pass 1 with nothing reused: fresh dependency install, fresh containers, fresh database. A
warm cache hides a missing dependency declaration and a migration that only applies to an
already-migrated database. This pass exists because CI is always cold.

## Pass 3 — Adversarial self-review

Assume Pass 1 lied. Three concrete exercises, not a feeling:

- **Sabotage spot-check.** Break the behaviour the new test names — invert a condition, return
  early — and confirm the test goes red. If it stays green, the test is decoration and the
  coverage number was noise.
- **Boundary probe.** Empty, one, many, maximum, concurrent, restarted. Whichever of these the
  change plausibly touches, try it by hand once.
- **Rule probe.** For each documented rule the change touches, try to violate it and confirm
  something stops you — a constraint, a permission, a test. If nothing does, the rule is a wish.

## Pass 4 — Read the diff as a stranger

Whole diff, top to bottom, as if you had not written it. Looking for: files with no reason to be
here, a debug artifact, a weakened assertion, a comment describing behaviour the code no longer
has, a document that now contradicts the code.

## Pass 5 — Confirmation run

Re-run Pass 1 once more, after every fix. It costs one command and has caught order-dependent
tests and dirty-state passes. **Every fix restarts the protocol** — one-line fixes have one-line
blast radii only in retrospect.

## Rationalizations and rebuttals

| Rationalization | Rebuttal |
|---|---|
| "Pass 1 was green, the re-run will obviously be green." | Then it costs one command. When it is not, that certainty was the bug. |
| "The sabotage check is theatre, I know the test covers it." | Then it costs sixty seconds and proves it. |
| "It's flaky, re-run until green." | A flake is a finding. Quarantine it with a ticket; never launder it through retries. |
| "Integration tests need Docker, CI will run them." | CI runs them after a human's time is already committed. Run them here. |
| "The snapshot diffs are tiny, approve them." | Every changed snapshot is intentional or a regression. "Tiny" is how regressions ship. |
| "One-line fix after Pass 3, no need to restart." | Restart. |
| "Coverage went up, the changed lines are probably covered." | Read the missing-lines output for the changed lines. The global number is noise here. |

## Output

Report each pass with its real numbers, what the probes actually did, and a final
`Not verified:` list. A gate report claiming everything was checked has checked nothing
carefully.
