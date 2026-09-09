"""This has failed like this before.

*«Задача упала с текстом, который почти совпадает с текстом падения на прошлой неделе. Консоль это
видит и говорит: то же самое было тогда-то… Все данные есть: `task.detail` хранится, задачи не
удаляются. Дешёвая функция с эффектом памяти команды.»*

## What it says and what it refuses to say

It says: this failed the same way before, here is when and what that one was called. It does not say
what fixed it. The console does not know that — nobody records "this is what helped" — and a
sentence claiming it would be an invention sitting exactly where somebody is looking for a fact.
What it can do is point at the earlier failure so a person can go and read what happened after it,
which is the honest half and the useful one.

## Nearly, not exactly

Two runs of the same failure rarely produce the same string: a path, a line number, a duration. So
the comparison is `difflib`'s ratio over the words, which is the same tool `ideas/describe.py`
already uses on this kind of text — and the threshold is high, because a console that says "this
happened before" about something that did not is a console whose memory nobody trusts twice.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Sequence
from dataclasses import dataclass

# How alike two failures have to be. High on purpose: the cost of a miss is somebody not being
# reminded, and the cost of a false match is a memory nobody believes again.
ALIKE = 0.82

# How much of a failure is compared. Two stack traces that differ only in their last frame are the
# same failure, and comparing ten kilobytes of them is slow and no more accurate.
MOST_CHARS = 600

# Numbers, paths and times are what differs between two runs of one failure, so they are taken out
# before comparing rather than being allowed to make one look like another.
_NOISE = re.compile(r"(0x[0-9a-f]+|/\S+|\d+)", re.IGNORECASE)


@dataclass(frozen=True)
class Before:
    """A failure that has already happened."""

    id: str
    title: str
    detail: str
    at: int


@dataclass(frozen=True)
class Match:
    """One earlier failure that looks like this one, and how alike they are."""

    id: str
    title: str
    at: int
    alike: float


def _bare(said: str) -> str:
    return " ".join(_NOISE.sub(" ", said.lower()[:MOST_CHARS]).split())


def like_this(detail: str, before: Sequence[Before], *, most: int = 3) -> list[Match]:
    """The earlier failures this one looks like, most alike first.

    An empty detail matches nothing. A failure that said nothing is not evidence that it is the
    same as another failure that said nothing — it is two runs about which the console knows
    equally little.
    """
    said = _bare(detail)
    if not said:
        return []
    found = []
    for one in before:
        theirs = _bare(one.detail)
        if not theirs:
            continue
        alike = difflib.SequenceMatcher(None, said, theirs).ratio()
        if alike >= ALIKE:
            found.append(Match(id=one.id, title=one.title, at=one.at, alike=round(alike, 3)))
    found.sort(key=lambda one: (-one.alike, -one.at))
    return found[:most]
