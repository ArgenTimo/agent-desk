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
| `instruction` | "On it — an agent is working on it in \<project\>", or that it is **waiting** for the seat | stop it · start it now · drop it ([adr/0006](adr/0006-the-desk-may-start-work.md)) |
| `master` | "an agent is working on it in agent-desk", or that the code is not on this machine | stop it · record as an idea |
| `observation` | a rendered fact from the board, no model call | pin |

**A request about this console goes to this console.** "Tidy up the ideas", "put a button here"
— `do` pointed at the desk rather than at a project it watches, and the address is the whole
difference. It starts an agent in the console's own checkout, which is the one repository this
program is allowed to change. Where that checkout is not on the machine — an installed copy with
no source beside it — there is nothing to start, so the request is written down as a thought about
the service and says so; that is the only honest answer available, not a fob-off.

**The kind is decided by a run, not by the person typing.** Three things arrive through one field
— "what did the migration do", "cache the probe results", "tell Biba to test it again" — and
asking which of the three it was would be the second question capture is not allowed to ask
([05-ideas.md](05-ideas.md)). So a short run reads the line and says `question`, `idea` or `do`,
and `question` is what an unreadable answer produces: a thought answered as a question loses
nothing, because the text is in the block verbatim and recording it is one click away.

**An instruction is carried out.** The run writes the message and names the project it is for,
from the board it was given, and then an agent starts on it in a worktree of its own
([adr/0006](adr/0006-the-desk-may-start-work.md)). A reply that names no project prepares the
message and asks which one it meant: picking a repository to start work in would be a guess with a
worktree at the end of it.

**And a request is not done until it is done.** Where something this program started is already
running in that project, the work is written into the queue and the block says **waiting** — it
starts when the seat is free, by itself where the project is armed
([adr/0007](adr/0007-a-loop-that-decides-when-not-what.md)) and by a click otherwise. What it does
not do is claim to be finished, or start a second agent in the same repository a minute after the
first.

The message itself is still written down against the session it names, and can still be sent by
hand into a session that is already running — that path has no client and says so, and it is a
second button rather than the answer.

States: `queued → running → answered`, or `failed`, or `cancelled`. A block that fails says why and
offers retry; it does not disappear, because a question that vanished is a question you ask again.

Blocks are independent. Several run at once, in whatever order they finish. Nothing waits.

## Threads

A block belongs to a thread. A thread is a subject.

A thread is a tab in the console, and typing in one is how a human says which subject this is. A
block submitted from a tab is not classified at all and is recorded as `human`: they chose it.
That is the "default and a click" [09-roadmap.md](09-roadmap.md) names as what should replace the
classifier if it ever costs more attention than it saves, and the tabs are that click.

Where no tab is named — a page with no JavaScript, or a submission from somewhere else — the input
is classified against the open threads: **continuation of one, or a new subject.** Continuation
attaches the block to that thread, which is what makes "and what about the other one" work — the
block inherits the thread's context.

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

A block's answer is produced by a headless `claude -p` run started by this tool, with **exactly
what was asked for and nothing else**:

- the cards sitting in the output field when it was sent — one line each, or the whole transcript
  for a card switched to `full`,
- the earlier questions and answers that were attached to it, one at a time, in the order they
  were attached,
- the board state relevant to it — sessions, their statuses, recent transcript tails,
- read access to the repositories being observed, one per session it was pointed at.

Cards from different projects combine: two sessions in two repositories dropped into the output
are two sessions the run is given and two checkouts it may read, which is what makes "how would I
put this one into that one" a question this tool can answer at all.

**Nothing is carried by default**, and the console says what is being carried before it is sent.
A call built from a subject's whole history is a call whose cost nobody can predict and whose
answer nobody can explain; naming what travels makes both obvious. The exception is a page that
cannot name anything — no JavaScript, or a submission from elsewhere — which inherits the thread
it was classified into, and that is what the classifier is for.

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
