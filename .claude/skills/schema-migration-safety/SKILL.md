---
name: schema-migration-safety
description: Database migration discipline — one head, forward-only against a running deployment, two-step for anything destructive, and the constraints and grants that enforce a rule must survive a table rebuild. ACTIVATE whenever a change touches a model or adds a migration, and in `pre-pr-checklist`. Triggers on "add a column", "миграция", "alembic", "prisma migrate", "rails db:migrate". MUST NOT drop a uniqueness constraint, a grant, or a rule that a documented guarantee depends on, and MUST NOT combine an additive and a destructive step in one revision.
metadata: {scope: project, author: ai-worker}
user-invocable: true
disable-model-invocation: false
---

## Rules

1. **One head.** After your revision, the migration tool reports exactly one. Two heads is a
   conflict that surfaces at deploy time, on someone else's machine.
2. **The revision ships with the model change**, in the same branch. A model without its
   migration is a broken deploy waiting for the next person.
3. **Forward-only against a running deployment.** Write `downgrade` honestly — including raising
   where the operation is not reversible — rather than writing a plausible one nobody will run
   and everybody will trust.
4. **Two-step for anything destructive.** Add the new column, backfill, switch the code, then drop
   the old one in a later revision. One revision doing all four cannot be deployed without
   downtime.
5. **Long-running operations are separated.** An index build or a table rewrite on a large table
   blocks writes; use the concurrent variant where the engine has one, and never in the same
   revision as a change the application waits on.

## Constraints that are not ordinary schema

Some constraints exist because they enforce a rule the application cannot enforce reliably:

- a **uniqueness constraint** that makes a retry idempotent;
- a **partial unique index** that makes "only one active X" true rather than hoped for;
- a **grant** that stops a component from writing a table it must not write;
- a **rule or trigger** that makes an audit table append-only.

A migration that recreates such a table must **re-apply these in the same revision**. A table
rebuilt without its constraint is a boundary silently removed, and no test that queries data will
notice. When the project has any of these, list them in the project's documentation so the next
migration author knows what to preserve.

## Checklist before committing a revision

```
heads                      → exactly one
upgrade on an empty DB     → clean
upgrade on a populated DB at the previous revision → clean
constraints / grants / rules on rebuilt tables     → re-applied
downgrade                  → works, or raises with a reason
long operations            → concurrent variant, separate revision
```
