# Vision

## The situation

One developer, several Claude Code agents running at once in separate terminals, on one or more
repositories. The agents work well. The developer is the bottleneck — not because the work is
hard, but because the *state of the work* is only visible by looking at it, and looking at it is
serial while the work is parallel.

## Five problems, stated so they can be checked

| # | Problem | Solved when |
|---|---|---|
| 1 | Watching several consoles is continuous manual work | one page answers "what is every agent doing" without opening a terminal |
| 2 | Asking an agent its status interrupts it | the answer to (1) is obtained with **zero** bytes added to any agent's context |
| 3 | Ideas arrive mid-run and pollute the running conversation | an idea can be captured in under ten seconds, into a place that is not any agent's context |
| 4 | The developer loses the thread and stops knowing what to send next | the page shows, per session, the last thing asked and the last thing done, with a timestamp |
| 5 | Non-technical teammates want to contribute ideas and see progress | a read-only, redacted view exists that a non-developer can open — Phase 3 |

Problem 2 is the one that constrains the design. Every other feature must be built so that it does
not violate it: a status board that pings agents for status has solved problem 1 by making problem
2 worse.

## The shape of the answer

**A window that hovers over the work.** Not a browser tab among thirty, not a terminal split. Its
own always-on-top window, showing a board of sessions and a single input field
([06-console.md](06-console.md)).

**Reading is free, writing is expensive.** Claude Code writes its own state to disk — a registry
of live sessions and a transcript per session ([03-session-observation.md](03-session-observation.md)).
Reading them is invisible to the agent. Sending a message to a session is not: it consumes context
and displaces the work in progress. So the tool reads continuously and writes only when a human
clicks ([adr/0002](adr/0002-read-first-never-interrupt.md)).

**A question does not block.** Typing into the input field creates a *block* that goes off and
prepares its own answer while the field is free again. Blocks relate to each other; a follow-up
attaches to its parent, a new subject starts a new thread
([04-threads-and-blocks.md](04-threads-and-blocks.md)).

**An idea is captured, not routed.** Some input is not a question. "Idea A recorded. One-line
summary. Keep it?" — and if kept, it sits in an inbox with actions that produce *drafts*, never
edits to somebody else's repository ([05-ideas.md](05-ideas.md)).

## What this is not

It does not run agents, schedule them, assign them work, or decide anything. It observes and it
remembers. The moment it starts deciding, it needs the whole apparatus that
the ai-worker repository exists to provide — a lifecycle, approvals,
evidence, a sentinel — and it is the wrong tool to grow that in ([adr/0001](adr/0001-a-separate-repository.md)).

## Relationship to ai-worker

Same author, same machine, same skillset in `.claude/`, and deliberately not the same program.

ai-worker is a service that takes a *ticket* on a *client repository* through a *lifecycle* and
hands back a reviewable pull request. Its console exists for an operator, and its own
specification states that a manager who has to open that console means something upstream has
failed.

agent-desk is a local window onto the author's own interactive sessions. No tickets, no clients,
no lifecycle, no approvals. The overlap is that both read what the `claude` CLI emits — which is
one parser, copied deliberately rather than shared ([adr/0004](adr/0004-the-transcript-format-is-not-a-contract.md)).
