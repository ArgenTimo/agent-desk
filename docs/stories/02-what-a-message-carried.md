# 02 · A record of what a message carried that you can trust

**Found by reading the console's own data, not its source.** The largest message in this store
records that it carried **96 things**. Twenty-two of those lines are distinct; seventy-four are
copies of something already in the same list, and one idea appears twelve times. The pool that
those lines name contains each of those ideas exactly once.

[`docs/04-threads-and-blocks.md`](../04-threads-and-blocks.md) is why that matters: *a block that
cannot say what it carried is a block whose answer cannot be explained afterwards.* A block that
says ninety-six when two dozen went is worse than one that says nothing, because somebody will
reason from it.

## The shape of it

There are **three readings of "what this message carries"**, and they disagree:

| where | what it counts | how |
|---|---|---|
| the count beside the field | `.pin` minus a few classes | no `[data-kind]`, keeps `.own` |
| what the block records | one line per target, walked | no de-duplication, keeps `block` cards |
| what the model is shown | `on_the_bench` | de-duplicated, `block` and `answer` dropped |

Only the third is right, and it is the only one nobody can see. Proven against the code as it
stands: given the same four targets with one repeated twice, the record says four lines and the
prompt is built from two cards.

Each of the three was written for a good reason and none of them is wrong on its own. What is
wrong is that there are three.

## Who this is

The same person as story 01, a week later, looking at an answer they no longer remember asking
for and trying to work out why it said what it said. The record is the only thing they have.

---

## 1 · The record is what actually went

> As someone explaining an answer a week later, I want "carried N things" to be what the model was
> actually shown, so that the record I reason from is not a different reading from the one that ran.

**Done when** the recorded lines are derived from the same reading the prompt was built from, so
that the two cannot drift again — not when both have been separately taught to de-duplicate.

## 2 · It does not list what was deliberately left out

> As someone reading `block · no longer on the board` in a message's record, I want the record not
> to name things the prompt dropped on purpose.

A block card and an answer card are the two halves of one exchange, already in the prompt as the
thread's history; `on_the_bench` leaves them out for that reason and says so. The record lists
them anyway, and on this console it lists them as *missing*, which reads like something went wrong.

**Done when** a card the prompt left out is not in the list of what was carried.

## 3 · The number beside the field is the number that will be sent

> As someone about to press Send, I want the count under the bench to be the count the message
> will actually carry.

`carrying 37 cards` is computed from a different selector than the one that builds the targets,
and both are computed from a different rule than the one that builds the prompt.

**Done when** the count and the targets come from one place, and a change to what is carried can
only be made in that place.

**Narrowed, and said rather than quietly done.** The browser's one reading is now `cardsBeingCarried`
and both the count and the field ask it. What it cannot do is apply the server's rule — a block card
is sent as a target and dropped by `on_the_bench`, and teaching the page that rule would be a fourth
reading, which is the disease this file is about. So the page's number is what the page sends, and
the difference is no longer silent: story 2 puts it in the record, in words.

## 4 · What was left out, and why

> As someone reading a record, I want to see what was left out as well as what went in, because
> "why did it not know about X" is the other half of "why did it say that".

`looking.Look` already carries `left_out`. Nothing that a person can see reads it.

**Done when** the record says both halves, in the console's own words.

## 5 · A long record is readable

> As someone opening a record of two dozen things, I want it grouped by kind rather than two dozen
> flat lines, so that "what was this about" is answerable at a glance.

**Done when** opening `carried …` on a large message shows its shape before its detail.

---

## What was deliberately not asked for

**A fourth reading that reconciles the other three.** That is the disease, not the cure.

**Storing the prompt itself.** It is the obvious way to make the record exact and it is the wrong
one here: the prompt holds transcript text, and `docs/07-security.md` keeps transcript content out
of any second store. The record names what was carried; it does not copy it.

**Counting tokens.** What a message *cost* is a different question with a real answer already on
the board (`$0.00 today`), and a second estimate beside it would be a guessed status wearing a
number — [`CLAUDE.md`](../../CLAUDE.md) rule five.
