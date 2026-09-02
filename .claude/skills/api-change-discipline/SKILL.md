---
name: api-change-discipline
description: Rules for adding or changing an HTTP endpoint — compatibility, error shape, idempotency, pagination, and the endpoints a project deliberately does not have. ACTIVATE when touching a route, a request or response schema, or a public contract. Triggers on "add an endpoint", "новый роут", "change the API". MUST NOT repurpose an existing field, and MUST NOT add an endpoint that lets a caller bypass a documented approval or state-transition rule.
metadata: {scope: project, author: ai-worker}
user-invocable: true
disable-model-invocation: false
---

## Compatibility

**Add fields, never repurpose them.** A repurposed field silently changes meaning in every stored
record and every client that already reads it — and it fails nowhere, which is what makes it
expensive.

Removing or renaming: deprecate, ship both, migrate the callers, then remove in a later change.
If the project has no versioning story, that is the finding to raise before the change, not
after.

## Error shape

One shape across the whole surface, machine-readable, with a stable type identifier and a
`detail` that names what a human should do. `problem+json` (RFC 7807) if the project has no
existing convention; the project's existing convention if it has one — consistency beats the
better format.

## Idempotency

Every mutating endpoint that a client might retry honours an idempotency key, and a repeat
returns the original result rather than acting twice. Enforce it with a uniqueness constraint in
the datastore, not with a check-then-insert: the case it protects against is exactly the race
where the check passed.

## Pagination

Cursor, not offset, for anything append-heavy. Offset pagination over a table that grows during
the scan silently skips and repeats rows.

## Endpoints that should not exist

Before adding a route, check it is not one of these wearing a different name:

- one that **records an approval or a sign-off** that is supposed to come from a reviewed
  platform action;
- one that **advances state** which a documented workflow says only a human or a verifier may
  advance;
- one that **returns a credential**. Secrets are write-only: accepted, never read back. Return a
  fingerprint.

The absence of such a route is a feature. Adding it as a convenience for the console is how a
guarantee stops holding.

## Audit

Where the project keeps an audit trail, write the record **before** the action, not after: the
action that fails halfway is precisely the one worth having a record of.

## Keep the contract document in step

If there is an API document, a route added without updating it is a route the next person
implements twice.
