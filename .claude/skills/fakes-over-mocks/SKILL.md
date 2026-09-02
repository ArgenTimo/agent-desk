---
name: fakes-over-mocks
description: Build and use small in-memory implementations of an external dependency, with real state and fault injection, instead of mocks asserting call sequences. ACTIVATE when writing a test that touches an external system, when a test needs a failure mode, and when adding a capability to an integration. Triggers on "test this without the API", "мок", "how do I test this integration". MUST NOT let a fake drift from the real client's behaviour — a drifted fake produces a green suite over a broken integration.
metadata: {scope: project, author: ai-worker, adapted_from: internal test-integration practice}
user-invocable: true
disable-model-invocation: false
---

## Why not mocks

A mock asserting a call sequence tests the implementation's shape. Code gets restructured; each
restructure then rewrites the suite while catching nothing. A fake with real state tests behaviour
and survives.

## What "real state" means

The fake behaves like the system, not like a lookup table:

- an operation that can only succeed once **does** only succeed once (a claim, a delete, a
  one-shot token);
- an object's derived fields move when the object changes — a pull request's head revision, an
  entity's updated timestamp;
- a child record belongs to the parent it belongs to in reality: a check belongs to a **revision**,
  not to a pull request. Getting that wrong in the fake hides exactly the bug that matters, since
  most confusion in this class of system is "the PR is green" versus "this revision is green".

## Fault injection, not just happy paths

Every fake supports: rate limiting with a retry hint, server errors, timeouts, an eventually-
consistent read, and the important one — **a write that succeeds and then reports failure**. That
last case is the crash window where the effect exists and the caller believes it does not, and
code that has never been tested against it will duplicate the effect on retry.

## Keeping fakes honest

1. **Contract tests run against both** — one test module, parametrised over the fake and a
   recorded-fixture implementation of the real client.
2. **A new capability lands in the fake in the same commit.** A fake missing a method is a test
   nobody can write, and that test is the one that would have caught it.
3. **Never assert on the fake's internals** from a test of production code. If a test needs to
   look inside the fake, the production code is missing an observable outcome.

## When a fake is the wrong tool

Deep protocol behaviour — TLS quirks, streaming, pagination edge cases in a specific API version
— is better covered by recorded traffic against the real client
(`http-service-virtualization`). Fakes model the semantics you depend on, not the wire.
