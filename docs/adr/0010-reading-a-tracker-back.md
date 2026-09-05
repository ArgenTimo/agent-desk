# ADR 0010 — reading a tracker back, and the one thing it is waiting on

**Status:** proposed · 2026-09-05

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

## Why this is `proposed` and not `accepted`

Because it cannot be finished tonight, and shipping the half that can be written would be worse
than shipping nothing.

**What is missing is not code.** It is two facts about a live board, and neither is guessable:

1. **A working credential.** The token recorded for DuckyFlow has not been exercised against the
   API, and the one thing worse than no integration is one that fails silently at three in the
   morning and reports an empty backlog as a quiet one.
2. **A base URL that is an API base.** What is linked today is a *board* URL — the thing a browser
   opens — and not `https://<site>.atlassian.net`, which is what a client needs. The difference is
   invisible until the first request 404s.

Writing a reader against a shape nobody has seen is exactly what
[0004](0004-the-transcript-format-is-not-a-contract.md) exists to stop: the fixtures in this
repository are recorded from real responses, and there is no recorded Jira response here to record
them from.

## What to do about it, in order

1. Put a working API token in the environment under the name the project's page states, and change
   the DuckyFlow link to the site's base URL rather than the board's.
2. Record one real response from `/rest/api/3/search` into `tests/fixtures/`, scrubbed the way
   every other fixture there is.
3. Then this ADR moves to `accepted` and the reader is written against that fixture.

Until step 1, the four ideas above stay in the pool with this document as the reason. That is the
honest state, and it is one decision away from not being.
