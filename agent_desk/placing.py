"""Where things go on the workbench, asked for in words.

*"Справа помести все карточки идеи которых интересны простым пользователям, а слева те которые
более интересны разработчикам."*

This is the one kind of request whose answer is neither a new card nor a paragraph: it is a change
to what is already lying there. Nothing is created, nothing is written down, nothing is started —
thirty cards move, and one press puts them back where they were. That is why this is allowed to
guess where most of this program is not: a wrong arrangement costs a press, and a wrong reading of
"make me a project" costs five agents (docs/adr/0006). The cheapness is the argument, and it is
also the reason the way back is built in the same afternoon as the way there.

Two rules hold the reading honest.

**The answer is columns, not prose.** A model asked to arrange things will otherwise describe an
arrangement, and a reader that accepted a description would move nothing while appearing to. The
shape below is strict — a heading, a bar, and the numbers of the cards that go under it — and it
is strict in the same way `answer/classify.py` is strict about a number: a line whose right-hand
side is not *only* numbers is skipped rather than mined for digits, because "developers | see 3 of
the cards above" would otherwise arrange one card and look like an answer.

**A column has a heading.** Without one, "справа эти, слева те" is two piles nobody can name a
minute later, and the heading is the whole difference between an arrangement and a shuffle. So a
column whose heading is empty is not a column and is dropped.

What the model is shown is what a folded card shows: its kind, its name, and the one line under
it. Nothing is opened in order to arrange it.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

# The right-hand side is numbers and separators, and nothing else. Same rule, and the same reason,
# as `classify.read_related`: a number inside a sentence is not an answer.
_NUMBERS = re.compile(r"\A[0-9,\s]+\Z")
# A model answering in a list writes "1. developers | 1, 4". Only that marker comes off the front
# of a heading — stripping digits generally would turn "2026 plans" into "plans".
_MARKER = re.compile(r"\A\d{1,2}[.)]\s+")

# A heading is read at a glance above a column of cards, so it is a few words or it is nothing.
MOST_TITLE = 60


@dataclass(frozen=True)
class Column:
    """One column of the arrangement: what it is called, and which cards are in it."""

    title: str
    cards: list[int]


def columns_prompt(said: str, cards: Sequence[str]) -> str:
    """Ask for an arrangement in a form that can be read rather than interpreted.

    The instruction to leave a card out is the counterpart of `telling.shape_prompt`'s instruction
    against inventing steps. A model told to place everything will place a session card under
    "interesting to ordinary users" rather than admit the request said nothing about it, and an
    arrangement with one confident lie in it is worse than one with a short last column.
    """
    return "\n".join(
        [
            "Somebody has a workbench in front of them with the cards below on it, and has asked",
            "for them to be laid out.",
            "",
            "Answer with one line per column, left to right in the order they asked for, and",
            "nothing else — no prose, no preamble, no explanation:",
            "",
            "  <heading> | <the numbers of the cards that go in it>",
            "",
            "The heading is a few words naming what is in that column, in the language they asked",
            "in. After the bar put card numbers separated by commas and nothing else: a line with",
            "any other words after the bar is thrown away unread.",
            "",
            "A card goes in at most one column. A card the request says nothing about goes in no",
            "column at all — leave it out rather than inventing somewhere for it, and never",
            "invent a card that is not in the list.",
            "",
            "## The cards",
            *[f"{number}. {card}" for number, card in enumerate(cards, start=1)],
            "",
            "## What they asked for",
            said,
        ]
    )


def read_columns(reply: str, count: int) -> tuple[list[Column], list[int]]:
    """The columns a reply describes, and the cards it left out of all of them.

    A card named twice belongs to the first column that claimed it: a card is in one place on a
    bench, and the alternative — the same card drawn in two columns — is a picture of something
    that cannot happen.
    """
    columns: list[Column] = []
    taken: set[int] = set()
    for raw in reply.splitlines():
        head, bar, rest = raw.strip().partition("|")
        if not bar:
            continue
        title = _MARKER.sub("", head.strip()).strip()
        numbers = rest.strip()
        if not title or not _NUMBERS.match(numbers):
            continue
        picked = []
        for part in re.split(r"[,\s]+", numbers):
            if part.isdigit() and 1 <= int(part) <= count and int(part) not in taken:
                taken.add(int(part))
                picked.append(int(part))
        # A column with a heading and nothing under it is a heading, not a column.
        if picked:
            columns.append(Column(title=title[:MOST_TITLE], cards=picked))
    return columns, [number for number in range(1, count + 1) if number not in taken]
