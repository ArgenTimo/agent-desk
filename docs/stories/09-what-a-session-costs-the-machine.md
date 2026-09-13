# 09 · What a session is costing the machine

**This one arrived by happening.** While this work was going on, the machine ran out of memory
twice and killed a test run and the console itself. The board was open the whole time and said
nothing, because nothing on it is about memory.

[`CLAUDE.md`](../../CLAUDE.md) states the promise: *the point of the tool is that you can trust the
board without opening a terminal.* Measured at that moment:

| | |
|---|---|
| sessions on the board | 30 |
| what they were holding, counted per process | **8.6 GiB** |
| the largest one | 560 MB |
| the smallest | 111 MB |
| what the board said about any of it | nothing |

A card already shows what a session is carrying in tokens — `119k`, "what this session is carrying
right now". This is the same question asked of the machine instead of the model, and the answer is
in a file this program already opens for that process.

## Why this is a reading and not an inference

`observe/registry.py` opens `/proc/<pid>/stat` for every session on every pass — that is the
liveness check [`docs/03-session-observation.md`](../03-session-observation.md) requires, and it is
why a dead session is never shown as busy. `/proc/<pid>/statm` is the file beside it. Reading all
thirty took **1.1 ms**, against the transcript tail this already reads per session.

Nothing about it is derived from silence. It is what the kernel says that process is holding.

---

## 1 · A card says what its session is holding

> As someone whose machine just died, I want to know that the thirty sessions on my board are
> holding eight gigabytes, because that is the fact that explains it.

**Done when** a session card carries the number, beside the one that says what it is carrying in
tokens, and reading it costs what the liveness check already costs.

## 2 · Which one is the expensive one

> As someone with thirty sessions and a decision to make, I want to see which of them is holding
> half a gigabyte, so that closing one is a decision rather than a guess.

**Done when** the number is per session, on the session, so the board's own order and grouping do
the rest.

## 3 · A measurement, never a verdict

> As someone reading `560 MB`, I do not want the console to have an opinion about it.

Whether half a gigabyte is too much depends on the machine, the work and the hour. A console that
coloured it would be putting a judgement where [`CLAUDE.md`](../../CLAUDE.md) rule five allows a
reading — the same argument that stopped [`docs/stories/03`](03-a-board-you-can-still-read.md)
from putting a threshold on the number of sessions.

**Done when** it is shown the way the token count is shown: quietly, in the same shape as every
other fact on the card.

## 4 · A machine that does not answer gets no number invented for it

> As someone on a system where this file is not what this program expects, I want no number rather
> than a wrong one.

**Done when** an unreadable process contributes nothing and the card simply does not carry the
pill.

---

## What was deliberately not asked for

**A total across the board, and this is the interesting one.** Summing what each process holds
counts shared pages once per process: on that machine the sum was **8.43 GiB** while the honest
figure — the proportional set, which counts a shared page once and splits it — was **5.63 GiB**.
The sum overstates by a third.

The honest number is readable (`/proc/<pid>/smaps_rollup`) and costs **274 ms for twenty-nine
sessions against 1.1 ms**, two hundred and fifty times more, on a surface that renders every two
seconds. That is precisely the cost [`docs/stories/05`](05-what-the-console-does-while-nothing-happens.md)
was about removing, and it would be paid to display a number nobody acts on — the actionable one is
per session.

So: no total. A number that needs a sentence beside it to stop it misleading is a number that will
mislead, and the one worth having is on the card.

**A threshold, a colour, or a warning.** See story 3.

**Doing anything about it.** Closing a session throws away what it has not committed and is the one
irreversible thing in this console ([`docs/adr/0012`](../adr/0012-the-one-irreversible-thing.md)).
This story is a number on a card.
