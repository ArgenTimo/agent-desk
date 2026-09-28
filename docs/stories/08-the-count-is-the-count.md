# 08 · The count under the bench is the count the model sees

[`docs/stories/02`](02-what-a-message-carried.md) closed the gap between what a block *records* it
carried and what the prompt was built from, and left one half open on purpose:

> What the page still cannot do is apply the server's own exclusion, and teaching it that rule
> would be a fourth reading. So the page says what the page sends, and the difference is in the
> record now instead of nowhere.

That was the right call with no number attached to it. Here is the number, counted on the author's
own busiest bench:

| | |
|---|---|
| cards on the bench | 58 |
| what the page sends as targets | **37** — answer cards are already excluded |
| what the model actually sees | **27** |
| the difference | **10**, and all ten are block cards |

So `carrying 37 cards` is over by a quarter, every time, on the bench somebody actually uses. The
number beside the Send button is the one thing on that strip a person reads before pressing it.

## Why the page could not simply subtract them

`on_the_bench` drops a `block` or `answer` card **unless a gesture pointed at it** — dragging one
answer onto another is somebody saying "these two", and a digest that then described neither would
be a digest that cannot be answered. The named pair arrives in its own field, `made_from`, but the
server only looks for it among the targets:

```python
for target in dropped:
    ...
    if kind in ("block", "answer"):
        if name not in named:
            continue
```

So the page had to keep sending every block card in case one of them turned out to be half of a
combine. That is the whole reason the count was wrong, and it is a coupling rather than a rule.

## Who this is

Somebody about to press Send, deciding whether the message is carrying what they meant.

---

## 1 · A card a gesture pointed at is included wherever it came from

> As the server, I want the two cards a combine names to be in the digest because the gesture named
> them, not because the browser happened to also list them.

**Done when** `named` does not have to appear in `dropped`, and a combine of two answers still
describes both.

## 2 · The page stops sending the conversation as things the message is about

> As someone with ten block cards on the bench, I do not want them counted as things I am asking
> about — they are the conversation, and it travels as the thread's history anyway.

**Done when** `cardsBeingCarried` is the set the model sees, so the count and the message agree
without anybody teaching the browser a second copy of the server's rule.

## 3 · And the two halves are checked against each other

> As the next person to change either side, I want a test that fails when they drift.

The two rules live in two languages and two files. Nothing has ever compared them.

**Done when** a test builds a bench of every kind of card, sends it the way the page would, and
asserts the number the page shows equals the number `on_the_bench` produces.

---

## What was deliberately not asked for

**A fourth reading.** Story 02 named that as the disease. This removes a coupling so that the
existing rule can be stated once, on the server, and the page can stop working around it.

**Hiding block cards from the bench.** They are on it because somebody wanted the conversation in
front of them, and the workbench is where this console puts things you are looking at. What changes
is what the message is *about*, not what is on the surface.
