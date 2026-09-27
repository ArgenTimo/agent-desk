# 01 · A workbench you can still use when it is full

**Written from the product's own screen, not from its source.** Opened at 37 cards on one bench,
four chat tabs, an agent working in the background. What that looks like is the reason this file
exists: cards sitting on top of each other, labels cut off mid-word with an ellipsis, and no way
to answer the question a person actually has in front of it — *where is the card I put down ten
minutes ago*.

The bench already knows how to be arranged: `Lay it out again`, `Fit everything on screen`,
`Take everything off`, a map, undo, and a slider back to how it was yesterday. Every one of those
is about the bench as a whole. None of them helps with one card among thirty-seven, which is the
thing somebody in front of it is trying to do.

## Who this is

The person who runs this console: one machine, several agents, one screen. They are not
administering anything. They put things on a bench because the bench is where they think, and the
bench filled up because thinking went well.

---

## 1 · Find a card by what it says

> As someone with thirty-seven cards in front of me, I want to type a few letters and be shown
> where the matching cards are, so that I stop panning around hunting for the one I put down ten
> minutes ago.

The idea pool has had `find a thought…` since it had twenty rows in it. The bench has more cards
than the pool has ideas and has nothing.

**Done when** typing in a box narrows the bench to what matches — matching cards stay lit, the
rest go quiet — and clearing the box puts everything back exactly as it was, positions included.
Matching is on what a person can see: the label, the kind, and the words on the card.

## 2 · Read a label that does not fit

> As someone looking at a label cut off mid-word, I want the whole of it without opening the card,
> so that reading the bench costs a glance instead of a click for every card on it.

`.pin-label` is set from `card.label` and carries no `title`. Every card whose label is longer
than its head is unreadable, and there are a lot of them.

**Done when** hovering a clipped label shows the whole of it, and a label that already fits does
not sprout a tooltip repeating itself.

## 3 · Say when a card is underneath another

> As someone who has just dropped a card and cannot see it, I want the bench to tell me it is
> behind something, so that I do not conclude it is gone and put down a second copy.

Cards are placed with collision avoidance, but they are also dragged by hand, restored from a
saved bench and re-laid out — and any of those can leave one card completely covering another.
A covered card is indistinguishable from a card that was never added.

**Done when** the bench says how many cards are hidden and can bring them out, without moving
anything the person arranged on purpose.

## 4 · Work on six of them without losing the other thirty-one

> As someone whose next twenty minutes are about six cards, I want everything else out of the way
> but not gone, so that I can think about the six without taking the rest off and losing the
> arrangement.

Today the only way to reduce what is in front of you is `Take everything off`, which is the
opposite of what this asks: it is destructive, and undo is the only way back.

**Done when** a chosen handful can be held in front and the rest set aside — reversibly, in one
press, with the arrangement untouched.

## 5 · What changed while I was not looking

> As someone who left this bench up while an agent worked, I want to see which cards arrived or
> changed since I last looked at it, so that I can pick up where I left off instead of re-reading
> thirty-seven cards.

Every card already records where it came from and when (`came`, `cameAt`, migration 045). Nothing
reads that as *recently*.

**Done when** coming back to a bench that changed shows what changed, and looking at it is what
clears the mark.

**Narrowed on the way in, and said rather than quietly done.** What shipped marks what *arrived*
while the window was in the background. It does not mark what *changed*, because nothing in this
program records a per-card time of last change — `cameAt` is when the card was made and never
moves. A mark that meant something narrower than it said would be CLAUDE.md's fifth rule broken on
the surface it is most read from, so the mark says "arrived" and the gap is in the pool as its own
thought.

---

## What was deliberately not asked for

**Folding several cards into one.** It is the obvious answer to a crowded bench and it is the
wrong one here: a group is a thing somebody has to name, maintain and remember the contents of,
and `docs/adr/0011` already refused a second surface for the same reason. The bench is crowded
because thirty-seven things are relevant, not because it lacks hierarchy.

**Automatic tidying.** The bench moves under a person's hands and stays where they put it. A
console that rearranged the surface on its own would be a console you fight, which is the
sentence `adr/0011` uses about lines it refuses to reject.

**A second window, a minimap-only mode, a zoomed-out "overview".** `map` is already that.
