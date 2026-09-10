# 03 · A board you can still read after the console has been running an hour

**Measured on the author's own machine, with the console up and its loop working.** Not read out
of the source; counted out of the registry the board is built from:

| | |
|---|---|
| rows on the board | **36** |
| of those, in a worktree under `.claude/worktrees/` | **35** |
| in *one* of those directories | **23** |
| sessions this console started and has a task for | **12** |
| live agents it can account for at all | **4** |
| sessions a person is actually sitting in | **1** |
| `claude` processes on the machine | **77** |

[`CLAUDE.md`](../../CLAUDE.md) states the whole promise of this surface: *the point of the tool is
that you can trust the board without opening a terminal.* A board of thirty-six near-identical rows,
thirty-two of which the console cannot say anything about, does not keep that promise — and the one
session the person is sitting in is somewhere in the middle of it.

The triage order is already there and already right ([`routes.board`](../../agent_desk/web/routes.py)
sorts by `triage_rank`). What is missing is not ordering. It is that the board says the same kind of
thing about every row, when it knows quite a lot about the difference between them.

## Who this is

Somebody who left the console running while they did something else, coming back to the question
they always come back with: *what is going on, and what needs me.*

---

## 1 · Mine, and the console's

> As someone opening the board, I want to see at a glance which sessions I am sitting in and which
> are agents this console started, so that thirty-six rows do not read as thirty-six things I might
> have to answer.

The console already knows: it started them, it recorded the agent id, and a dispatched session runs
in `.claude/worktrees/…` while a person's runs in a checkout.

**Done when** the two are distinguishable without reading a path, and the count at the top of a
project says which of the two it is counting.

## 2 · Twenty-three rows for one piece of work read as one piece of work

> As someone looking at twenty-three sessions in one worktree, I want them gathered under the work
> they belong to, so that the length of the board tells me how much is happening rather than how
> many processes exist.

**Done when** several sessions in one directory are one entry that can be opened, and the board's
length is the number of pieces of work.

## 3 · What the console cannot account for, said as that

> As someone whose board shows thirty-six agents where this console started twelve, I want it to
> say so, rather than present all thirty-six as though it knows what they are.

This is rule five in a new place. `idle` and `busy` come from the registry and are facts; *"this is
one of ours"* is a fact for four of the rows and an assumption for the other thirty-two, and the
board renders both identically.

**Done when** a session the console did not start is not presented as one it did, and the number at
the top of a project separates the two.

## 4 · A machine under load says so

> As someone whose machine has seventy-seven agent processes on it, I want the console to mention
> it, because "you can trust the board without opening a terminal" is only true if the board says
> when the terminal would show a problem.

The console already reads the registry every two seconds. The count is free; nothing renders it.

**Done when** an unusual number of live sessions is visible on the board, as a count and never as a
diagnosis — this console does not know *why* there are seventy-seven, and saying it does would be
the same mistake in the other direction.

**Answered by what was already there, and nothing was built for it.** The header has said
`36 sessions` all along; what stories 1 and 3 added beside it — `0 started here` — is the sentence
that actually carries the alarm, because a console answerable for none of the thirty-six is the
fact worth noticing. The seventy-seven processes are not the console's to count: most of them are
the CLI's own spare daemons, which are not sessions and are not in the registry this program reads.

What was rejected here is the threshold. "Unusual" is a judgement, and a console that decided
thirty-six was too many would be putting a diagnosis where [`CLAUDE.md`](../../CLAUDE.md) rule five
allows only a reading.

---

## What was deliberately not asked for

**Stopping anything.** Closing a session throws away what it has not committed and is the one
irreversible thing in this console; [`docs/adr/0012`](../adr/0012-the-one-irreversible-thing.md)
decided how that happens and it is a switch somebody presses per project. Nothing here goes near it.

**Hiding rows.** A board that quietly showed twelve of thirty-six would be a board that is wrong in
a way nobody can see. Gathering is not hiding: what is gathered says how many it gathered.

**Guessing which agent belongs to which piece of work.** The console knows this for the ones it
started and does not for the rest. Rule five: the ones it does not know about say so.
