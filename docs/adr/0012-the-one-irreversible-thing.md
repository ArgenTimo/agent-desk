# ADR 0012 — the one irreversible thing this console can do

**Status:** accepted · 2026-09-09

## Context

Everything this console does can be taken back. A card off the bench comes back with undo; an idea
marked done is a row with a different word in it; a task that failed is retried from its own card;
a branch that would not merge is still a branch. That is not an accident of implementation — it is
why the workbench can be *tried*, and it is the argument behind
[0011](0011-the-workbench-is-a-constructor.md).

Closing a session is not like that. `claude stop` ends a process, and whatever that process had not
committed is gone. There is no row to change back and no press to undo it.

The pool asked for it anyway, and was right to:

> «Закрывать сессию с потерянной канарейкой автоматически — со своим переключателем и проверкой…
> Закрытие сессии выбрасывает то, что она не закоммитила. Это единственное необратимое действие во
> всей консоли, и решение о нём должно приниматься с открытыми глазами, а не заодно с кнопкой.»

A session whose canary is lost has rolled past its brief. It is not doing the work any more, it is
occupying a seat, and on a machine running four of them that seat is the resource. The half that
costs nothing — flag it, and offer to start a fresh one carrying the work forward — was built first
and deliberately left as the whole of it.

## Decision

This console may close such a session, and only when **all four** of these are true:

1. **The project has been switched on for it.** Its own switch, off by default, beside the two in
   [0008](0008-an-agent-that-finds-its-own-work.md) — not folded into either of them, because
   "start what I queued" and "close something" are not the same permission.
2. **The canary is lost**, on a session this console started and told to sign. An unsigned reply
   from anybody else's session means nothing at all (`023-canary.sql`).
3. **The checkout is clean**, read with `git status` in the session's own directory. A checkout
   that cannot be read counts as not clean.
4. **It has been idle for half an hour.** Not "idle": the status field cannot tell *finished* from
   *between two turns of the same thing*, and the wait is what makes "let it finish and commit"
   real time rather than a race.

The reading in (3) is the whole safety argument. It is also allowed: reading a repository is what
this program does, and CLAUDE.md's second rule is about writing.

## What the alternatives would have cost

**Not building it.** The seat stays occupied until somebody notices. That is what happens today and
it is survivable — which is why this was a separate idea rather than an unfinished one.

**Building it without the switch.** A console that closed sessions on a machine nobody armed is the
failure [0008](0008-an-agent-that-finds-its-own-work.md) exists to prevent, wearing a canary as an
excuse.

**Building it without the reading.** One closure that threw away an afternoon's uncommitted work
would end the feature and take the trust in everything else with it. The reading costs one
subprocess per switched-on project per tick, and only where somebody pressed the switch.

**Committing on the session's behalf first.** Tempting, and refused: committing is a judgement about
what the work *is*, and this program does not write into an observed repository (CLAUDE.md, rule
two). A commit nobody wrote a message for is worse than a session left running.

## Consequences

- `agent_desk/tidying.py` holds the decision and is pure: it is given four readings and answers,
  with the reason it said no. It can be tested without a machine, which is the point.
- The panel says all four conditions before the switch is pressed, and says the other half when it
  is off: closing a session stays something a person does in the terminal that has it.
- Nothing else in this console acquires the ability to close anything. If a second caller ever wants
  it, this document is where the argument starts again.
