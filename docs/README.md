# Documentation map

`docs/` states what must be true. [`../design/`](../design/) states how. `docs/adr/` records the
decisions that had a real alternative, with what that alternative would have cost.

Present tense here is a **requirement on the implementation**, not a description of running code.
Where the code and a document disagree: fix the code, or fix the document in the same commit, or
write an ADR. Never implement the other thing and adjust the prose afterwards.

## Read in this order

| # | Document | What it settles |
|---|---|---|
| 01 | [vision](01-vision.md) | the five problems, and what counts as solving each |
| 02 | [architecture](02-architecture.md) | four components, one direction of data flow |
| 03 | [session observation](03-session-observation.md) | the three sources of truth on disk, and their limits |
| 04 | [threads and blocks](04-threads-and-blocks.md) | why a question does not block, and how blocks relate |
| 05 | [ideas](05-ideas.md) | capture, the card, and what "integrate" is allowed to mean |
| 06 | [console](06-console.md) | the screens, and the overlay window |
| 07 | [security](07-security.md) | credentials, transcript content, and a second pair of eyes |
| 08 | [non-goals](08-non-goals.md) | what v1 does not do, each with its reason |
| 09 | [roadmap](09-roadmap.md) | five phases with a done-when criterion each |
| 10 | [meeting intake](10-meeting-intake.md) | beyond v1 — and the two things the foundation does now |
| 11 | [the plan](11-the-plan.md) | nine pieces of work, in the order they had to happen (finished) |
| 12 | [the tool builder](12-the-tool-builder.md) | what a tool is made of, and what each scenario needs from it |

## Decisions

| ADR | Decision |
|---|---|
| [0001](adr/0001-a-separate-repository.md) | this is a separate repository from ai-worker |
| [0002](adr/0002-read-first-never-interrupt.md) | read always, write only on a human click |
| [0003](adr/0003-sqlite-and-one-process.md) | SQLite, one process, no build step |
| [0004](adr/0004-the-transcript-format-is-not-a-contract.md) | one parser, recorded fixtures, a version check |
| [0005](adr/0005-one-door-out-to-a-tracker.md) | an idea leaves for a tracker through one door, opened by a human |
| [0006](adr/0006-the-desk-may-start-work.md) | this console may start an agent, and what that costs |
| [0007](adr/0007-a-loop-that-decides-when-not-what.md) | a loop decides *when* work starts, never *what* the work is |
| [0008](adr/0008-an-agent-that-finds-its-own-work.md) | an agent may find its own work; nothing lands that the gate refuses |
| [0009](adr/0009-a-session-that-is-not-allowed-to-idle.md) | a switched-on session is kept working, and every bound is a test |
| [0010](adr/0010-reading-a-tracker-back.md) | somebody else's board is quoted, never decided about |
| [0011](adr/0011-the-workbench-is-a-constructor.md) | the workbench builds things: typed cards, typed lines, an engine that queues |
| [0012](adr/0012-the-one-irreversible-thing.md) | this console may close a session, and only with all four conditions true |

## Keeping this map honest

Seven ADRs and one document went missing from these tables between 0004 and 0011, because each was
added by a commit that was thinking about the decision rather than about the index. An index that
has fallen behind is worse than none: it is a list that reads as complete.

So: **a new document or ADR is not finished until it is in the table above**, in the same commit.
There is no test for this — the check is the review — and this paragraph is the reason to do it
anyway.

## The one sentence

Reading a session costs nothing; writing to one costs its context. Everything else in these
documents follows from that.
