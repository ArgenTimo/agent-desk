"""Several runs of one drawing, and what they disagreed about.

"Модель отвечает по-разному. Схема, прогнанная один раз, показывает одну выдачу из распределения, и
решение по ней — это решение по шуму." And, the same machinery from the other end: *"Один пример
ничего не говорит о промпте… прогон схемы по каждой строке, с таблицей результатов и долей
прошедших проверок. Это то место, где «поиграться» превращается в «померить»."*

Two ideas and one thing. Running a drawing twenty times with the same input and running it once per
line of a set are the same act with a different list of inputs — so there is one mechanism, and the
difference is what is handed to it.

## What a spread says, and what it refuses to say

It counts. How many runs got to each step, how many finished, and how many different answers a step
gave — with the commonest first, because "usually this, sometimes that" is the shape of the finding.

It does not average, score or rank. There is no number that says one prompt is better than another,
and inventing one here would be this console making the judgement somebody ran twenty examples in
order to make themselves.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

# How much of an answer identifies it. Two answers that differ past this are two answers; two that
# agree up to it are counted together, which is wrong only for a step whose whole output is a long
# tail — and that step's spread was never going to be readable as a table anyway.
SAME_CHARS = 300


@dataclass(frozen=True)
class Step:
    """One step, across every run of the drawing."""

    name: str
    label: str
    reached: int
    failed: int
    # Each distinct answer and how many runs gave it, commonest first.
    answers: tuple[tuple[str, int], ...] = ()

    @property
    def says(self) -> str:
        if not self.reached:
            return "no run got here"
        many = len(self.answers)
        said = "every run answered the same" if many == 1 else f"{many} different answers"
        if self.failed:
            return f"{said}; {self.failed} of {self.reached} did not pass"
        return said


@dataclass(frozen=True)
class Spread:
    steps: tuple[Step, ...]
    runs: int
    finished: int

    @property
    def said(self) -> str:
        """The one line above the table. A count and a share, never a verdict."""
        if not self.runs:
            return "nothing has been run yet"
        return f"{self.finished} of {self.runs} runs finished without a step failing"


def _key(said: str) -> str:
    return " ".join(said.split())[:SAME_CHARS]


def over(runs: Iterable[Sequence[object]], labels: dict[str, str] | None = None) -> Spread:
    """What several runs of one drawing produced, step by step.

    Each run arrives as its steps. The order of the steps is the order the first run reached them
    in, which is the drawing's own order — sorting by how often a step was reached would put the
    steps of a run that failed early at the bottom, where they read as unimportant rather than as
    the place it stopped.
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
    return Spread(
        runs=total,
        finished=finished,
        steps=tuple(
            Step(
                name=name,
                label=said.get(name, name),
                reached=reached.get(name, 0),
                failed=failed.get(name, 0),
                answers=tuple(
                    sorted(answers.get(name, {}).items(), key=lambda one: (-one[1], one[0]))
                ),
            )
            for name in order
        ),
    )
