# 04 · A flag that still means something

**Counted on the author's own board, with the console up:**

| | |
|---|---|
| rows saying **⚑ may want you** | **34 of 38** |
| of those, interactive sessions a person is in | **0** |
| of those, `--bg` agents | **34** |
| the one session a person was actually sitting in | **not flagged** |

A flag on nine rows in ten is not a flag. It is decoration that costs a person the one glance the
board exists to be worth.

## Why it fires there

[`attention_hint`](../../agent_desk/observe/model.py) is sound and its reasoning is written down:
`idle`, the last transcript entry is the assistant's, and nothing has moved for five minutes. For a
session somebody is sitting in, all three together really do mean *this may be waiting for you*.

For a `--bg` agent they mean something else entirely, and the console knows it — because the console
wrote the sentence itself. [`dispatch.build_task`](../../agent_desk/dispatch.py) tells every agent
it starts:

> you are running in a git worktree of your own and **cannot be asked anything once you start**

A session that cannot be asked anything is a session that cannot be waiting for an answer. When one
of those goes idle after its own last word it has **finished a turn**, which is a different fact,
worth showing, and not the same thing as somebody being needed.

So the inference is not wrong. It is being applied to a kind of session it was never about, and the
result is that the flag which means "look here" is on thirty-four rows where there is nothing to
look at, and on none of the rows where there might be.

This is [`CLAUDE.md`](../../CLAUDE.md) rule five in its subtlest form. Nothing here reports a status
as known — the flag says *a guess, not a signal*, and carries the observation it was made from. What
it does is apply a guess where the premise it rests on is false, which no amount of hedging in the
wording repairs.

## Who this is

Somebody glancing at the board to decide whether to put down what they are doing.

---

## 1 · The flag is for sessions where a person can be asked

> As someone glancing at the board, I want "may want you" only on sessions where somebody could
> actually be waiting on me, so that seeing it means something.

**Done when** a background agent is not flagged as possibly waiting for a human, and the reason is
the one the console itself put in that agent's brief.

## 2 · An agent that has finished its turn says so, in its own words

> As someone with thirty-four idle agents, I want to see that they have stopped, because that is
> genuinely worth knowing — just not under a word that means somebody is needed.

**Done when** an idle background agent reads as having finished rather than as waiting, and the
observation behind it is still there for anyone who wants it.

## 3 · The count at the top means what it says

> As someone reading `34 may want you`, I want that number to be the number of places worth looking.

**Done when** the header count is the flag's count and the flag is worth having.

---

## What was deliberately not asked for

**Deciding whether an agent's work was any good.** "Finished a turn" is a reading of the transcript
and the registry. Whether what it did was right is what the person opening it is for.

**Doing anything about it.** Not starting, not stopping, not kicking. This story is about one word
on a card.

**Making the flag cleverer.** Longer timeouts, heuristics on the last message, asking a model. The
premise was wrong for a whole class of session; the fix is to stop applying it there, not to tune
it.
