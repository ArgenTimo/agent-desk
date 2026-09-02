---
name: property-based-testing
description: Test a statement that must hold for all inputs, rather than for the three inputs you thought of — invariants, round-trips, and comparison against a simpler model. ACTIVATE for parsers, serializers, encoders, arithmetic, data transformations, and anything with a "for any X" in its description, when the stack has a property-testing library. Triggers on "property test", "hypothesis", "fuzz this", "проверь на произвольных данных". MUST NOT replace example-based tests for the specific behaviours a requirement names.
metadata: {scope: project, author: ai-worker, adapted_from: internal test-authoring practice}
user-invocable: true
disable-model-invocation: false
---

## When it pays

The value comes from statements of the form "for any input, X holds". Three shapes cover most of
it:

| Shape | Statement | Typical target |
|---|---|---|
| **round trip** | `decode(encode(x)) == x` | serializers, parsers, encoders, migrations |
| **invariant** | some property of the output holds for every input | sorting, normalisation, sanitisation, arithmetic |
| **model comparison** | the fast implementation agrees with a slow obvious one | caches, optimised paths, query builders |

Where the profile's `toolchain.<lang>.property` is null, this skill is `needs_toolchain`: say so
and write example-based tests instead. Do not install a library to satisfy a skill.

## Writing one well

- **Generate the domain, not the universe.** A generator producing mostly invalid inputs tests
  your validation and nothing else. Constrain it to what the function is supposed to accept, and
  test rejection separately.
- **Assert the property, not the implementation.** "The result is sorted and a permutation of the
  input" is a property. "The result equals what my sort returns" is a tautology.
- **Keep the failing case.** When the library shrinks a failure to a minimal input, add that input
  as an ordinary example test. It is now a regression test with a name, and it will still be there
  when the generator changes.
- **Bound the runtime.** A property test is a loop; in CI it needs a case budget, or it becomes
  the reason nobody runs the suite.

## What it does not replace

The example tests for the behaviours the requirement actually names. A property says "nothing
absurd happens for any input"; an example says "this specific thing the ticket asked for
happens". Both, not either.
