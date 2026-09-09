"""Why a card is where it is, as a chain of facts rather than a sentence about them.

*«Тыкнуть в блокер, в статус, в предложенную ветку, в подсвеченную карточку — и получить не текст,
а цепочку: вот эта задача упала с такой ошибкой, поэтому эта идея не закрыта, поэтому этот блокер
здесь.»*

*«Это ровно то, чего требует пятое правило проекта, доведённое до конца: не просто "не выдавать
догадку за факт", а "на любое утверждение уметь показать, из чего оно следует".»*

## Every step says where it came from

A step is a sentence and the thing it was read out of. That second half is the whole point: a chain
whose steps are only sentences is a paragraph with line breaks, and the person reading it still has
to take the console's word for it. `from_` names a table, a file or a column, so a step somebody
does not believe is a step they can go and check.

## Nothing here computes anything

Every fact was already worked out and thrown away — `came` was written when the card arrived,
`relates_to` when the question was read, `made_from` when two cards were dragged together. This
module turns rows that already exist into sentences, and adds nothing. That is why it is pure: a
chain that had to ask the model why something is on a bench would be the guess this is written
against.

## What is not here

An empty chain. A card nobody can say anything about produces no steps, and the page says so — "it
does not say" is an answer, and an invented reason is the failure the fifth rule names.
"""

from __future__ import annotations

from dataclasses import dataclass

# How much of a remembered sentence travels. Long enough to recognise what was asked, short enough
# that eight of them are a chain rather than a transcript.
SAID_CHARS = 90


@dataclass(frozen=True)
class Step:
    """One fact, and where it can be checked."""

    said: str
    # The row, column or file this was read out of. Never a guess and never a model.
    from_: str


def _short(said: str) -> str:
    words = " ".join(said.split())
    return words if len(words) <= SAID_CHARS else words[: SAID_CHARS - 1] + "…"


def on_the_bench(came: str) -> list[Step]:
    """How this card got onto the workbench, in the words written when it arrived (045).

    Empty `came` produces no step rather than "it got here somehow": a way of making a card that
    does not say leaves the line off, and inventing one here would put a reason on every card
    whether or not anybody knows it.

    The phrase is dropped in whole rather than folded into a sentence. The nineteen ways onto a
    bench are not all the same part of speech — "dropped it on the workbench" and "written down by
    an answer" both read as themselves and neither survives "because somebody …", which is what the
    first version of this said and what the browser showed.
    """
    return [Step(said=f"It is on this workbench — {came}.", from_="bench_card.came")]


def about_an_idea(
    *,
    summary: str,
    source_kind: str,
    parent: str = "",
    asked: str = "",
    state: str = "",
    filed: str = "",
) -> list[Step]:
    """An idea: how it was written down, what it is part of, and what became of it."""
    steps = [
        Step(
            said=f"It was written down as “{_short(summary)}”, {source_kind}.",
            from_="idea.summary, idea.source_kind",
        )
    ]
    if asked:
        steps.append(
            Step(said=f"The message that recorded it said “{_short(asked)}”.", from_="block.input")
        )
    if parent:
        steps.append(Step(said=f"It is a part of “{_short(parent)}”.", from_="idea.parent_id"))
    if state and state != "new":
        steps.append(Step(said=f"Somebody moved it to {state}.", from_="idea.state"))
    if filed:
        steps.append(Step(said=f"It went out as {filed}.", from_="filing"))
    return steps


def about_an_answer(
    *, asked: str, made_from: tuple[str, ...] = (), by_button: bool = False
) -> list[Step]:
    """An answer: the question under it, and the gesture that asked it where there was one."""
    steps = [Step(said=f"It answers “{_short(asked)}”.", from_="block.input")]
    if made_from:
        steps.append(
            Step(
                said="It was made out of " + " and ".join(f"“{one}”" for one in made_from) + ".",
                from_="block.made_from",
            )
        )
    elif by_button:
        steps.append(
            Step(said="It was asked by a button rather than typed.", from_="block.by_button")
        )
    return steps


def about_a_question(*, kind: str, relates_to: tuple[str, ...] = ()) -> list[Step]:
    """A question: what the console read it as, and what it was taken to follow on from.

    The second one is a *reading* and says so. `relates_to` is a short run's guess (051), and a
    chain that presented it as a fact would be the thing this whole file is against.
    """
    steps = [Step(said=f"The console read it as a {kind}.", from_="block.kind")]
    if relates_to:
        steps.append(
            Step(
                said="It was read as following on from "
                + " and ".join(f"“{one}”" for one in relates_to)
                + " — a reading, not a fact.",
                from_="block.relates_to",
            )
        )
    return steps
