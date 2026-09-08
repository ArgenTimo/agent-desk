"""One prompt, two models, one card (01M1XA1V8QT3ART00VEQQMWCKB).

"Так как модели 2, то из промпта 2 выхода — 2 карточки с результатами… Это главный примитив
харнесса: без него сравнение двух моделей означает две одинаковые схемы рядом, которые расходятся
при первой же правке."

The divergence is the argument. Two drawings that are meant to be the same drawing agree only until
somebody edits one, and the edit that matters is the one being tested.
"""

from __future__ import annotations

import pathlib

import pytest
from agent_desk import engines, process
from agent_desk.config import Settings
from agent_desk.web import engine

pytestmark = pytest.mark.unit


def _model(value: str) -> process.Card:
    return process.Card(
        name=f"step:m{value}", role="object", label=f"model {value}", said={"what": value}
    )


def _step() -> process.Card:
    return process.Card(name="step:a", role="action", label="ask", said={"asks": "Say something."})


def _into(one: process.Card, other: process.Card) -> process.Line:
    return process.Line(from_name=one.name, to_name=other.name, kind="then")


# --- how many engines a step is asked ---------------------------------------------------------------
def test_two_model_cards_ask_two_engines(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engines, "settings", Settings(local_model_bin="/usr/bin/llama"))
    step = _step()
    first, second = _model("claude"), _model("local")
    cards = [first, second, step]

    asked, why = engine._asked_of(step, cards, [_into(first, step), _into(second, step)])

    assert why == ""
    assert [one.name for one in asked if one] == ["claude", "local"]


def test_the_same_model_twice_is_one_engine() -> None:
    """Two cards saying "claude" is somebody drawing, not a fan of one model against itself."""
    step = _step()
    first, second = (
        _model("claude"),
        process.Card(name="step:m2", role="object", label="also claude", said={"what": "claude"}),
    )

    asked, _ = engine._asked_of(
        step, [first, second, step], [_into(first, step), _into(second, step)]
    )

    assert len(asked) == 1


def test_no_model_card_is_one_unnamed_engine() -> None:
    """Which is every drawing that is not a harness, and it must go on working exactly as it did."""
    step = _step()

    assert engine._asked_of(step, [step], []) == ([None], "")


# --- what the step produces --------------------------------------------------------------------------
def test_two_answers_are_labelled_by_who_gave_them() -> None:
    """An unlabelled pair is a comparison nobody can read, and the labels are what the next step and
    the run comparison both see — so which model said what survives past the moment."""
    said = engine.as_a_fan([("claude", "the first answer"), ("local", "the second")])

    assert "## claude" in said
    assert "## local" in said
    assert said.index("the first answer") < said.index("## local")


def test_one_answer_is_itself() -> None:
    """A heading over a single result would be a heading about nothing."""
    assert engine.as_a_fan([("answer", "just this")]) == "just this"


def test_it_is_one_card_and_not_two_drawings() -> None:
    """The whole point: the result of a fan is the step's own `made`, so editing the prompt edits
    what both models were asked."""
    source = (
        pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "engine.py"
    ).read_text(encoding="utf-8")

    assert "answer = as_a_fan(answers)" in source
    assert "await store.card_made(card.name, answer[:MOST_MADE])" in source


def test_half_a_comparison_stops_the_step() -> None:
    """A step that reported one of two answers as its result would say so nowhere."""
    source = (
        pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "engine.py"
    ).read_text(encoding="utf-8")
    start = source.index("        answers: list[tuple[str, str]] = []")
    body = source[start : source.index("answer = as_a_fan(answers)", start)]

    assert "return 1" in body, "a failure in one engine does not stop the step"
