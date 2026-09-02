---
name: test-data-management
description: How test data is created, isolated and cleaned up so tests stay independent, readable and fast — builders over fixtures, per-test isolation, no shared mutable state, and no production data in a repository. ACTIVATE when a test needs non-trivial setup, when tests interfere with each other, and when a fixture file starts growing. Triggers on "test fixtures", "тестовые данные", "these tests interfere". MUST NOT copy production data into the repository, and MUST NOT introduce a shared mutable fixture to save typing.
metadata: {scope: project, author: ai-worker, adapted_from: internal test-operations practice}
user-invocable: true
disable-model-invocation: false
---

## Builders, not fixture files

```
make_user(email="a@b.c")            # readable, explicit about what this test cares about
```

A builder with sensible defaults says, at the call site, exactly which field matters to this
test. A shared fixture file says nothing, and every test that uses it becomes coupled to fields
it does not care about — so a change to one test's needs breaks nine others.

Rule of thumb: if a reader has to open another file to understand what a test asserts, the data
is in the wrong place.

## Isolation

Each test creates what it needs and leaves nothing behind. Transaction rollback per test, or a
truncate between tests, or unique identifiers per test — whichever the stack supports.

The signature of a violation is a test that passes alone and fails in a suite, or vice versa. That
is not flakiness to retry away; it is shared state, and the fix is isolation, not a retry.

## Determinism

- No `now()` in an assertion — freeze or inject the clock.
- No unseeded randomness in data that an assertion depends on. Seed it, and keep a failing seed as
  a regression case.
- No dependence on insertion order unless the requirement is about order.

## Never copy production data in

A production export in a repository is a breach with extra steps: it contains real people, it is
in every clone forever, and nobody remembers it is there. If realistic shapes are needed,
generate them, or anonymise **before** the data ever reaches a working copy.

## Size

A fixture that grows past a screen is usually two things: the small part the tests actually
assert on, and a large part nobody has read since it was pasted. Split it, and delete what no
assertion touches — unused test data is code that can break the build and can never catch a bug.
