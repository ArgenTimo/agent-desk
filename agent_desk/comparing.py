"""The runs of one drawing, read together: what the last two produced, and what all of them said.

"Тестировать пайплайн — значит запускать его несколько раз и смотреть, что изменилось."

"Модель отвечает по-разному. Схема, прогнанная один раз, показывает одну выдачу из распределения, и
решение по ней — это решение по шуму."

Two readings of one history, and this module is the one thing they turned out to be. The first asks
what changed between two runs; the second asks what twenty runs disagreed about. They were built as
two modules, two routes and two buttons that appeared and disappeared together — and both of them
opened the same panel, the second by passing off two of its counted answers as a pair of runs,
which lost the counts and marked no differences at all.

So there is one reading, and a row of it answers both questions: the two columns are the last two
runs, marked word by word, and what the row *says* carries what the whole set did — how many
distinct answers there were, and how many runs did not pass. With exactly two runs that is the
comparison as it always was; with twenty it grows the counting on the end of it.

The history was already there and nothing showed it: every run keeps what each of its steps
produced (`run_step.made`), which is exactly what 036 deliberately does *not* keep on the card —
the card holds the last result, and the runs hold all of them. So this needs no storage: it needs
the reading, and a place to open it.

## What "changed" means here, and what it does not

A step that produced different words is marked changed. That is a fact about two strings and this
module claims nothing beyond it: it does not say the pipeline got better, and it does not say the
difference is caused by the edit somebody made in between. A model asked the same question twice
answers differently, and a comparison that hid that would be worse than none — it would make noise
look like progress.

The counting is held to the same rule. It counts: how many runs reached a step, how many did not
pass, and how many different answers a step gave — commonest first, because "usually this,
sometimes that" is the shape of the finding. It does not average, score or rank. There is no number
that says one prompt is better than another, and inventing one here would be this console making
the judgement somebody ran twenty examples in order to make themselves.

## One run is neither

Fewer than two runs produces no rows at all. One run has nothing to compare and no spread, which is
the same reason the control is not offered until there are two: a table of one column is what a
person presses once and never again.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

# How much of a step's output is shown in a column. Enough to see that two answers differ and
# roughly how; the whole of either is one click away on the step itself.
SAID_CHARS = 400

# How much of an answer identifies it for counting. Two answers that differ past this are two
# answers; two that agree up to it are counted together, which is wrong only for a step whose whole
# output is a long tail — and that step's spread was never going to be readable as a table anyway.
SAME_CHARS = 300


@dataclass(frozen=True)
class Row:
    """One step: the last two runs of it in the columns, and what every run of it produced.

    `reached` is `None` when the row is not about runs at all — the several answers of one card,
    side by side, are the same question asked of a different thing ("here are two texts, what is
    different about them"), so they are the same row and the same panel. A second row would be a
    second answer to "how is a difference shown", and the two would drift.
    """

    name: str
    label: str
    before: str
    after: str
    # Across every run, not only the two in the columns.
    reached: int | None = None
    failed: int = 0
    # Each distinct answer and how many runs gave it, commonest first.
    answers: tuple[tuple[str, int], ...] = ()

    @property
    def changed(self) -> bool:
        return self.before.strip() != self.after.strip()

    @property
    def marks(self) -> list[tuple[str, str]]:
        """The two, word by word, with what changed marked."""
        return differences(self.before, self.after)

    @property
    def says(self) -> str:
        """What happened to this step: between the last two runs, and then across all of them."""
        if self.reached == 0:
            return "no run got here"
        across = self._across()
        return f"{self._between()}; {across}" if across else self._between()

    def _between(self) -> str:
        """The two in the columns, in the words the panel uses.

        "Produced anything" rather than "got here", because an empty column has two causes and
        this row cannot tell them apart: the run stopped before the step, or it reached the step
        and the step failed. What it *can* say is that there is nothing in the column, and how many
        runs did not pass is beside it.
        """
        if not self.before and not self.after:
            return "neither run produced anything"
        if not self.before:
            return "only the second run produced anything"
        if not self.after:
            return "only the first run produced anything"
        return "different" if self.changed else "the same"

    def _across(self) -> str:
        """And the whole set — left out when the two columns already show all of it."""
        if not self.reached or (self.reached <= 2 and not self.failed):
            return ""
        if not self.answers:
            return f"{self.failed} of {self.reached} did not pass"
        counted = ", ".join(str(times) for _answer, times in self.answers)
        said = (
            "every run answered the same"
            if len(self.answers) == 1
            else f"{len(self.answers)} different answers across {self.reached} runs ({counted})"
        )
        return f"{said}, {self.failed} of {self.reached} did not pass" if self.failed else said


@dataclass(frozen=True)
class Spread:
    """Every run of one drawing, as the rows of one table."""

    rows: tuple[Row, ...]
    runs: int
    finished: int

    @property
    def said(self) -> str:
        """The one line above the table. A count and a share, never a verdict: "three of five steps
        differ" is a fact, and "it got better" is not one this program could know."""
        if not self.runs:
            return "nothing has been run yet"
        if self.runs < 2:
            return "one run so far, and two are needed to see what changed"
        return (
            f"{self.finished} of {self.runs} runs finished without a step failing; "
            f"between the last two, {in_a_word(self.rows)}"
        )


# Words, and the spaces between them kept as their own pieces. Splitting on whitespace and
# rejoining with a single space would rewrite the indentation of a code block into one line and
# call the result a difference.
_WORDS = re.compile(r"\s+|\S+")


def differences(before: str, after: str) -> list[tuple[str, str]]:
    """The two texts as one sequence of pieces, each marked with where it belongs.

    "Два ответа, показанные друг под другом с отличиями." Two answers side by side are readable;
    two answers side by side with the changed words marked are *comparable*, which is the thing the
    whole harness is assembled to reach.

    Word by word rather than line by line. Two answers to one prompt are usually the same shape
    with different words in it, and a line diff of those marks every line as changed — which says
    "it is all different" about two texts that differ in three words.

    Three marks: `same`, `before`, `after`. A caller renders the first in both columns and the
    other two in one each; nothing here decides how it looks.
    """
    first, second = _WORDS.findall(before), _WORDS.findall(after)
    found: list[tuple[str, str]] = []
    for what, i, j, k, m in difflib.SequenceMatcher(None, first, second).get_opcodes():
        if what in ("replace", "delete"):
            found.append(("before", "".join(first[i:j])))
        if what in ("replace", "insert"):
            found.append(("after", "".join(second[k:m])))
        if what == "equal":
            found.append(("same", "".join(first[i:j])))
    return [(mark, text) for mark, text in found if text]


def _said(steps: Sequence[object]) -> dict[str, str]:
    return {
        str(getattr(step, "name", "")): str(getattr(step, "made", "") or "")[:SAID_CHARS]
        for step in steps
    }


def _key(said: str) -> str:
    return " ".join(said.split())[:SAME_CHARS]


def over(runs: Sequence[Sequence[object]], labels: Mapping[str, str] | None = None) -> Spread:
    """What every run of one drawing produced, step by step. Newest run first.

    Newest first is the order the store answers in, and the newest run is the drawing as it is now:
    a step somebody added since belongs where they put it, and a step they removed belongs at the
    end rather than in the middle of a shape it is no longer part of. That orders the rows too —
    the newest run's steps in its own order, then whatever only an older run reached.

    Sorting the rows by how often a step was reached would put the steps of a run that failed early
    at the bottom, where they read as unimportant rather than as the place it stopped.
    """
    said = labels or {}
    order: list[str] = []
    reached: dict[str, int] = {}
    failed: dict[str, int] = {}
    answers: dict[str, dict[str, int]] = {}
    total = 0
    finished = 0
    for steps in runs:
        total += 1
        broke = False
        for step in steps:
            name = str(getattr(step, "name", ""))
            if not name:
                continue
            if name not in order:
                order.append(name)
            state = str(getattr(step, "state", ""))
            if state not in ("done", "failed"):
                continue
            reached[name] = reached.get(name, 0) + 1
            if state == "failed":
                failed[name] = failed.get(name, 0) + 1
                broke = True
                continue
            made = _key(str(getattr(step, "made", "") or ""))
            answers.setdefault(name, {})[made] = answers.setdefault(name, {}).get(made, 0) + 1
        if not broke:
            finished += 1
    if total < 2:
        return Spread(rows=(), runs=total, finished=finished)
    after, before = _said(runs[0]), _said(runs[1])
    return Spread(
        runs=total,
        finished=finished,
        rows=tuple(
            Row(
                name=name,
                label=said.get(name, name),
                before=before.get(name, ""),
                after=after.get(name, ""),
                reached=reached.get(name, 0),
                failed=failed.get(name, 0),
                answers=tuple(
                    sorted(answers.get(name, {}).items(), key=lambda one: (-one[1], one[0]))
                ),
            )
            for name in order
        ),
    )


def in_a_word(rows: Sequence[Row]) -> str:
    """The line about the two columns, counted rather than judged for the reason `Spread.said`
    gives — and said on its own by the panel that compares the answers of one card."""
    if not rows:
        return "neither run produced anything"
    changed = sum(1 for row in rows if row.changed)
    if not changed:
        return f"all {len(rows)} steps produced the same thing"
    return f"{changed} of {len(rows)} steps produced something different"
