---
name: combinatorial-test-design
description: Choose a small set of cases that covers the interactions between several parameters, instead of one case per combination or three cases chosen by intuition. ACTIVATE when a feature has three or more independent flags, roles, formats or states whose combinations matter. Triggers on "test all the combinations", "матрица тестов", "how many cases do I need". MUST NOT be used to justify a parametrised suite of thirty shallow cases with one assertion shape.
metadata: {scope: project, author: ai-worker, adapted_from: internal test-integration practice}
user-invocable: true
disable-model-invocation: false
---

## The problem

Four parameters with three values each is 81 combinations. Writing all of them produces a slow
suite nobody reads; writing three by intuition covers the combinations you already thought about,
which are the ones least likely to be broken.

## Pairwise as the default

Most interaction defects involve **two** parameters, not five. A pairwise set — every pair of
values appears together in at least one case — covers those in roughly a dozen cases instead of
81. Generate it with the stack's tool if there is one, or by hand for small matrices; the exact
set matters less than the coverage property.

## Then add, deliberately

Pairwise is a floor, not the whole design. Add:

- **the boundaries** — empty, one, maximum, just over the maximum;
- **the known-dangerous combination** — the one an incident or a bug report already named;
- **the forbidden combination** — assert it is rejected, rather than leaving it untested because
  it "cannot happen".

## Naming

A parametrised case that fails must say what failed:

```
test_export[format=csv-role=viewer-archived=included]
```

not `test_export[7]`. A failing case number in CI costs a reader ten minutes of reconstruction.

## When not to bother

Two parameters: write all four cases. Parameters that do not interact: test them separately, and
say why they are independent — that sentence is worth more than the matrix, because it is the
assumption that would make the whole design wrong if it were false.
