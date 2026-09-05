# ADR 0010 — reading a tracker back, and the one thing it is waiting on

**Status:** accepted · 2026-09-05

## Context

[0005](0005-one-door-out-to-a-tracker.md) opened one door out to Jira — one route, one idea, one
human click, having read what will be sent — and refused the other direction outright. Reading a
tracker *back* was not argued against at length there because nobody had asked for it yet.

They have now, four times, in these words:

- «собери блокеры из jira»
- «проанализируй jira и внеси все блокеры из задач и комментариев в систему»
- «в столбце с идеями/блокерами можно переключить режим на jira таски и перетаскивать и брать их
  в работу»
- «есть задачи в jira — берут в исполнение; задачи в To Do без тега того или иного агента — тоже
  берём в работу»

Four requests over one evening is not somebody testing a boundary. It is a feature this console is
missing, and the last of them is the one that matters most: it is the whole of "agents never idle"
that the kicking loop ([0009](0009-a-session-that-is-not-allowed-to-idle.md)) does *not* cover.
That loop keeps a session going on the project in front of it; it has nothing to say about a
backlog somebody else is maintaining.

## What 0005 was protecting, and whether it applies here

0005's argument is about **writing**: a queue that fills itself has removed the human deciding
something is worth doing, and a backlog nobody chose to fill is a backlog nobody trusts.

Reading is the opposite operation and none of that argument reaches it. A ticket in Jira is
already a decision somebody made, in a system built for making it. Reading it costs that system
nothing, changes nothing in it, and — unlike a session's context — cannot be displaced by being
observed. This is the same asymmetry [0002](0002-read-first-never-interrupt.md) is built on, and
it points the same way: **reading is free; writing is the act that needs somebody standing behind
it.**

So the refusal in 0005 was over-broad, and this document narrows it rather than overturns it. The
door out stays exactly as it is.

## Decision (proposed)

**agent-desk may read a tracker it has been given a link and a credential for**, and:

- **What it reads never becomes an idea.** The pool is a person's notebook
  ([05-ideas.md](../05-ideas.md)), and filling it from a backlog would be
  [0008](0008-an-agent-that-finds-its-own-work.md)'s rejected clause with a different source. A
  ticket read from a tracker is a *task* — the queue's own kind, marked with where it came from,
  counted apart from what a person queued, exactly as `found` is.
- **It reads; it does not tidy.** No transitions, no comments, no assignments, no closing a ticket
  because an agent thinks it is done. The one write that exists is 0005's, unchanged.
- **A blocker read from a ticket is rendered as a fact with its source.** "The ticket says it is
  blocked" is a quotation, not an inference, and it carries the issue key that says so
  (CLAUDE.md, rule five).
- **The credential is a name, never a value.** Same as every other integration here
  ([07-security.md](../07-security.md)): the project's page holds the *name* of an environment
  variable, and `agent_desk/secrets.py` holds the value on this machine only.

## Why this was `proposed` for an hour, and what changed

It was written as a proposal on the grounds that two facts about a live board were missing and
neither was guessable: a credential that had been exercised, and a base URL that was a site rather
than a board.

The second turned out to be **a bug in this repository, not a gap in the world.**
`destination_of` matched only `/browse/DUCK` — the form somebody writes down — and refused the
board URL their browser is showing them when they copy it, which names the same two facts in a
different order. So a link that looked entirely correct produced no destination, the file button
never appeared, and nothing anywhere said why. Both shapes are accepted now.

The first was over-cautious. `file_issue` has shipped since [0005](0005-one-door-out-to-a-tracker.md)
with no recorded Jira response either: it is tested against a stubbed transport, and the question
"does this token work" is a runtime condition it reports honestly rather than a shape it has to
know in advance. The reader is built to exactly that standard and no lower — the parsing is tested
against responses shaped by hand *at the boundary this program controls*, and a body it does not
recognise yields no tickets rather than an exception.

What is genuinely still unknown is whether the DUCK token works, and the console says so in the
one place it matters: an unreadable board queues nothing and logs why, and — this is the part that
took the care — it does **not** clear what it previously knew. An unreadable board must never look
like an empty one.

## What it does, in the order it does it

1. **Reads** the project's unfinished issues, oldest first. Ordered by creation rather than by
   priority: priority is a field people set at different times for different reasons, and "the one
   that has been waiting longest" is a rule that needs no agreement to be fair.
2. **A ticket that says it is stuck does not go in the queue.** An agent started on it would spend
   a worktree discovering what the ticket already says. It is recorded as a blocker instead, with
   the ticket's own sentence quoted and its key beside it — and skipping it silently was never an
   option, because then a board full of blocked work looks exactly like an empty board.
3. **Everything else becomes a task**, marked `tracker`, carrying the issue key, and counted apart
   from what a person queued here. Never an idea: the pool is a person's notebook, and this is
   somebody else's decided work.
4. **Nothing is written back.** No transition, no comment, no assignment, no closing a ticket
   because an agent thinks it is done. A test asserts the reader calls no writer.

The queue still comes first, and exploration still comes last: what a person queued here, then
what their board says, then what an agent would find for itself
([0008](0008-an-agent-that-finds-its-own-work.md)).
