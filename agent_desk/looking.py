"""What the model is shown when it is asked about the workbench.

*«Подсвети те, которые принесут доход» невозможно исполнить, зная только `idea:01M1X…`. Нужна
компактная и полная выжимка того, что лежит на верстаке — что за карточка, что на ней написано, с
чем связана — в форме, которую дёшево отправлять и по которой можно однозначно указать на карточку
в ответе.*

Until now a question carried a *list of names*. `idea:01M1XC4YZHPE076JTH5BCXMD9W` says that an idea
is on the bench and nothing else — not what it is about, not that it is joined to the session below
it, not that four of the fourteen cards are the same investigation. So a request about the cards
themselves could not be answered at all, and the ones that looked answered were answered from the
question's wording rather than from the bench.

Three things this has to get right, and they pull against each other.

**Complete.** Every card, what kind it is, what is written on it, and what it is joined to. A
digest that quietly drops the cards it could not describe produces an answer about eleven cards
presented as an answer about fourteen — a guess wearing the shape of a fact, which is the failure
CLAUDE.md's fifth rule is about. So nothing is dropped silently: what does not fit is counted and
the count is in the text.

**Compact.** This is sent on every question asked with cards in front of it, so it is one line per
card and a trimmed sentence, not a document. A bench is something a person arranged by hand, so the
budget is generous by the standards of a bench and small by the standards of a prompt.

**Pointable.** The model has to be able to say *which* cards it means, and a ULID copied back by a
language model is a ULID that will sometimes come back with a character changed — resolving to
nothing, or worse, to something. So each card carries a number and the answer is asked for in
numbers, which is the convention this repository already uses for the sessions a directive can be
addressed to (`answer/session.py`) and for the ideas a request is about (`answer/classify.py`).

Reading those numbers back out of an answer is deliberately not here. Nothing acts on them yet, and
a parser with no caller is a parser nobody has ever run — it belongs in the commit that gives the
model's answer somewhere to land, together with the test that proves the round trip.

Pure: no store, no clock, no model call. What is on the bench is gathered where the store is, and
this module decides only how it is shown and how the answer is read back.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

# One line per card, and this is the line. Long enough for a sentence that says what a card is,
# short enough that sixty of them are still a paragraph rather than a document.
SAID_CHARS = 160

# How many cards are described. Past this the bench is not a thing somebody arranged, and a prompt
# that grew without bound would fail at the far end rather than here — see `Look.left_out`, which
# is why going over it is visible rather than silent.
MOST_CARDS = 60


@dataclass(frozen=True)
class OnBench:
    """One card, as the console knows it, before it is given a number.

    `said` is what is written on the card — an idea's own words, the sentence a pass wrote about a
    session, what a step is told. `role` is what it is in a process, when somebody has said.
    """

    name: str
    kind: str
    label: str
    said: str = ""
    role: str = ""


@dataclass(frozen=True)
class Seen:
    """One card as the model is shown it: everything of `OnBench`, plus its number."""

    at: int
    name: str
    kind: str
    label: str
    said: str
    role: str


@dataclass(frozen=True)
class Joined:
    """One line between two cards, by the numbers the model can see rather than by name."""

    frm: int
    to: int
    says: str


@dataclass(frozen=True)
class Look:
    cards: list[Seen]
    joins: list[Joined]
    # Cards there was no room for. Never nothing when some were cut: an answer about the bench has
    # to know it was not shown all of it.
    left_out: int = 0

    @property
    def empty(self) -> bool:
        return not self.cards


def _trim(said: str) -> str:
    """One line, to the budget. Whitespace collapsed, because a card's text has newlines in it and
    a digest that is one line per card has to actually be one line per card."""
    flat = re.sub(r"\s+", " ", said).strip()
    return flat if len(flat) <= SAID_CHARS else flat[: SAID_CHARS - 1].rstrip() + "…"


def look(cards: Sequence[OnBench], ties: Sequence[tuple[str, str, str]]) -> Look:
    """Number the cards, and restate the lines between them in those numbers.

    `ties` are `(from_name, to_name, says)`. A line with an end that is not on the bench is left
    out rather than drawn to nothing — the same rule the workbench diagram follows, and for the
    same reason: a relation to something the reader cannot see explains nothing.
    """
    kept = list(cards)[:MOST_CARDS]
    seen = [
        Seen(
            at=number,
            name=card.name,
            kind=card.kind,
            label=_trim(card.label) or card.name,
            said=_trim(card.said),
            role=card.role,
        )
        for number, card in enumerate(kept, start=1)
    ]
    at = {card.name: card.at for card in seen}
    joins = [
        Joined(frm=at[frm], to=at[to], says=says)
        for frm, to, says in ties
        if frm in at and to in at
    ]
    return Look(cards=seen, joins=joins, left_out=max(0, len(cards) - len(kept)))


def as_lines(look_: Look) -> list[str]:
    """The digest, as the lines that go into a prompt.

    The instruction about numbers is in here rather than in the prompt builder because it is only
    true when this section is present, and an instruction to answer in numbers that arrives with no
    numbered list is an instruction to invent some.
    """
    if look_.empty:
        return []
    lines = [
        f"These {len(look_.cards)} cards are on the workbench in front of the person asking.",
        "Each one has a number. When your answer is about particular cards, name them by number "
        "and by nothing else — never quote a card's text back as its name.",
        "",
    ]
    for card in look_.cards:
        role = f" ({card.role})" if card.role else ""
        lines.append(f"{card.at}. {card.kind}{role} — {card.label}")
        if card.said and card.said != card.label:
            lines.append(f"   {card.said}")
    if look_.left_out:
        # Said out loud, because an answer about "everything on the bench" that was given eleven of
        # fourteen cards is wrong in a way nobody can see from the answer.
        lines += [
            "",
            f"There are {look_.left_out} more cards on the workbench that did not fit here. Say so "
            "if that changes your answer.",
        ]
    if look_.joins:
        lines += ["", "Lines somebody has drawn between them:"]
        lines += [f"  {join.frm} {join.says} {join.to}" for join in look_.joins]
    return lines
