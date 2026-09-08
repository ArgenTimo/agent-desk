"""«Нарисуй ...» asked in the input field (01M1Z9ZZT7WJ…, a child of 01M1X8DA86AJ…).

"Сервис сам определяет что за запрос перед ним… реакция сервиса на каждый вид соответствующая. К
четырём нынешним видам нужны как минимум: «нарисуй», «покажи мне», «сделай из этого вещь»,
«запусти пайплайн»."

Every part of this already existed — `telling.shape_prompt` turns a description into steps and
lines, and the workbench has put those on the bench since 038 — behind a panel somebody had to open
first. This is the same act asked for in the field, which is where the rest of the console is asked
for things.
"""

from __future__ import annotations

import pathlib
import tempfile
from collections.abc import AsyncIterator

import pytest
from agent_desk import telling
from agent_desk.answer import classify
from agent_desk.store.repo import Store
from agent_desk.web import blocks


@pytest.fixture
async def desk() -> AsyncIterator[Store]:
    with tempfile.TemporaryDirectory() as where:
        store = Store(pathlib.Path(where) / "agent-desk.db")
        await store.open()
        yield store
        await store.close()


# --- a kind of its own ---------------------------------------------------------------------------
@pytest.mark.unit
def test_drawing_is_its_own_kind_of_request() -> None:
    assert classify.read_kind("draw") == "drawing"


@pytest.mark.unit
def test_the_classifier_is_told_what_a_drawing_request_looks_like() -> None:
    said = classify.kind_prompt("нарисуй процесс релиза")

    assert "draw" in said
    assert "describing a *process*" in said
    assert "Not a question about a process" in said


@pytest.mark.unit
def test_how_sure_it_has_to_be_depends_on_what_being_wrong_costs() -> None:
    """ "Неправильно понятый вопрос стоит одного лишнего ответа, неправильно понятая просьба
    «сделай проект» стоит пяти агентов. Чем дороже ветка, тем выше должна быть уверенность."

    The two tie-breaks said which way to lean; this says why, so a sixth kind added later is
    weighed on the same scale rather than on how confident the sentence sounded.
    """
    said = classify.kind_prompt("нарисуй процесс релиза")

    assert "what it costs to be wrong" in said
    assert "starts agents in worktrees" in said
    assert "`draw` and `arrange` are cheap" in said


# --- and it makes cards --------------------------------------------------------------------------
@pytest.mark.unit
async def test_a_shape_becomes_step_cards_and_the_lines_between_them(desk: Store) -> None:
    names = await blocks.cards_from_shape(
        desk,
        [
            {"role": "action", "label": "run the tests", "words": "run them"},
            {"role": "decision", "label": "did they pass?", "words": "green?"},
        ],
        [{"from": "1", "to": "2", "kind": "then", "says": "then"}],
    )

    assert len(names) == 2
    assert (await desk.card_roles())[names[0]] == "action"
    assert (await desk.card_fields())[names[0]]["do"] == "run them"
    assert [(one.from_name, one.to_name) for one in await desk.card_ties()] == [
        (names[0], names[1])
    ]


@pytest.mark.unit
async def test_a_step_of_a_kind_this_console_does_not_have_is_left_out(desk: Store) -> None:
    """The roles are five and closed. A shape naming a sixth is a shape this console cannot draw,
    and inventing a role to hold it would be the guess the whole vocabulary exists to prevent."""
    names = await blocks.cards_from_shape(
        desk, [{"role": "wizard", "label": "do magic", "words": ""}], []
    )

    assert names == []


@pytest.mark.unit
async def test_a_line_to_a_step_that_was_left_out_is_not_drawn(desk: Store) -> None:
    """A drawing with a dangling arrow is harder to correct than one with none — the rule
    `telling.read_shape` already follows, kept when the cards are made."""
    names = await blocks.cards_from_shape(
        desk,
        [{"role": "action", "label": "one", "words": ""}, {"role": "wizard", "label": "two"}],
        [{"from": "1", "to": "2", "kind": "then", "says": "then"}],
    )

    assert len(names) == 1
    assert await desk.card_ties() == []


@pytest.mark.unit
async def test_one_answer_to_what_a_drawn_process_becomes(desk: Store) -> None:
    """The panel's route and the input field's branch call the same function. Two copies of it
    were two answers, and the day they differ is the day one description produces two benches."""
    said = (
        pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "routes.py"
    ).read_text(encoding="utf-8")

    assert "block_runs.cards_from_shape(" in said
    assert "add_step_card" not in said[said.index("async def keep_sketch") :][:2000], (
        "the route makes its own cards again"
    )


# --- and the block carries both halves -----------------------------------------------------------
@pytest.mark.unit
def test_the_block_keeps_the_words_and_the_cards() -> None:
    """A block has to be readable by a person scrolling back and applicable by the page. The same
    shape a rearranging answer stores under — which is what makes the shape worth having."""
    stored = telling.as_drawn_json("1. action — run the tests", ["step:a", "step:b"])

    said, cards = telling.read_drawn(stored)

    assert said == "1. action — run the tests"
    assert cards == ["step:a", "step:b"]


@pytest.mark.unit
def test_a_block_that_stored_something_else_draws_nothing() -> None:
    for said in ("", "an ordinary answer", "{}", '{"drawing": null}', "[1]"):
        assert telling.read_drawn(said) == ("", []), said


@pytest.mark.unit
def test_the_page_puts_the_cards_it_listed_on_the_bench() -> None:
    """Stored and never drawn would be a process this console understood and did not show."""
    console = (
        pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "static" / "console.js"
    ).read_text(encoding="utf-8")

    assert "'.drawn-cards li[data-kind]'" in console

    said = (
        pathlib.Path(__file__).resolve().parents[2]
        / "agent_desk"
        / "web"
        / "templates"
        / "_blocks.html"
    ).read_text(encoding="utf-8")
    assert 'class="drawn-cards"' in said
