"""The input field is where a pipeline is run and what it is run against
(01M1X8DA934D1KA1MKS18M6Y4M, 01M1ZYJCRNP1PSCJNB0CYZYWWM).

"Весь запуск и ввод происходит из одного места, с поля ввода. То есть пайплайн получает вход не из
формы внутри карточки, а из того, что человек написал внизу — и это же поле его запускает."

Both halves of that sentence, and the second is the reason for the first: running the same shape
against a different input is the whole reason to build one, so the input belongs to the run and not
to a card.
"""

from __future__ import annotations

import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk import process, telling
from agent_desk.answer import classify
from agent_desk.store.repo import Store
from agent_desk.web import blocks, engine, routes

pytestmark = pytest.mark.unit

HERE = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture
async def desk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    yield store
    await store.close()


async def _a_pipeline(store: Store) -> list[str]:
    """Two prompt steps, joined. It touches nothing, so it needs no project."""
    first = await store.add_step_card("summarise")
    second = await store.add_step_card("rewrite")
    for card, asks in ((first, "Summarise this."), (second, "Now rewrite it shorter.")):
        await store.set_card_role(card.name, "action")
        await store.set_card_field(card.name, "asks", asks)
    await store.tie_cards(from_name=first.name, to_name=second.name, kind="then", says="")
    return [first.name, second.name]


# --- the kind ---------------------------------------------------------------------------------------
def test_run_is_one_of_the_kinds() -> None:
    assert classify.read_kind("run") == "running"


def test_it_is_only_possible_where_there_is_a_drawing() -> None:
    """With an empty workbench the same words are a question — the same guard `arrange` has."""
    asked = classify.kind_prompt("прогони это")

    assert "Only when there is a drawing" in asked


def test_the_page_says_what_it_took_the_line_for() -> None:
    assert "run what is on the workbench" in telling.taken_as("running")


# --- the input belongs to the run -------------------------------------------------------------------
async def test_a_run_keeps_what_it_was_started_with(desk: Store) -> None:
    names = await _a_pipeline(desk)

    made, why = await engine.begin(desk, names=names, repo_key="", cwd="", given="the text")

    assert made is not None, why
    assert made.given == "the text"


async def test_the_prompt_is_sent_what_the_run_was_given() -> None:
    card = process.Card(name="step:1", role="action", label="ask", said={"asks": "Summarise."})

    said = engine._asking(card, "a long article", [])

    assert said.index("Summarise.") < said.index("a long article")
    assert "What this run was given" in said


async def test_two_runs_of_one_shape_can_differ(desk: Store) -> None:
    """Which is the whole reason for building a shape rather than asking twice. A field inside a
    card would be the input of one step of one shape, edited in place."""
    names = await _a_pipeline(desk)

    first, _ = await engine.begin(desk, names=names, repo_key="", cwd="", given="one")
    second, _ = await engine.begin(desk, names=names, repo_key="", cwd="", given="two")

    assert first is not None and second is not None
    assert (first.given, second.given) == ("one", "two")


# --- a pipeline needs nowhere to run ------------------------------------------------------------------
async def test_a_drawing_of_prompts_needs_no_project(desk: Store) -> None:
    """It touches neither a repository nor a working directory, which is what its permission means
    rather than describes. Asking where to run it would be asking where to run something that runs
    nowhere."""
    names = await _a_pipeline(desk)

    made, why = await engine.begin(desk, names=names, repo_key="", cwd="")

    assert made is not None, why


async def test_a_drawing_that_does_work_still_needs_one(desk: Store) -> None:
    card = await desk.add_step_card("write the migration")
    await desk.set_card_role(card.name, "action")
    await desk.set_card_field(card.name, "do", "write it")

    made, why = await engine.begin(desk, names=[card.name], repo_key="", cwd="")

    assert made is None
    assert "nowhere to run this" in why


# --- and what the message does ------------------------------------------------------------------------
async def test_an_empty_workbench_says_so_rather_than_failing(desk: Store) -> None:
    thread = await desk.create_thread("a chat")
    block = await desk.create_block(
        thread_id=thread.id, kind="question", input="run it", thread_set_by="human"
    )

    await blocks._run_the_drawing(desk, block, [], [])

    again = await desk.block(block.id)
    assert again is not None
    assert again.kind == "running"
    assert "nothing on the workbench to run" in (again.answer or "")


async def test_the_message_starts_it_with_what_was_typed(desk: Store) -> None:
    names = await _a_pipeline(desk)
    thread = await desk.create_thread("a chat")
    block = await desk.create_block(
        thread_id=thread.id,
        kind="question",
        input="прогони на этом тексте",
        thread_set_by="human",
    )

    await blocks._run_the_drawing(desk, block, [], names)

    (run,) = await desk.runs()
    assert run.given == "прогони на этом тексте"
    again = await desk.block(block.id)
    assert again is not None and "Running the 2 cards" in (again.answer or "")


async def test_a_refusal_is_the_engine_s_own_words(desk: Store) -> None:
    """A button that is offered and a message that is refused must not disagree about why."""
    card = await desk.add_step_card("write it")
    await desk.set_card_role(card.name, "action")
    thread = await desk.create_thread("a chat")
    block = await desk.create_block(
        thread_id=thread.id, kind="question", input="run it", thread_set_by="human"
    )

    await blocks._run_the_drawing(desk, block, [], [card.name])

    again = await desk.block(block.id)
    assert again is not None
    assert "did not start" in (again.answer or "")
    assert await desk.runs() == []
