# Threads and blocks

The input field is one line at the bottom of the window. What it produces is not a chat log.

## Why not a chat

A chat is a queue: the second message waits for the first answer, and the transcript is a single
line of history. Both properties are wrong here. The developer's questions arrive while agents are
running — "what did the migration end up doing", "is the port thing done", "idea: cache the probe
results" — and they are not a conversation. They are unrelated errands that happen to be typed by
the same person in the same minute.

So: **submitting frees the field immediately.** The question becomes a *block* that prepares its
own answer on its own time, and the next thing can be typed while it does.

## Blocks

A block is one unit of input and whatever it grows into. It has a kind, decided at submission, and
the kind changes what it looks like and what it can do:

| Kind | Shows | Actions |
|---|---|---|
| `question` | the question, then the answer as it streams | retry · follow up · discard |
| `idea` | "Idea recorded. \<one-line summary\>. Keep it?" | keep · discard · edit summary ([05-ideas.md](05-ideas.md)) |
| `observation` | a rendered fact from the board, no model call | pin |

States: `queued → running → answered`, or `failed`, or `cancelled`. A block that fails says why and
offers retry; it does not disappear, because a question that vanished is a question you ask again.

Blocks are independent. Several run at once, in whatever order they finish. Nothing waits.

## Threads

A block belongs to a thread. A thread is a subject.

On submission, the input is classified against the open threads: **continuation of one, or a new
subject.** Continuation attaches the block to that thread, which is what makes "and what about the
other one" work — the block inherits the thread's context.

**The classifier is wrong sometimes, and the design assumes it.** It is a small model call on
short text with no ground truth, and the failure is annoying in both directions: a follow-up
stranded in its own thread loses its context, and a new subject swallowed into an old thread gets
answered against the wrong background.

Two mechanisms, both cheap:

- **A visible, one-click override.** Every question shows the thread it landed in, as a control:
  move it, or split it off. Correcting a misfile costs one click, and after the correction the
  block re-runs against the right context.

  Two boundaries on that sentence, both learned the hard way. The control lists the twenty most
  recent open subjects — one is created per question, so the list grows without limit otherwise —
  **plus the block's own, always, even when it has fallen outside that window**; without the
  exception the control rendered with nothing selected, a browser showed the newest subject as
  the block's, and the button beside it moved the block there. And an *idea* block has no such
  control: moving one would run the thought through the answer engine, which is the second
  question [05-ideas.md](05-ideas.md) says capture never asks.
- **An explicit escape hatch on input.** A leading `/new` starts a thread outright, with no
  classification. When you already know, you should not have to hope.

Threads are never merged automatically. Two subjects that turn out to be one is a judgement, and
the human makes it.

## What a question is answered *from*

A block's answer is produced by a headless `claude -p` run started by this tool, with:

- the thread's previous blocks,
- the board state relevant to it — sessions, their statuses, recent transcript tails,
- read access to the repositories being observed.

It is **not** produced by asking a running session. That would cost the session its context, which
is problem 2 of [01-vision.md](01-vision.md), and the whole reason this tool exists is to answer
"what is going on" without doing that. The one path that does message a session is a human
clicking a button, and it is not this one ([adr/0002](adr/0002-read-first-never-interrupt.md)).

A consequence worth stating: **an answer here can be out of date or wrong about intent.** It is
built from what agents left on disk, not from asking them what they meant. The board is precise
about facts and the blocks are an assistant on top of them; where a block cannot tell, it says so
and names the session to go look at.

## Persistence

Threads and blocks live in the store and survive a restart, because a queued question that a
crash silently ate is worse than one that never accepted the input
([`design/02-data-model.md`](../design/02-data-model.md)). A block that was `running` when the
process died comes back as `failed` with "interrupted" and a retry button — never as `answered`.
