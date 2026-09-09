"""Holes in the shape of a drawing (01M1XED1E27MBT3TDAK07P5GSG).

"У схемы есть форма, и в ней видны дыры: у решения одна ветка вместо двух, у действия нет
результата, событие ничего не запускает, шаг ни с чем не связан. Ненавязчивая подсказка рядом, без
единого вызова модели — это структурная проверка, а не мнение."

"Делает конструктор обучающим: человек узнаёт словарь, пользуясь им, а не читая про него."
"""

from __future__ import annotations

import pathlib

import pytest
from agent_desk import process

pytestmark = pytest.mark.unit

CONSOLE = (
    pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "static" / "console.js"
)


def _card(name: str, role: str) -> process.Card:
    return process.Card(name=name, role=role, label=name)


def _line(from_name: str, to_name: str, kind: str = "then", says: str = "") -> process.Line:
    return process.Line(from_name=from_name, to_name=to_name, kind=kind, says=says)


def test_a_decision_with_one_way_out_is_not_a_decision() -> None:
    """It is a step with a question mark on it."""
    cards = [_card("choose", "decision"), _card("next", "action")]
    lines = [_line("choose", "next", "if", "yes")]

    (said,) = process.gaps(cards, lines)["choose"]

    assert "two ways out" in said and "has 1" in said


def test_a_decision_with_two_ways_out_has_no_hole() -> None:
    cards = [_card("choose", "decision"), _card("a", "action"), _card("b", "action")]
    lines = [_line("choose", "a", "if", "yes"), _line("choose", "b", "if", "no")]

    assert "choose" not in process.gaps(cards, lines)


def test_an_action_that_makes_nothing_is_named() -> None:
    cards = [_card("do", "action"), _card("next", "action")]
    lines = [_line("do", "next")]

    assert any("makes" in one for one in process.gaps(cards, lines)["do"])


def test_an_event_that_starts_nothing_is_named() -> None:
    cards = [_card("it happened", "event"), _card("elsewhere", "action")]

    assert any("starts something" in one for one in process.gaps(cards, [])["it happened"])


def test_a_step_joined_to_nothing_is_named() -> None:
    cards = [_card("alone", "action"), _card("elsewhere", "action")]

    assert any("joined to nothing" in one for one in process.gaps(cards, [])["alone"])


def test_two_holes_in_one_card_are_two_things_to_draw() -> None:
    cards = [_card("alone", "decision"), _card("elsewhere", "action")]

    assert len(process.gaps(cards, [])["alone"]) == 2


def test_a_lone_card_on_an_empty_bench_has_no_holes() -> None:
    """Somebody who has just drawn their first card is drawing, not making a mistake, and a console
    that said so would be the nagging this is written to avoid."""
    assert process.gaps([_card("first", "action")], []) == {}


def test_only_steps_are_checked() -> None:
    """An Object is a thing that exists and a Result is what came out. Neither runs, and neither
    owes the drawing a line."""
    cards = [_card("a thing", "object"), _card("what came out", "result")]

    assert process.gaps(cards, []) == {}


def test_it_is_about_lines_where_unfinished_is_about_fields() -> None:
    """A card can be complete and joined to nothing, and a card joined perfectly can have said
    nothing. Two questions, two answers, and neither covers the other."""
    lonely = process.Card(name="alone", role="action", label="alone", said={"do": "something"})
    cards = [lonely, _card("elsewhere", "action")]

    assert "alone" not in process.unfinished(cards)
    assert "alone" in process.gaps(cards, [])


def test_the_hint_is_on_the_card_and_says_all_of_it() -> None:
    """ "Ненавязчивая подсказка рядом." On the card, because that is where the hole is — and every
    sentence, not the first, because two holes are two things to draw."""
    source = "\n".join(
        line
        for line in CONSOLE.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("//")
    )
    start = source.index("function showGaps(")
    body = source[start : source.index("\n}\n", start)]

    assert "pin-wants" in body
    assert "wants.join(" in body
    assert "processSaid.gaps" in body


def test_only_the_cards_somebody_is_drawing_with_are_checked() -> None:
    """A question and its answer are cards on the same surface and their natural roles make them
    steps, but nobody drew them as a process. Telling somebody the conversation they had this
    morning is joined to nothing is exactly the noise that gets a hint like this switched off."""
    cards = [_card("step:one", "action"), _card("block:abc", "event")]

    said = process.gaps(cards, [], ["step:one"])

    assert set(said) == {"step:one"}


def test_no_list_means_every_card() -> None:
    """What a caller with no such list should get, rather than silence."""
    cards = [_card("step:one", "action"), _card("block:abc", "event")]

    assert set(process.gaps(cards, [])) == {"step:one", "block:abc"}
