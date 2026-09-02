# ADR 0001 — agent-desk is a separate repository from ai-worker

**Status:** accepted · 2026-09-02

## Context

The two programs share an author, a machine, a stack, a `.claude/` skillset, and the fact that both
read what the `claude` CLI writes. Putting agent-desk inside the ai-worker repository would have
reused a running FastAPI application, an existing console, a Postgres store, an operator login, and
a headless-`claude` adapter already written and tested.

## Decision

Separate repository. agent-desk reuses ai-worker's *patterns* by copying, and shares none of its
code, its database, or its deployment.

## Why

**The domains do not overlap.** ai-worker runs client repositories through a ticket lifecycle on a
server. agent-desk watches the author's own interactive sessions on the author's own laptop. The
shared word is "agent".

**Three of ai-worker's written decisions say no**, and each was made deliberately:

- `docs/17-deferred.md` §18 states that an idea arriving from a chat has no door into the system,
  because a queue that fills itself is a queue nobody trusts. The ideas inbox is that door.
- `docs/15-web-console.md` states the console is for an operator and that a manager needing to open
  it means something upstream failed. A hovering chat contradicts the sentence.
- `docs/21-cti-suite.md` assigns every human-facing message to a sibling agent, and `CLAUDE.md`
  forbids reimplementing a sibling's job.

**The deployment postures are opposite.** ai-worker runs in a container and reaches Postgres.
agent-desk needs the host's `~/.claude/` and `/run/user/<uid>/`, and must work with no daemon
running.

**agent-desk must serve every project at once**, including ai-worker itself. A tool living inside
one of the repositories it watches cannot be pointed at the others without a hack.

**The mechanical proof:** ai-worker's `make verify` runs `scripts/check-api-surface.py`, which fails
on any route not described in its `docs/14-api.md`. The first `/api/blocks` route would turn its
gate red — which is that repository correctly refusing a change it never agreed to.

## Costs accepted

- The headless-`claude` invocation exists in two places and will drift. Accepted: they are ~150
  lines each and want different things — one needs a transcript for evidence, the other needs a
  stream for a UI ([adr/0004](0004-the-transcript-format-is-not-a-contract.md)).
- Two repositories to keep gates green in.
- The `.claude/` skillset is a copy and will fall behind upstream. Mitigated by keeping the
  `.ai-worker/` directory name so an upstream improvement still applies as a patch
  (`CLAUDE.md`, "The skillset").

## Alternative rejected

`experiments/` inside ai-worker, outside `make gate`. Cheaper on day one and wrong by the end of
week one: it still cannot watch the other repositories, and the first person to read that tree has
to be told which half of it is the product.
