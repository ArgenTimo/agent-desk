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


def from_here(name: str, cards: Sequence[Card], lines: Sequence[Line]) -> tuple[str, ...]:
    """This card and everything downstream of it, in the order they would run.

    "В схеме может быть несколько независимых веток, и запускать хочется ту, над которой сейчас
    думаешь, а не всё сразу."

    Downstream and not upstream. What feeds a step has already happened as far as this branch is
    concerned — its result is on the card — and running it again would be re-doing work in order to
    reach the part somebody actually pressed. A branch that needs its input re-made is started from
    the card that makes it.

    A card nobody has drawn a line from is itself, which is the right answer and not a special
    case: a lone step is a branch of one.
    """
    by_name = {card.name: card for card in cards}
    if name not in by_name:
        return ()
    seen = {name}
    edge = [name]
    while edge:
        here = edge.pop()
        for line in _carrying(lines):
            if line.from_name == here and line.to_name in by_name and line.to_name not in seen:
                seen.add(line.to_name)
                edge.append(line.to_name)
    # In the order the whole drawing runs in, so a branch runs the way it would have as part of it.
    return tuple(one for one in order(cards, lines).steps if one in seen)


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


def gaps(
    cards: Sequence[Card], lines: Sequence[Line], drawn: Sequence[str] = ()
) -> dict[str, tuple[str, ...]]:
    """Holes in the *shape* of a drawing, by card name.

    "У схемы есть форма, и в ней видны дыры: у решения одна ветка вместо двух, у действия нет
    результата, событие ничего не запускает, шаг ни с чем не связан. Ненавязчивая подсказка рядом,
    без единого вызова модели — это структурная проверка, а не мнение."

    The last clause is the whole licence for this. Every rule below is a fact about the lines
    drawn, not a judgement about the work — which is why it can be shown without being asked for,
    and why it says what is missing rather than what would be better.

    `unfinished` is the other half and answers a different question: that one is about fields a
    role asks for, this one is about lines. A card can be complete and joined to nothing, and a
    card joined perfectly can have said nothing.

    A lone card on an empty bench has no gaps. Somebody who has just drawn their first card is
    drawing, not making a mistake, and a console that said so would be the nagging this is written
    to avoid.

    `drawn` is the cards somebody is drawing *with*, and everything else is left alone. A question
    and its answer are cards on the same surface and their natural roles make them steps, but
    nobody drew them as a process — telling somebody that the conversation they had this morning
    is joined to nothing would be exactly the noise that gets a hint like this switched off. Empty
    means every card, which is what a caller with no such list should get.
    """
    if len(cards) < 2:
        return {}
    only = set(drawn)
    out: dict[str, list[str]] = {}
    carries = _carrying(lines)
    for card in cards:
        if card.role not in STEPS or (only and card.name not in only):
            continue
        leaving = [line for line in carries if line.from_name == card.name]
        arriving = [line for line in carries if line.to_name == card.name]
        wants: list[str] = []
        if not leaving and not arriving:
            wants.append("it is joined to nothing, so nothing leads to it and nothing follows")
        if card.role == "decision":
            ways = [
                line
                for line in lines
                if line.from_name == card.name and line.kind in ("if", "when")
            ]
            if len(ways) < 2:
                # One way out is not a decision, it is a step with a question mark on it.
                wants.append(
                    f"a Decision needs two ways out and has {len(ways)}: draw an `if` line for "
                    "each answer"
                )
        if card.role == "action" and not any(line.kind == "makes" for line in leaving):
            wants.append("an Action makes something: draw a `makes` line to what it produces")
        if card.role == "event" and not leaving:
            wants.append("an Event starts something: draw a line to what happens when it does")
        if wants:
            out[card.name] = wants
    return {name: tuple(said) for name, said in out.items()}


@dataclass(frozen=True)
class Walked:
    """One step, as a run would meet it.

    Everything here is worked out from the drawing. `branches` is the one place a dry run has to
    admit it cannot know: a Decision chooses by what it is told at the time, and this can only name
    the ways out of it.
    """

    name: str
    label: str
    role: str
    # What this step would be told about what leads into it — `memory_for`, verbatim.
    told: str
    # The ways out of a Decision, as the words on the lines. Empty for anything else.
    branches: tuple[str, ...]
    # Why a run would get no further than this, or "". The first one that has a reason is where it
    # would stop, and everything after it is what it would never reach.
    stops: str


def walk(cards: Sequence[Card], lines: Sequence[Line]) -> tuple[Walked, ...]:
    """The whole drawing walked through, without running any of it.

    "Нажать «как если бы» — и движок проходит схему до конца: показывает порядок, какие развилки
    выбрал бы, что именно получил бы на вход каждый шаг, и где остановился бы. Ни одного агента, ни
    одного вызова модели, ни одной записи."

    Nothing here is new arithmetic. `order` already says the sequence, `memory_for` already says
    what a step is told, and `roles.missing` already says what a card has not filled in — this puts
    the three side by side in the order they would happen, which is the thing nobody could see
    before without paying for a run.

    A drawing of eight steps could not be checked any other way than by running it and paying. That
    is the difference between a builder somebody is afraid to press and one they try twenty times.
    """
    by_name = {card.name: card for card in cards}
    walked: list[Walked] = []
    stopped = False
    for name in order(cards, lines).steps:
        card = by_name.get(name)
        if card is None or card.role not in STEPS:
            continue
        gaps = roles.missing(card.role, dict(card.said))
        # The first step that cannot run is where a run would stop. Everything after it is listed
        # too and says so, because "and then these four would never happen" is half of what
        # somebody is asking when they press this.
        because = ""
        if stopped:
            because = "a step before this one would have stopped the run"
        elif gaps:
            because = "it has not said: " + ", ".join(gaps)
            stopped = True
        walked.append(
            Walked(
                name=name,
                label=card.label or name,
                role=card.role,
                told=memory_for(name, cards, lines),
                branches=tuple(
                    line.says or line.kind
                    for line in lines
                    if line.from_name == name and line.kind in ("if", "when")
                )
                if card.role == "decision"
                else (),
                stops=because,
            )
        )
    return tuple(walked)


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
