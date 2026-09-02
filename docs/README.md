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
| 09 | [roadmap](09-roadmap.md) | four phases with a done-when criterion each |

## Decisions

| ADR | Decision |
|---|---|
| [0001](adr/0001-a-separate-repository.md) | this is a separate repository from ai-worker |
| [0002](adr/0002-read-first-never-interrupt.md) | read always, write only on a human click |
| [0003](adr/0003-sqlite-and-one-process.md) | SQLite, one process, no build step |
| [0004](adr/0004-the-transcript-format-is-not-a-contract.md) | one parser, recorded fixtures, a version check |

## The one sentence

Reading a session costs nothing; writing to one costs its context. Everything else in these
documents follows from that.
