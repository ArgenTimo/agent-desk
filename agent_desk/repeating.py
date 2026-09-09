"""Noticing that somebody has done the same thing three times.

*«Три раза подряд: собрал те же три карточки, задал тот же по форме вопрос, запустил. Консоль
предлагает сохранить это как процесс — уже собранный, с полями, заполненными по тому, что
делалось.»*

The most direct road from "interesting thing" to "I use this every day" is a template nobody had to
sit down and invent. This is the noticing half: what shape a question was, and whether that shape
has happened enough times to be worth offering.

## What "the same" means, and what it deliberately does not

Two questions are the same *shape* when they were asked with the same kinds of card in front of them
and open with the same few words. Not the same cards — the whole point is that the third time was
about a different idea — and not the same sentence, because nobody types a sentence twice.

The words are cut to a handful and lowered, and everything that is a name or a number is dropped.
"Draft a plan for the migration" and "Draft a plan for the reader" are one shape; "Draft a plan" and
"What is it doing" are two.

## Why it only ever offers

An arrangement this console saved by itself is a list somebody did not make, in a place they look
for the lists they did. The offer costs a line above the input field and one press, and the press is
the whole of the decision.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

# How many times before it is worth saying anything. Three is the number the idea names, and it is
# the right one: twice is a coincidence, and four is a person who has already given up expecting
# the console to notice.
ENOUGH = 3

# How many of a question's own words make its shape. Enough to tell "draft a plan" from "what is it
# doing", short enough that the subject of the sentence is not in it.
WORDS = 3

# How far back this looks. A shape somebody used three times last month is not what they are doing
# now, and an offer about it arrives as a non-sequitur.
RECENT = 12

# Anything that is a name, a number or an id: dropped before two questions are compared, because
# the third time is always about a different thing.
_NOISE = re.compile(r"[0-9]+|[A-Za-z]*\d[\w-]*")


@dataclass(frozen=True)
class Shape:
    """What a question was, without what it was about."""

    kinds: tuple[str, ...]
    words: tuple[str, ...]

    @property
    def empty(self) -> bool:
        return not self.words

    @property
    def says(self) -> str:
        """What to call the process this would become, from what was actually done."""
        return " ".join(self.words) or "what I keep doing"


@dataclass(frozen=True)
class Again:
    """A shape that has happened enough times to be worth offering."""

    shape: Shape
    times: int
    # The last question of that shape, in the words somebody typed. What goes into the step this
    # would become — «с полями, заполненными по тому, что делалось».
    asks: str


def shape_of(said: str, context: str) -> Shape:
    """The shape of one question: the kinds of card it was asked with, and how it opens.

    `context` is the lines this console wrote about what the question was sent with, which is where
    the kinds are — `idea · …`, `session · …`. A line saying `earlier · …` is a previous question
    rather than a card, and counting it would make a shape out of how long a conversation was.
    """
    kinds = tuple(
        sorted(
            line.split(" · ", 1)[0].strip()
            for line in context.splitlines()
            if " · " in line and not line.startswith("earlier · ")
        )
    )
    words = tuple(one for one in _NOISE.sub("", said.lower()).split() if one.isalpha())[:WORDS]
    return Shape(kinds=kinds, words=words)


def noticed(asked: Sequence[tuple[str, str]]) -> Again | None:
    """The shape somebody has repeated, or `None`.

    `asked` is the recent questions, newest first, each as what was typed and what it was sent
    with. Newest first because what is offered has to be about what somebody is doing now: a shape
    that has not been used since is not a habit, it is a week in March.
    """
    seen: dict[Shape, list[str]] = {}
    for said, context in list(asked)[:RECENT]:
        shape = shape_of(said, context)
        if shape.empty:
            continue
        seen.setdefault(shape, []).append(said)
    for shape, saids in seen.items():
        if len(saids) >= ENOUGH:
            # The most recent of them: the fields of the offered process are filled from what was
            # done, and the last time is the closest thing to what they would do next.
            return Again(shape=shape, times=len(saids), asks=saids[0])
    return None
