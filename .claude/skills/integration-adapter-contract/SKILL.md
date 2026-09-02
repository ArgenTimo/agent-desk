---
name: integration-adapter-contract
description: Rules for code that talks to an external system — an HTTP client, an SDK wrapper, a queue consumer. Keeps the boundary honest so a provider can be swapped, a failure is distinguishable from an absence, and no adapter starts deciding things on its caller's behalf. ACTIVATE when writing or changing anything that calls out of the process, and when adding a provider. Triggers on "add an integration", "API client", "адаптер". MUST NOT let an adapter return a judgement where the upstream returned uncertainty, or cache a fact that can change.
metadata: {scope: project, author: ai-worker}
user-invocable: true
disable-model-invocation: false
---

## Three rules

**No adapter method returns a judgement.** If the upstream says "I do not know yet" — a
mergeability state still computing, an eventually-consistent read, a check with no conclusion —
the adapter returns that, not a convenient boolean. The caller decides what unknown means. The
moment an adapter maps unknown to "probably fine", a decision is being made in a helper function
nobody reviews.

**Never swallow an error into a falsy return.** "The object does not exist" and "we could not
ask" are different facts. Return `None` where absence is meaningful; raise where it is not. Code
that cannot tell them apart will eventually act on a network blip as if it were a deletion.

**Do not cache a fact that can change.** A status, a HEAD revision, a review, a check conclusion
— always a live read. Caching is for content that is stable for the length of a task: an exported
design frame, a documentation page. A cached live fact is how a system acts on a world that no
longer exists.

## Error classes

Uniform, because callers handle them uniformly:

| Class | Adapter behaviour |
|---|---|
| auth failure (401/403) | raise a distinct `CredentialInvalid`; this is not retryable and must surface, not retry silently |
| rate limit (429) | honour `Retry-After`, retry inside the adapter within a small budget |
| server error (5xx) | retry with jitter to a budget, then raise a distinct `Upstream` error |
| timeout | always set one; a call without a timeout is a hang waiting for a bad day |
| not found | `None` or raise, per the rule above — decided per method, documented |

## Adding a provider

Implement the existing interface; add nothing to it. If the new provider genuinely cannot express
an operation, that is a finding about the design, not a licence to widen the interface with an
optional method that one implementation ignores.

And **verify the guarantees you claim** rather than assuming them from the other provider. If the
code says "an approval is invalidated by a new commit", test it on a scratch project: approve,
push, look. An adapter reporting a guarantee its platform does not provide is worse than one
reporting the guarantee as absent.

## Testing

Fakes with real state, not mocks asserting a call sequence — `fakes-over-mocks`. Contract tests
run against both the fake and a recorded-fixture implementation of the real client, so the fake
cannot drift into a green suite over a broken integration.
