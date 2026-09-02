---
name: http-service-virtualization
description: Test against a recorded or stubbed HTTP dependency instead of a live one — cassettes, a local stub server, or a fake at the client boundary — so tests are deterministic, offline and fast. ACTIVATE when a test would otherwise call a third-party API, when a suite is slow or flaky because of the network, and when reproducing an upstream's specific error. Triggers on "mock the API", "запиши каccеты", "tests hit the network". MUST NOT record a cassette containing a live credential or customer data, and MUST NOT let a stale recording silently pass over a changed upstream.
metadata: {scope: project, author: ai-worker, adapted_from: internal test-integration practice}
user-invocable: true
disable-model-invocation: false
---

## Three levels, pick the lowest that answers the question

| Level | Use for | Cost |
|---|---|---|
| **fake at the client boundary** (`fakes-over-mocks`) | the semantics your code depends on | cheapest, most durable |
| **recorded traffic (cassettes)** | protocol details: pagination, headers, error bodies, a specific API version | medium; recordings go stale |
| **local stub server** | timeouts, connection resets, slow responses, streaming | most setup; unbeatable for failure modes |

Most tests want the first. Reach for the second when the bug you are preventing lives in the wire
format, and the third when it lives in the network's behaviour rather than the response's content.

## Recording safely

A cassette is a file in the repository containing whatever the API returned:

- **Filter credentials before writing.** Authorization headers, tokens in query strings, cookies,
  and any `Set-Cookie`. Configure the filter before the first recording, not after.
- **Filter payload data.** Real ticket text, real names, real emails — the same rule as
  `test-data-management`: production data does not enter a repository.
- **Record once, deliberately.** An auto-re-recording mode turns a red test green by capturing
  the new behaviour, which is the exact failure it was supposed to report.

## Staleness

A recording is a claim about an upstream that keeps changing. Two defences:

1. **A contract test against the real API**, run on a schedule or before a release — not in the
   ordinary suite. It is allowed to fail loudly when the upstream changed; that is its job.
2. **Re-record on purpose**, in a separate commit, with the diff reviewed. A cassette diff is
   readable and frequently reveals the upstream change that would otherwise have surprised
   production.

## Failure modes worth stubbing

Rate limiting with a retry hint, a 500 mid-pagination, a timeout, a truncated body, and an
eventually-consistent read that returns the old value once. Client code is usually written for the
happy path, and these four are what it will actually meet.
