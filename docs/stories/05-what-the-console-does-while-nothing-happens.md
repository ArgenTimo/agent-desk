# 05 · What the console does while nothing is happening

**Measured on the author's own console, with nobody touching it:**

| every two seconds | |
|---|---|
| work done **on the event loop** | **184 ms** — nine per cent of it |
| conversation HTML rendered and thrown away | **862 KiB** |
| ideas and blockers rendered and thrown away | 32 KiB |
| how much of that output differed from the tick before | **none of it — byte for byte** |
| the board, in a thread | 193 KiB · 375 ms |

The stream is careful about the *network*: it holds the previous HTML and pushes only what changed
([`sse.board_events`](../../agent_desk/web/sse.py)), which is why a page sitting still receives a
heartbeat and nothing else. What it is not careful about is the *work*. Every two seconds the whole
conversation is built out of the store, formatted, and compared against an identical string, and
then dropped.

Three of the four are built with no thread under them. [`CLAUDE.md`](../../CLAUDE.md) names this as
one of the two async mistakes that hurt most here — *blocking IO in an async path stalls the whole
console* — and one hundred and eighty-four milliseconds in every two seconds is a ninth of the loop
that serves every request, every other stream and every run.

And it grows with the conversation. A hundred and twenty blocks cost this much; nothing bounds the
number of blocks.

## Who this is

Anybody with the console open — which, for this tool, is anybody using it at all. The symptom is
not a crash. It is that the machine is busier than the work on it, and every other thing the
console does waits behind it.

---

## 1 · Do not build an answer to find out the question has not changed

> As someone with the console open and nothing happening, I want it to notice that nothing happened
> without assembling a megabyte of HTML to prove it.

The store already knows: a block has `created_at` and `finished_at`, and a conversation that has
not gained or settled a block cannot have changed.

**Done when** a tick over an unchanged store does not render the conversation, and the first tick
after something changes still pushes it.

## 2 · What must be built anyway is built off the loop

> As someone waiting for a page while a tick is running, I want the tick not to be in front of me.

The board already goes through `asyncio.to_thread`. The other three do not, and they are most of
what is left.

**Done when** nothing on this path holds the event loop for the length of a render.

## 3 · The cheap check cannot be cheaper than it is honest

> As someone whose answer just arrived, I want to see it on the next tick and not one after.

A staleness check that misses a change is worse than no check: a console that shows an answer two
ticks late is a console people reload, and reloading is what this stream exists to remove.

**Done when** the check is derived from what the store already records, and the thing it guards is
rendered whenever the check cannot be sure.

---

## What was deliberately not asked for

**A longer poll interval.** It would divide every number here by the same factor and make the
console slower to notice things. The work is wrong, not its frequency.

**Rendering fewer blocks.** A conversation you cannot scroll back through is a different product.
If the number of blocks on the page needs a bound, that is a decision about the product and belongs
in a story of its own, not smuggled in as a performance fix.

**Caching the HTML by hand, in a dictionary, next to the one the stream already keeps.** The stream
holds the previous render to decide what to *push*. A second copy held to decide what to *build*
would be two answers to "what is current", which is the shape of mistake
[`docs/stories/02`](02-what-a-message-carried.md) was entirely about.
