"""Whether an edit to a prompt made it better.

*«За эту смену я трижды правил `classify.kind_prompt` — восемьдесят строк инструкций, которые
решают, поднимется ли агент в воркдире. Проверить, стало ли лучше, было нечем: тесты утверждают
ТЕКСТ промпта, а не его поведение.»*

A test that asserts a prompt contains a sentence proves the sentence is there. It says nothing about
whether the prompt still decides correctly, which is the only thing the prompt is for.

## The set is this console's own history

«В базе уже лежат сотни блоков с тем, что человек напечатал, и с тем, каким видом консоль это
сочла.» Every line anybody has typed into the console is already stored next to what the classifier
made of it. The missing column is what it really was, and some of it is free: a block whose thread a
person set by hand, or whose kind they corrected, is a person having already said. Those become
labels nobody types twice.

## Why it belongs to the console and not to a session

«Измерение промпта стоит десятков вызовов модели, и ни один из них не должен пройти через мой
контекст.» Fifty rows is fifty calls. An agent that ran them itself would spend its window on the
answers rather than on the one number they add up to — and the console is the one place that can
make the calls without anybody watching them go by.

## What it reports

The share that matched and the rows it got wrong, by name. «Итог прогона: доля правильных, и список
тех строк, на которых промпт ошибся» — a number alone says a prompt got worse and not where, and
where is what somebody edits.
"""

from __future__ import annotations

import subprocess
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from agent_desk.answer import classify
from agent_desk.store.repo import Block, BlockKind

# How many rows one measurement runs. Fifty calls is a minute and a few cents; five hundred is
# neither, and a measurement nobody runs measures nothing.
MOST_ROWS = 50

# How much of a line is shown against a wrong answer. Enough to recognise it, and it is a line
# somebody typed into a one-line field.
SHOWN_CHARS = 80


@dataclass(frozen=True)
class Row:
    """One line of the set: what was typed, and what it really was."""

    block_id: str
    said: str
    kind: BlockKind
    # How many cards were on the workbench when it was typed. Part of what somebody said, and the
    # classifier is given it — so a measurement that left it out would be asking a different
    # question from the one the console asks (agent_desk/answer/classify.py).
    #
    # Reconstructed rather than stored: nothing writes the count down, and what a block does keep
    # is the lines the console wrote about what it was sent with. Every one of those that is not
    # an earlier question is a card, which is the same number the classifier was given.
    pointed_at: int = 0


@dataclass(frozen=True)
class Wrong:
    """One row the prompt got wrong."""

    said: str
    wanted: str
    got: str


@dataclass(frozen=True)
class Score:
    """What one measurement found."""

    right: int
    of: int
    wrong: tuple[Wrong, ...] = ()

    @property
    def says(self) -> str:
        if not self.of:
            return "nothing to measure: no line has been labelled yet"
        return f"{self.right} of {self.of}"


def from_history(blocks: list[Block], labels: dict[str, BlockKind]) -> list[Row]:
    """The set, out of what is already stored.

    A label somebody wrote is the truth. Failing that, a block whose thread a *human* set is a
    person having said what it was about, and that is the free half of the set — but only where the
    classifier's own answer is not the thing being checked, so the kind still comes from the label
    table and never from `block.kind`.

    Empty input is left out rather than counted as an easy row: an empty line is not a decision the
    prompt has to get right.
    """
    found = []
    for block in blocks:
        kind = labels.get(block.id)
        if kind is None or not block.input.strip():
            continue
        found.append(
            Row(
                block_id=block.id,
                said=block.input,
                kind=kind,
                pointed_at=_cards_in(block.context or ""),
            )
        )
    return found[:MOST_ROWS]


def _cards_in(context: str) -> int:
    """How many cards a block was sent with, from the lines the console wrote about it.

    `earlier · …` is a previous question in the same thread rather than a card on the bench, and
    counting it would tell the classifier somebody was pointing at something they were not
    (agent_desk/web/blocks.py).
    """
    return len(
        [
            line
            for line in context.splitlines()
            if " · " in line and not line.startswith("earlier · ")
        ]
    )


