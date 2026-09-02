---
name: flaky-test-management
description: 'Methodology skill — handle a test that passes and fails without code changes: identify it, classify the source of nondeterminism, fix it at the source, and report it as a finding rather than retrying until green. Read when a suite result differs between runs of the same SHA, or when the reviewer sees a pass-on-retry. Triggers on phrases "this test is flaky", "passed on the second run", "тест флакает". MUST NOT resolve flakiness by adding a retry, a sleep, or a skip in order to reach a green report.'
metadata:
  scope: project
  author: ai-worker
  adapted_from: spec-to-ship/test-craft/test-operations/flaky-test-management
user-invocable: true
disable-model-invocation: false
---

## A pass on retry is a finding, not a pass

The report must say `flaky: 1`, never `passed`. This matters more inside an automated pipeline
than in a human workflow: a human notices the second run; a pipeline that reports the retry as a
success buries the only evidence that anything was wrong.

## Classify before fixing

| Source | Signature | Fix |
|---|---|---|
| **Order dependence** | passes alone, fails in a suite, or vice versa | isolate the shared state; make setup create what the test needs |
| **Time** | fails near midnight, month end, or under load | freeze the clock; assert on a condition, not on a duration |
| **Concurrency** | fails under parallel execution only | remove the shared resource or serialise that test explicitly |
| **External dependency** | fails when a network or a container is slow | virtualise the dependency |
| **Randomness** | fails for some seeds | seed deterministically, and keep the failing seed as a regression case |
| **Real defect** | fails under a genuine race in the code | it is not the test that is flaky — report it as `test_failure` |

The last row is the one most often misclassified, and misclassifying it is expensive: a race in
production code labelled "flaky test" and retried away is a defect shipped deliberately.

## Inside a run

You are not the owner of the project's test suite. When a pre-existing test is flaky and
unrelated to the diff:

1. Report it in the run report under checks, named, with the retry result.
2. Do not fix it as part of this ticket — that is scope the ticket did not ask for.
3. Do not disable it. Disabling somebody else's test to make your ticket green is the worst
   available option; it removes a check and hides the removal in an unrelated diff.

When the flaky test is one **you just wrote**, fix it here. A test that you introduced and that
cannot pass reliably is not finished.

## Reporting

```
Checks:
- local gate: passed (214 tests, 1 flaky)
Not verified automatically:
- tests/test_sync.py::test_replica_catches_up is flaky (passed on retry, pre-existing,
  order-dependent — not touched by this ticket)
```
