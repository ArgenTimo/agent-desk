"""A card that says which model, and the boundary it must not cross
(01M1XA1V8CNKJE7PNARBCS0D5S).

"Развилка на 2 карточки: Claude Opus и GPT 4.1… Здесь же честная граница: сегодня консоль умеет
звать один движок ответов (плюс локальный, если настроен). Вторая модель — это либо второй
настроенный движок, либо ничего; карточка не должна делать вид, что умеет звать то, чего нет."

The idea wrote its own boundary. A card offering a third engine would be a control that fails when
pressed, which is the failure `allowed.py` exists to prevent wearing a different costume.
"""

from __future__ import annotations

import pathlib

import pytest
from agent_desk import engines, process
from agent_desk.config import Settings
from agent_desk.web import engine

pytestmark = pytest.mark.unit


def _model(value: str) -> process.Card:
    return process.Card(name="step:m", role="object", label="model", said={"what": value})


def _step() -> process.Card:
    return process.Card(name="step:a", role="action", label="ask", said={"asks": "Say something."})


def _into(one: process.Card, other: process.Card) -> process.Line:
    return process.Line(from_name=one.name, to_name=other.name, kind="then")


# --- what this console has -----------------------------------------------------------------------
def test_the_primary_is_always_there() -> None:
    """It is what every block is answered with, and the console says so plainly when it is not
    installed rather than pretending it has none."""
    assert [one.name for one in engines.available()] == ["claude"]


def test_a_second_appears_only_when_somebody_configured_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Not a default: "a local model is a thing you have to have running"."""
    monkeypatch.setattr(engines, "settings", Settings(local_model_bin="/usr/bin/llama"))

    assert [one.name for one in engines.available()] == ["claude", "local"]


def test_an_engine_nobody_configured_is_not_one() -> None:
    assert engines.named("gpt-4.1") is None
    assert not engines.is_an_engine("local")


def test_a_model_card_cannot_ask_for_a_temperature() -> None:
    """`claude -p --output-format stream-json` takes none of those, so a field for one would be a
    box somebody fills in and nothing reads."""
    source = (pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "engines.py").read_text(
        encoding="utf-8"
    )
    fields = {name for name in ("temperature", "max_tokens", "top_p") if f'"{name}"' in source}

    assert fields == set()


# --- and how a step is asked ------------------------------------------------------------------------
def test_a_card_leading_in_chooses_the_engine() -> None:
    """A field on the step would be the wrong shape: the same prompt with two model cards on it is
    two lines on a diagram, and the same prompt with two values in one field is two prompts."""
    model, step = _model("claude"), _step()

    engine_name, why = engine._asked_of(step, [model, step], [_into(model, step)])

    assert why == ""
    assert engine_name == ""


def test_a_step_with_no_model_card_uses_whatever_is_configured() -> None:
    """`None` means "the ordinary list", which is what every drawing without a model card wants."""
    step = _step()

    assert engine._asked_of(step, [step], []) == (None, "")


def test_an_engine_this_console_does_not_have_stops_the_step() -> None:
    """Falling through to the default would compare a thing with itself and give no sign that it
    had — which is the one outcome a harness cannot have."""
    model, step = _model("GPT 4.1"), _step()

    engine_name, why = engine._asked_of(step, [model, step], [_into(model, step)])

    assert engine_name is None
    assert "no engine called" in why
    assert "claude" in why, "it does not say what it does have"


def test_a_card_that_is_not_about_a_model_is_left_alone() -> None:
    """Most cards leading into a prompt are its inputs. One holding an article must not be read as
    a failed attempt to choose an engine."""
    article = process.Card(
        name="step:i", role="object", label="the article", said={"what": "a long text about bees"}
    )
    step = _step()

    assert engine._asked_of(step, [article, step], [_into(article, step)]) == (None, "")


def test_the_run_stops_rather_than_asking_the_wrong_model() -> None:
    source = (
        pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "engine.py"
    ).read_text(encoding="utf-8")

    assert "engine, why = _asked_of(card, cards, lines)" in source
    assert "answer, gone = await _ask(said, engine)" in source


def test_a_named_engine_is_the_only_one_tried() -> None:
    """The fallback exists for an engine that is *unavailable*; a card that asked for one and got
    the other silently is the comparison being wrong without saying so."""
    source = (
        pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "answer" / "session.py"
    ).read_text(encoding="utf-8")

    assert "if engine is not None:\n        engines = [engine]" in source
