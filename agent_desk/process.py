"""A bench of typed cards and typed lines, read as a process: what runs, in what order, on what.

From the first user's feedback: *"Result одного шага должен быть входом для следующего, иначе
схема из пяти блоков — это пять независимых запросов. Память процесса — это то, что делает
последовательность последовательностью."*

That is exactly right, and it is the whole of this module. Five cards joined by four arrows are
five separate questions unless something carries what came out of one into the next. What follows
is the reading that does it — and it is deliberately *only* the reading. Nothing here starts an
agent, writes to a store or looks at a clock. It takes the cards, the lines and whatever the steps
have already produced, and answers three questions:

- **what order** do these run in (`order`);
- **what feeds** a given step (`feeding`);
- **what does that step get told** (`memory_for`).

Everything that acts is somewhere else, and it will ask these three functions. Keeping them pure
is not tidiness: a process engine whose ordering can only be observed by running agents is an
engine nobody can test, and this project has a rule about that (`docs/adr/0004`, about a different
file, for the same reason).

## What "feeds" means, exactly

A line carries something into a step when it is `then`, `if`, `when` or `makes` — the four that
say something happens. `with` does not: it says two things are related in no particular order, and
treating it as a feed would make every loosely-associated card on the bench part of every step's
input, which is how a context window fills up with things nobody meant.

## Cycles

A person drawing a process will draw a loop, on purpose and by accident. `order` returns what it
can put in order and names the rest rather than hanging or guessing at a sequence: a step in a
cycle has no "before", and inventing one would produce a run whose order nobody chose.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from agent_desk import roles

# The lines that carry something forward. `with` is deliberately absent — see the docstring.
CARRIES = ("then", "if", "when", "makes")

# The roles that are steps: something has to happen at them. An Object is a thing that exists and
# a Result is what came out; neither is executed, and both are read by the steps around them.
STEPS = ("action", "decision", "event")


@dataclass(frozen=True)
class Card:
    """One card as this module needs it: what it is, what it says, and what it produced."""

    name: str
    role: str
    label: str = ""
    said: Mapping[str, str] = field(default_factory=dict)
    # What this card produced the last time anything ran it. Empty until something has.
    made: str = ""


@dataclass(frozen=True)
class Line:
    """One typed line between two cards."""

    from_name: str
    to_name: str
    kind: str
    says: str = ""


@dataclass(frozen=True)
class Order:
    """The steps in the order they can run, and the ones that have no order.

    `tangled` is not an error to be shown once and dismissed — it is the part of the drawing that
    cannot be run, and it stays named until somebody unpicks it.
    """

    steps: tuple[str, ...]
    tangled: tuple[str, ...]

    @property
    def runnable(self) -> bool:
        return bool(self.steps) and not self.tangled


def _carrying(lines: Sequence[Line]) -> list[Line]:
    return [line for line in lines if line.kind in CARRIES]


def order(cards: Sequence[Card], lines: Sequence[Line]) -> Order:
    """The order these cards run in: what comes first, and what has no first.

    A standard topological pass, and the two decisions in it are about what to do when the drawing
    does not describe a sequence.

    **A card nothing points at starts.** That includes a lone card on a bench with no lines at
    all, which is the ordinary state of a process somebody has just begun drawing.

    **Ties are broken by the order the cards were given.** Two steps that could equally run first
    would otherwise come out in whatever order a set iterated, and a process that runs in a
    different order on two identical benches is a process nobody can reason about.
    """
    here = {card.name for card in cards}
    carried = [line for line in _carrying(lines) if line.from_name in here and line.to_name in here]

    waiting_on: dict[str, set[str]] = {name: set() for name in here}
    feeds: dict[str, list[str]] = {name: [] for name in here}
    for line in carried:
        if line.to_name not in waiting_on[line.to_name] and line.from_name != line.to_name:
            waiting_on[line.to_name].add(line.from_name)
            feeds[line.from_name].append(line.to_name)

    given = [card.name for card in cards]
    settled: list[str] = []
    ready = [name for name in given if not waiting_on[name]]
    while ready:
        name = ready.pop(0)
        settled.append(name)
        for after in feeds[name]:
            waiting_on[after].discard(name)
            if not waiting_on[after]:
                # Back in the order they were given, so the result does not depend on when a card
                # happened to become ready.
                ready.append(after)
                ready.sort(key=given.index)

    tangled = tuple(name for name in given if name not in settled)
    return Order(steps=tuple(settled), tangled=tangled)


def feeding(name: str, cards: Sequence[Card], lines: Sequence[Line]) -> tuple[Card, ...]:
    """The cards that flow into this one, in the order they were given.

    One hop, not the whole ancestry. A step is told what leads directly into it; carrying the
    entire graph would put the first card of a twelve-step process into the briefing of the last,
    which is how a context window fills with things nobody meant. What the earlier steps
    contributed reaches here through what the step in between *made*, which is the point of
    keeping a result at all.
    """
    by_name = {card.name: card for card in cards}
    into = {
        line.from_name
        for line in _carrying(lines)
        if line.to_name == name and line.from_name in by_name
    }
    return tuple(card for card in cards if card.name in into)


def memory_for(name: str, cards: Sequence[Card], lines: Sequence[Line]) -> str:
    """What this step is told about what came before it.

    The text that goes into a briefing, and the shape of it is the argument. Each card that feeds
    this one contributes what it *is* and, where there is one, what it actually **made** — and the
    made part is written last and labelled, because a step that has run is a fact and a step that
    has only been described is a plan. A briefing that presented the two identically would let an
    agent act on a result that does not exist yet.
    """
    said: list[str] = []
    for card in feeding(name, cards, lines):
        role = roles.role_of(card.role).says
        said.append(f"- {role}: {card.label or card.name}")
        for one in roles.fields_of(card.role):
            words = (card.said.get(one.name) or "").strip()
            if words:
                said.append(f"  {one.says}: {words}")
        if card.made.strip():
            said.append(f"  what it produced: {card.made.strip()}")
    if not said:
        return ""
    return "What leads into this step:\n" + "\n".join(said)


def unfinished(cards: Sequence[Card]) -> dict[str, tuple[str, ...]]:
    """Which cards have not said the things their role needs, by card name.

    What an engine would stop on, gathered before it starts rather than discovered halfway
    through a run with three agents already going.
    """
    short = {}
    for card in cards:
        gaps = roles.missing(card.role, dict(card.said))
        if gaps:
            short[card.name] = gaps
    return short


def ready_to_run(cards: Sequence[Card], lines: Sequence[Line]) -> str:
    """Why this drawing cannot be run yet, or an empty string.

    One function so that whatever offers the button and whatever refuses the run give the same
    answer — the same argument as `autostart.why_not`, which exists because a console that says
    one thing and does another is worse than one that does nothing.
    """
    if not any(card.role in STEPS for card in cards):
        return "nothing here is a step: a process needs an Action, a Decision or an Event"
    walked = order(cards, lines)
    if walked.tangled:
        return f"{len(walked.tangled)} card(s) are in a loop, so there is no order to run them in"
    short = unfinished(cards)
    if short:
        first = next(iter(short))
        return f"{len(short)} card(s) have not said what they need — starting with {first}"
    return ""
