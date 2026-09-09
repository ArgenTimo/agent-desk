"""Two answers, one under the other, with the differences marked
(01M1XA1V906B3KRJ84G4KHRE33).

"Два ответа, показанные друг под другом с отличиями — это то, ради чего собирают такую схему. Всё
остальное в этом наборе — способ до этого экрана добраться."

The idea was marked `decide`, and the decision was where this screen lives. It is the panel that
already compares two runs: the question is the same one asked of different things — here are two
texts, what is different about them — and a second panel would be a second answer to "how is a
difference shown", which would drift from the first.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk import comparing
from agent_desk.store.repo import Store
from agent_desk.web import engine, routes

pytestmark = pytest.mark.unit

CONSOLE = (
    pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "static" / "console.js"
)


@pytest.fixture
async def desk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    yield store
    await store.close()


# --- what "with the differences" means ---------------------------------------------------------------
def test_the_words_that_changed_are_marked() -> None:
    marks = comparing.differences("the quick brown fox", "the slow brown fox")

    assert ("before", "quick") in marks
    assert ("after", "slow") in marks
    assert ("same", " brown fox") in marks


def test_it_is_word_by_word_and_not_line_by_line() -> None:
    """Two answers to one prompt are usually the same shape with different words in it, and a line
    diff marks every line as changed — which says "it is all different" about two texts that differ
    in three words."""
    marks = comparing.differences("one two three", "one four three")

    assert [text for mark, text in marks if mark == "same"] == ["one ", " three"]


def test_whitespace_is_kept_as_it_was() -> None:
    """Splitting on whitespace and rejoining with a single space rewrites a code block into one
    line and calls the result a difference."""
    marks = comparing.differences("a\n    b", "a\n    b")

    assert "".join(text for _mark, text in marks) == "a\n    b"


def test_two_texts_that_are_the_same_have_no_marked_pieces() -> None:
    marks = comparing.differences("the same", "the same")

    assert {mark for mark, _text in marks} == {"same"}


def test_a_row_carries_its_own_marks() -> None:
    row = comparing.Row(name="a", label="a", before="one", after="two")

    assert ("before", "one") in row.marks


# --- reading a fan back ------------------------------------------------------------------------------
def test_the_answers_come_back_out_of_what_the_step_produced() -> None:
    made = engine.as_a_fan([("claude", "the first"), ("local", "the second")])

    assert engine.read_a_fan(made) == [("claude", "the first"), ("local", "the second")]


def test_one_answer_that_begins_with_a_heading_is_not_a_fan() -> None:
    """A reader that thought so would show somebody a comparison of one thing against the rest of
    its own prose."""
    assert engine.read_a_fan("## Summary\nit went well") == []


def test_a_plain_answer_is_not_a_fan() -> None:
    assert engine.read_a_fan("it went well") == []


# --- the route -----------------------------------------------------------------------------------------
async def test_a_card_with_two_answers_compares_them(desk: Store) -> None:
    card = await desk.add_step_card("ask")
    await desk.card_made(card.name, engine.as_a_fan([("claude", "one"), ("local", "two")]))

    answer = await routes.answers_on_a_card(card.name)
    said = json.loads(bytes(answer.body).decode())

    (row,) = said["rows"]
    assert row["before"] == "one"
    assert row["after"] == "two"
    assert row["label"] == "claude → local"
    assert {one["mark"] for one in row["marks"]} == {"before", "after"}


async def test_three_answers_are_each_compared_with_the_first(desk: Store) -> None:
    """The reading a fan invites: one model is the one you had, and the others are what the rest
    said instead."""
    card = await desk.add_step_card("ask")
    await desk.card_made(card.name, engine.as_a_fan([("a", "one"), ("b", "two"), ("c", "three")]))

    said = json.loads(bytes((await routes.answers_on_a_card(card.name)).body).decode())

    assert [row["label"] for row in said["rows"]] == ["a → b", "a → c"]


async def test_a_card_with_one_answer_says_so(desk: Store) -> None:
    card = await desk.add_step_card("ask")
    await desk.card_made(card.name, "just the one")

    said = json.loads(bytes((await routes.answers_on_a_card(card.name)).body).decode())

    assert said["rows"] == []
    assert "one answer, not several" in said["said"]


async def test_a_card_that_produced_nothing_says_so(desk: Store) -> None:
    said = json.loads(bytes((await routes.answers_on_a_card("step:nothing")).body).decode())

    assert said["rows"] == []


# --- and the panel ---------------------------------------------------------------------------------------
def _code() -> str:
    return "\n".join(
        line
        for line in CONSOLE.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("//")
    )


def test_it_is_the_panel_that_already_compares_two_things() -> None:
    """A second panel would be a second answer to "how is a difference shown"."""
    source = _code()

    assert "async function showComparison(where)" in source
    assert "showComparison(`/workbench/answers?name=" in source
    assert "showComparison(`/workbench/compare?runs=" in source


def test_every_piece_is_written_as_text_and_never_as_markup() -> None:
    """These are two answers a model wrote, and a model writes angle brackets."""
    source = _code()
    start = source.index("function writeMarks(")
    body = source[start : source.index("\n}\n", start)]

    assert "textContent" in body
    assert "innerHTML" not in body


def test_a_side_shows_what_is_in_it_and_not_what_is_only_in_the_other() -> None:
    source = _code()
    start = source.index("function writeMarks(")
    body = source[start : source.index("\n}\n", start)]

    assert "one.mark !== 'same' && one.mark !== side" in body


def test_the_control_appears_only_where_there_are_several_answers() -> None:
    """Decided from the run this page already has, rather than a request per card every two
    seconds for a control most cards will never show."""
    source = _code()

    assert "answers.hidden = ((step.made || '').match(/^## /gm) || []).length < 2" in source
