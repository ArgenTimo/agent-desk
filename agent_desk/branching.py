"""Where the cards of an enquiry go, when the enquiry has stopped being a tree.

"2 разные изначально темы могут начать переплетаться далее." Two branches that started apart grow
into each other: an answer that follows on from a card in each of them belongs to both, and from
there the picture is a graph, not a tree.

The lines themselves already cope — they are drawn from card to card and do not care how many
arrive at one. What did not cope is the layout. A bench is laid out in a column per kind, which is
right for a pile of sessions and ideas and wrong for an enquiry: every answer in one column and
every question in another tears a branch in half the moment it is longer than two steps, and the
thing somebody is trying to read — this followed from that, which followed from those two — is the
one thing that arrangement cannot show.

So this lays out by following the lines instead.

## What it is, in three rules

- **Depth is the longest way down to a card, not the shortest.** A card that follows on from two
  branches sits below the deeper of them. Taking the shortest would draw a line upwards from the
  other parent, and an arrow that goes back up a diagram is read as a loop.
- **A card sits under the middle of its parents.** One parent and one child is a straight line
  down, which is what keeps a long branch in one column instead of scattering it; two parents put
  the child between them, which is what a merge looks like.
- **Nothing overlaps.** Within a row the cards are swept left to right and pushed apart, keeping
  the order their parents put them in — so siblings fan out sideways rather than one of them being
  moved to a row of its own.

Pure: no store, no page, no clock. Sizes arrive with the cards because the page is the only thing
that knows how tall a card has drawn itself, and a layout computed against a guessed height is one
that overlaps the moment a card says two lines instead of one.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

# The room between two cards. The lines run through it, and two cards touching leave nowhere for a
# line to be seen — the same reason and the same number the surface uses when it drops a card.
GAP = 26
# The room between one row and the next. Larger than the sideways gap on purpose: this is the gap a
# line crosses with a label on it, and the label needs somewhere to be.
ROW_GAP = 60


@dataclass(frozen=True)
class Card:
    """One card, as the surface knows it: a name, and how big it has drawn itself."""

    name: str
    width: int
    height: int


@dataclass(frozen=True)
class Spot:
    x: int
    y: int


def _known(cards: Sequence[Card], lines: Iterable[Mapping[str, str]]) -> list[tuple[str, str]]:
    """The lines whose both ends are cards being laid out.

    A line to a card that is not here is not an error — it is an answer somebody took off the
    bench, or a card belonging to another chat — and it contributes nothing to where these ones go.
    """
    here = {card.name for card in cards}
    return [
        (str(line["from"]), str(line["to"]))
        for line in lines
        if str(line.get("from", "")) in here
        and str(line.get("to", "")) in here
        and line["from"] != line["to"]
    ]


def _depths(cards: Sequence[Card], joins: Sequence[tuple[str, str]]) -> dict[str, int]:
    """How far down each card is: the longest way to it from a card nothing points at.

    Longest rather than shortest, so a card that follows on from two branches lands below both.
    Computed by relaxing the edges once per card, which is enough for any graph without a cycle and
    is what makes a cycle safe: a loop stops moving after that many passes instead of never.
    """
    depth = {card.name: 0 for card in cards}
    for _ in range(len(cards)):
        moved = False
        for parent, child in joins:
            if depth[child] < depth[parent] + 1:
                depth[child] = depth[parent] + 1
                moved = True
        if not moved:
            break
    return depth


def lay_out(
    cards: Sequence[Card], lines: Sequence[Mapping[str, str]], *, left: int = 40, top: int = 40
) -> dict[str, Spot]:
    """Every card's place, keyed by name. The order of `cards` decides ties, so an arrangement is
    the same twice for the same bench."""
    if not cards:
        return {}
    joins = _known(cards, lines)
    depth = _depths(cards, joins)
    size = {card.name: card for card in cards}
    parents: dict[str, list[str]] = {card.name: [] for card in cards}
    for parent, child in joins:
        # Only the ones above it. A line from a deeper card is a merge seen from the other end, and
        # counting it here would drag the card back up towards something below it.
        if depth[parent] < depth[child]:
            parents[child].append(parent)

    spots: dict[str, Spot] = {}
    middles: dict[str, float] = {}
    y = top
    # The depths that exist, in order, rather than every number up to the largest. Two cards
    # pointing at each other have no honest depth at all — the relaxation above stops them running
    # away but leaves a gap in the numbering — and a row with nothing in it is not a row.
    for level in sorted({depth[card.name] for card in cards}):
        row = [card for card in cards if depth[card.name] == level]
        # Where each would like to be: under the middle of its parents, or — for a card with none
        # above it — out of the way to the right of the ones already wanted here.
        wanted: list[tuple[float, Card]] = []
        for card in row:
            above = [middles[name] for name in parents[card.name] if name in middles]
            wanted.append((sum(above) / len(above) if above else float("inf"), card))
        # `inf` sorts last, which is where a card with no parents belongs: it starts a branch of its
        # own and must not push a merge off the middle of the one it belongs to.
        wanted.sort(key=lambda one: one[0])

        x = float(left)
        for want, card in wanted:
            middle = x + card.width / 2 if want == float("inf") else max(want, x + card.width / 2)
            spots[card.name] = Spot(x=round(middle - card.width / 2), y=y)
            middles[card.name] = middle
            x = middle + card.width / 2 + GAP
        y += max(size[card.name].height for card in row) + ROW_GAP
    return spots
