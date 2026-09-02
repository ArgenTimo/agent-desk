---
name: observability-discipline
description: What a log line, a metric and an error must carry to be useful during an incident — correlation identifiers, redaction at the logger, stable metric names, and the rule that a check which did not run is never reported as passed. ACTIVATE when adding logging, a metric, or an error path, and when debugging something the current logs could not explain. Triggers on "add logging", "метрика", "why can't I tell what happened". MUST NOT log a request or response body, and MUST NOT rely on redaction as the reason a credential is safe.
metadata: {scope: project, author: ai-worker}
user-invocable: true
disable-model-invocation: false
---

## Correlation

Every log line carries whatever identifies the unit of work in this project — a request id, a job
id, a ticket key. A line that cannot be attributed to one is nearly useless during an incident,
and that is most of what makes a log hard to read at 2 a.m.

Structured over formatted: a field is queryable, a sentence is not.

```json
{"ts":"…","level":"info","request_id":"…","event":"external.call",
 "system":"tracker","endpoint":"/issue/{key}","status":200,"ms":142}
```

## What never goes in

- **Request and response bodies.** They are where a credential, a customer's data, or a client's
  private ticket text ends up in the log store. Log the method, the endpoint **shape**, the
  status and the latency: when an upstream starts failing, the shape of the failure is what
  matters.
- **Credentials, in any field.** Redaction at the logger is a **net**, not the mechanism — it
  masks the values it was told about, and the one that leaks is the one nobody registered.
- **User content, by default.** If a payload must be logged to debug something, log it behind a
  flag, with a retention shorter than the rest, and say so.

## Errors

An error message names what failed, what was being attempted, and what a human should do. "An
error occurred" and a bare stack trace both fail that test. Include the identifier that lets
someone find the rest of the story.

Never log-and-rethrow at every level: one entry per failure, at the boundary that handles it.

## Metrics

Names are an interface. Renaming one breaks whatever someone built on it, so choose once. Label
by the dimension you will actually filter on, and keep cardinality bounded — a label carrying a
user id or a ticket key will take the metrics store down eventually.

Prefer metrics that reveal a **wrong** state, not merely a busy one: a counter of verifications
that failed, of retries that succeeded, of checks that ran zero cases. A dashboard of throughput
tells you the system is alive, not that it is right.

## "Nothing executed" is not success

A pipeline whose expensive jobs were skipped by a path filter is formally green and verified
nothing. A test run that executed zero tests proved nothing. A check whose upstream returned
`unknown` did not happen. Wherever this project reports a verification result, the reporting code
must distinguish **failed**, **passed**, and **did not run** — and the third must never be
rendered as the second.
