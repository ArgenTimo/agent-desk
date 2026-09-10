# 07 · A question that was never asked

**Found in the author's own store, not in the source.** One message has been sitting in `queued`
for **forty-five hours**:

    queued  45.0h old  kind=question  "Make one thing out of these two. Say what having them to…"

[`docs/04-threads-and-blocks.md`](../04-threads-and-blocks.md) makes the promise this breaks:

> A block never disappears on failure — a question that vanished is a question you ask again.

It did not vanish. It is worse than that: it is on the page, in a state that reads as *about to
happen*, and it never will. A person looking at it waits.

## Why it happens, and why nothing catches it

A block is created `queued` and the same request then starts the run that moves it on
(`runs.start`). If the process dies in that window — a restart, a crash, a kill — nothing ever
picks it up again. Searched: **no code anywhere reads a `queued` block.** The only thing that looks
at block states on startup is `Store._recover_interrupted`, and it says:

> A `queued` block is left queued: it never started, and nothing about it is lost by running it
> now.

The reasoning is sound and the second half is a promise nothing keeps. *Running it now* is
something no code does. The comment describes an intention; the state it produces is a message that
will sit there until somebody deletes it by hand.

## Who this is

Somebody who asked a question, saw it accepted, and came back later. There is nothing on the page
telling them the difference between "still working" and "will never work".

---

## 1 · A message this process will not run says so

> As someone whose question has been queued since Tuesday, I want the console to tell me it is not
> going to happen, so that I stop waiting for it.

The console already has the shape for this: `_recover_interrupted` settles a `running` block as
`failed` with `interrupted` as its reason, and a settled block gets a `retry` button and a sentence
saying what stopped and what would change it.

**Done when** a block that was queued and never started is settled on the next start, under a
reason that says which of the two happened — because "it was interrupted mid-answer" and "it never
began" are different facts and the second one costs nothing to re-ask.

## 2 · And it says what to do about it, like every other stop

> As someone reading it, I want the sentence, not the runner's words.

`telling.stopped` turns a failure into what happened and what would change it, from a list of the
failures this program can actually produce — and everything else keeps its own words, because
inventing a next step for a failure nobody has seen is the guess rule five forbids. This is a
failure this program can produce, so it belongs on the list.

**Done when** the page says it in the console's own words and offers the one press that fixes it.

## 3 · The comment stops describing an intention

> As the next person to read `_recover_interrupted`, I want its docstring to describe what the code
> does.

**Done when** the sentence "nothing about it is lost by running it now" is either true or gone.

---

## What was deliberately not asked for

**Running them on startup.** A console that woke up and fired every question queued since Tuesday
would be a burst of model calls nobody asked for, at the moment the person is least expecting to
pay for one — which is the thing [`docs/adr/0007`](../adr/0007-a-loop-that-decides-when-not-what.md)
exists to prevent. And a question asked two days ago may not be a question any more.

**A new block state.** The vocabulary is five words and closed. `failed` with a reason is the shape
this console already uses for "it stopped and here is why", and the reason is where the difference
belongs.

**Noticing it while running.** A block queued for ten minutes with nothing running it is stranded
too, but "nothing is running it" is not something the store can see — it would be an inference from
silence, and the restart is a fact.