def already_said(blocks: list[Block]) -> dict[str, BlockKind]:
    """Labels nobody has to type: the blocks a person already corrected.

    «Разметка берётся из уже исправленных блоков: `thread_set_by='human'` и правки вида — это
    готовые метки.» A person who moved a block to a thread by hand said what it was about; the kind
    on such a block is the one that stands after they touched it. That is a label, and asking them
    to give it again is asking them to do the same work twice.
    """
    return {
        block.id: block.kind for block in blocks if block.thread_set_by == "human" and block.input
    }


async def _asks_the_classifier(row: Row) -> str:
    return await classify.kind(row.said, pointed_at=row.pointed_at)


@dataclass(frozen=True)
class Reader:
    """One decision this console makes, and what measuring it would take.

    «`classify.about`, `showing.what_to_show`, `telling.read_shape` принимают решения такой же цены
    и измерены так же — никак. Один механизм, четыре набора.» The mechanism is `measure`, which
    takes the asking function; a reader without an `ask` here is one whose *set* does not exist,
    and saying which is which is the point of the list. A set is labelling somebody does, not code
    somebody writes, and pretending otherwise would put a reader in this list that reports a score
    about nothing.
    """

    what: str
    says: str
    # `None` where the labelled set the screen builds cannot answer this reader's question.
    ask: Callable[[Row], Awaitable[str]] | None = None
    needs: str = ""


READERS: tuple[Reader, ...] = (
    Reader(
        what="kind",
        says="what a typed line is — the decision that starts an agent in a worktree",
        ask=_asks_the_classifier,
    ),
    Reader(
        what="about",
        says="which of the cards in front of somebody a question is about",
        needs="a set of lines with the cards that were on the bench, which blocks do not keep",
    ),
    Reader(
        what="showing",
        says="which list somebody is asking to be shown",
        needs="lines labelled by which list they meant, which this screen does not ask",
    ),
    Reader(
        what="shape",
        says="the drawing a description of a process turns into",
        needs="a set of descriptions with the drawing each should produce",
    ),
)


def reader(what: str) -> Reader | None:
    return next((one for one in READERS if one.what == what), None)


async def measure(rows: list[Row], ask: Callable[[Row], Awaitable[str]] | None = None) -> Score:
    """Ask a reader about every row and count what matched.

    The default goes through `classify.kind`, which is the function the console itself uses. A
    measurement that reimplemented the call would measure a copy of the prompt rather than the
    prompt — and that is the argument for passing the function rather than the prompt.
    """
    asking = ask or _asks_the_classifier
    right = 0
    wrong: list[Wrong] = []
    for row in rows:
        got = await asking(row)
        if got == row.kind:
            right += 1
        else:
            wrong.append(Wrong(said=row.said[:SHOWN_CHARS], wanted=row.kind, got=got))
    return Score(right=right, of=len(rows), wrong=tuple(wrong))


def at_the_commit(root: Path) -> str:
    """Which commit the prompt is at, or "" when nothing could be read.

    Empty is said rather than guessed at: a measurement filed against the wrong commit answers
    "did my edit help" with somebody else's edit (CLAUDE.md, rule five).
    """
    try:
        done = subprocess.run(  # noqa: S603 — a fixed argv, and the only variable is this repo
            ["git", "rev-parse", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            cwd=root,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip()[:40] if done.returncode == 0 else ""


def as_text(score: Score, before: list[tuple[str, str]]) -> str:
    """The answer, and what it was last time.

    «Прогон без истории — это одно число.» A score on its own cannot answer the only question
    anybody runs this for, so the previous ones are on the same page — by commit, because that is
    what the edit was.
    """
    said = [score.says + (" matched what a person said it was." if score.of else "")]
    if score.wrong:
        said.append("")
        said.append("Wrong on:")
        said += [
            f"  “{one.said}” — it said {one.got}, and it was {one.wanted}" for one in score.wrong
        ]
    if before:
        said.append("")
        said.append("Before this: " + "; ".join(f"{was} at {sha[:7]}" for sha, was in before))
    return "\n".join(said)
