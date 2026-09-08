"""A prompt with places in it, and the cards that fill them
(01M1XA1V8H8JRY8EQCW3662FBR, 01M1XA1V8234H5H655FY9CPKCC).

"Промпт — это шаблон, а не текст: в нём места, куда подставляется то, что пришло по связям. Без
слотов схема из пяти карточек — это пять отдельных промптов, которые надо править по одному."

"Карточка ввод… Именованное значение, которое подставляется дальше по цепочке. Это то, что делает
схему переиспользуемой: поменял ввод — прогнал ту же схему заново."

Neither is anything on its own: a value nothing substitutes is a note, and a slot with nothing to
fill it is a prompt with a brace in it.
"""

from __future__ import annotations

import pathlib

import pytest
from agent_desk import process, slots
from agent_desk.web import engine

pytestmark = pytest.mark.unit


def _card(label: str, made: str = "", **said: str) -> process.Card:
    return process.Card(name=f"step:{label}", role="object", label=label, said=said, made=made)


# --- the slots ---------------------------------------------------------------------------------------
def test_a_slot_is_filled_from_the_card_of_that_name() -> None:
    filled = slots.fill("Summarise {the article}.", {"the article": ["a long text"]})

    assert filled.said == "Summarise a long text."


def test_braces_that_are_not_a_slot_are_left_alone() -> None:
    """A prompt about JSON is full of braces, and a pattern that matched `{"key": 1}` would eat the
    example somebody was asking about."""
    said = 'Answer like {"key": 1} and nothing else.'

    assert slots.fill(said, {}).said == said
    assert slots.names_in(said) == ()


def test_a_slot_nothing_fills_is_left_standing_and_named() -> None:
    """A prompt that quietly lost `{the article}` ran against nothing and answered confidently; one
    that still says it is visibly about the wrong thing."""
    filled = slots.fill("Summarise {the article}.", {})

    assert "{the article}" in filled.said
    assert filled.left == ("the article",)


def test_a_name_on_two_cards_is_named_rather_than_resolved() -> None:
    """Silently picking one is how a pipeline produces the wrong answer for a week."""
    filled = slots.fill("Use {input}.", {"input": ["first", "second"]})

    assert filled.said == "Use first."
    assert filled.twice == ("input",)


def test_the_same_slot_twice_is_one_name() -> None:
    assert slots.names_in("{a} and {a} and {b}") == ("a", "b")


# --- what a card offers ---------------------------------------------------------------------------
def test_a_card_offers_what_it_produced() -> None:
    assert slots.values_from([_card("summary", made="one line")]) == {"summary": ["one line"]}


def test_a_card_that_has_not_run_offers_what_it_says() -> None:
    """An input card has no work to do, and its value is what somebody typed into it. Both are the
    same thing to the prompt downstream, which is why an input card needs no kind of its own."""
    assert slots.values_from([_card("the article", what="a long text")]) == {
        "the article": ["a long text"]
    }


def test_what_it_produced_beats_what_it_says() -> None:
    """A step that has run is a fact and a step that has only been described is a plan — the same
    order `process.memory_for` already puts them in."""
    offered = slots.values_from([_card("x", made="the result", what="the plan")])

    assert offered == {"x": ["the result"]}


def test_a_card_with_no_name_offers_nothing() -> None:
    """There would be no way to write the slot."""
    assert slots.values_from([_card("")]) == {}


def test_a_card_with_nothing_in_it_offers_nothing() -> None:
    assert slots.values_from([_card("empty")]) == {}


# --- and in a prompt step ----------------------------------------------------------------------------
def test_a_prompt_step_is_filled_from_what_leads_into_it() -> None:
    article = _card("the article", what="a long text")
    step = process.Card(
        name="step:ask", role="action", label="ask", said={"asks": "Summarise {the article}."}
    )
    line = process.Line(from_name=article.name, to_name=step.name, kind="then")

    said = engine._asking(step, "", [], [article, step], [line])

    assert said.startswith("Summarise a long text.")


def test_only_what_leads_into_it() -> None:
    """A card sitting elsewhere on the bench is not an input to this step, and filling from it
    would make the lines decorative."""
    elsewhere = _card("the article", what="a long text")
    step = process.Card(
        name="step:ask", role="action", label="ask", said={"asks": "Summarise {the article}."}
    )

    said = engine._asking(step, "", [], [elsewhere, step], [])

    assert "{the article}" in said
    assert "still empty" in said


def test_the_slots_are_filled_before_anything_is_written_about_the_prompt() -> None:
    source = (
        pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "engine.py"
    ).read_text(encoding="utf-8")
    start = source.index("def _asking(")
    body = source[start : source.index("\n\n\n", start)]

    assert body.index("slots.fill(") < body.index("What this run was given")
