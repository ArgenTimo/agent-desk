# ADR 0003 — SQLite, one process, no build step

**Status:** accepted · 2026-09-02

## Context

The author's other service runs FastAPI against Postgres in Docker Compose, with Alembic
migrations. Reusing that shape here would be familiar and would need no decisions.

## Decision

One Python process. SQLite through async SQLAlchemy, one file under
`~/.local/share/agent-desk/`. Server-rendered Jinja2 with HTMX and server-sent events. No
container, no daemon, no `npm`.

## Why

**The tool must be running before the work starts, or it will not be used.** It competes with
"just look at the terminal", and every second of startup and every step of setup is paid on every
single day. `make run` must be the whole ritual.

**One writer, one reader, a handful of rows a day.** SQLite is not a compromise at this size; it is
the correct database. What Postgres would add — concurrent writers, network access, a real type
system — is not needed by anything in [`design/02-data-model.md`](../../design/02-data-model.md).

**A container cannot see what this tool exists to see.** `~/.claude/` and
`/run/user/<uid>/cc-socks/` are host state. Bind-mounting them into a container to watch the host
is a fight with the isolation, not a use of it.

**A build step in a local tool is a trap.** The day it breaks — a Node version, a lockfile, a
transitive dependency — the tool is down and the thing it was watching is not. HTMX over the wire
has no such day.

## Consequences

- Migrations are plain SQL applied at startup, in order, recorded in a table. Alembic for a
  single-user file database is machinery without a reason.
- The UI is server-rendered, so every interaction is a request. At this size that is imperceptible,
  and it removes client state as a category of bug.
- Backup is `cp` on one file, which is also the recovery procedure.

## Entry condition for revisiting

A second machine, or a second writer. Both are Phase 4 territory
([09-roadmap.md](../09-roadmap.md)) and neither has a user yet.
