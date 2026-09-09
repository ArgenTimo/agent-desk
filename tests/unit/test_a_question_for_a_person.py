"""An agent asks a person and goes on working (01M21NAVDKYXSTMZRP240H46NW).

«Агент, упёршийся в решение, которое не его, сегодня умеет одно — остановиться и ждать. Всё, что он
сделал до вопроса, стоит в очереди за ответом.»

The console is the only place a question can wait for somebody without occupying anybody's window.
Nothing here writes into a running session: the row waits, a person presses, the asker comes back.
"""

from __future__ import annotations

import pathlib
import urllib.parse
from collections.abc import AsyncIterator
from typing import ClassVar

import pytest
from agent_desk.mcp import tools
from agent_desk.store.repo import Store
from agent_desk.web import blockers, routes

pytestmark = pytest.mark.unit


@pytest.fixture
async def desk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    yield store
    await store.close()


def _said(back: dict[str, object]) -> str:
    return back["content"][0]["text"]  # type: ignore[index,return-value]


def _a_form(fields: dict[str, str]) -> object:
    """A posted form, without a running server behind it."""
    body = urllib.parse.urlencode(fields).encode()

    class Filled:
        async def body(self) -> bytes:
            return body

        headers: ClassVar[dict[str, str]] = {"content-type": "application/x-www-form-urlencoded"}

    return Filled()


# --- the call that does not wait -----------------------------------------------------------------
async def test_asking_returns_an_id_and_does_not_wait(desk: Store) -> None:
    """Everything the agent built before the question is queued behind the answer, and it does not
    have to be: it leaves the question and takes up what does not depend on it."""
    said = _said(
        await tools.call(
            desk,
            "ask",
            {
                "question": "keep the third column or drop it?",
                "options": ["keep it", "drop it"],
                "done": "the reader and its tests",
                "who": "the column agent",
            },
        )
    )

    (one,) = await desk.questions()
    assert one.id in said
    assert one.choices == ["keep it", "drop it"]
    assert one.waiting


async def test_a_question_with_nothing_in_it_is_refused(desk: Store) -> None:
    assert "empty" in _said(await tools.call(desk, "ask", {"question": "   "}))
    assert await desk.questions() == []


# --- the answer is a press ----------------------------------------------------------------------
async def test_the_answer_is_what_somebody_pressed(desk: Store) -> None:
    """ "Человек отвечает нажатием, а не набором текста, потому что варианты уже перечислены."""
    one = await desk.ask_a_person("keep it?", options=["keep it", "drop it"])

    assert await desk.answer_a_question(one.id, "drop it")

    back = await desk.question(one.id)
    assert back is not None
    assert back.answer == "drop it"
    assert not back.waiting


async def test_the_first_answer_stands(desk: Store) -> None:
    """The asker may already have read it and acted on it. A question whose answer changes
    underneath the work it unblocked is worse than one answered wrongly and asked again."""
    one = await desk.ask_a_person("keep it?", options=["keep it", "drop it"])
    await desk.answer_a_question(one.id, "keep it")

    assert not await desk.answer_a_question(one.id, "drop it")

    back = await desk.question(one.id)
    assert back is not None and back.answer == "keep it"


async def test_an_unanswered_question_says_so_in_words(desk: Store) -> None:
    """ "Словами, а не пустотой." An empty string back cannot be told apart from somebody having
    answered with nothing, and the two mean opposite things about whether to keep waiting."""
    one = await desk.ask_a_person("keep it?", options=["keep it", "drop it"])

    said = _said(await tools.call(desk, "answer", {"id": one.id}))

    assert "Nobody has answered" in said
    assert "keep it, drop it" in said


async def test_the_answer_comes_back_when_it_is_there(desk: Store) -> None:
    one = await desk.ask_a_person("keep it?", options=["keep it", "drop it"])
    await desk.answer_a_question(one.id, "drop it")

    assert _said(await tools.call(desk, "answer", {"id": one.id})) == "drop it"


async def test_a_question_nobody_asked_is_said_plainly(desk: Store) -> None:
    assert "no question" in _said(await tools.call(desk, "answer", {"id": "nope"}))


# --- the card ------------------------------------------------------------------------------------
async def test_the_card_shows_who_asked_what_is_on_hold_and_the_options(desk: Store) -> None:
    """ "Не строка в логе: карточка, у которой видно, кто спросил, что предлагает и что стоит на
    паузе." Read as a browser reads it, so a rule that matters is not asserted against the comment
    that explains it."""
    one = await desk.ask_a_person(
        "keep the third column?",
        options=["keep it", "drop it"],
        done="the reader and its tests",
        who="the column agent",
    )

    page = await routes.card(kind="asked", id=one.id)
    said = page.body.decode()

    assert "the column agent" in said
    assert "the reader and its tests" in said
    assert said.count('type="submit"') == 2
    for choice in one.choices:
        assert f'value="{choice}"' in said


async def test_an_answered_card_offers_nothing_to_press(desk: Store) -> None:
    one = await desk.ask_a_person("keep it?", options=["keep it", "drop it"])
    await desk.answer_a_question(one.id, "drop it")

    said = (await routes.card(kind="asked", id=one.id)).body.decode()

    assert 'value="keep it"' not in said
    assert "drop it" in said


async def test_a_question_with_no_options_is_answered_in_words(desk: Store) -> None:
    """A question that offers nothing to press is one somebody types an answer to, and the card
    says which kind it is rather than showing an empty row of buttons."""
    one = await desk.ask_a_person("what should it be called?")

    said = (await routes.card(kind="asked", id=one.id)).body.decode()

    assert "<textarea" in said
    assert said.count('type="submit"') == 1


async def test_a_card_for_a_question_that_is_gone(desk: Store) -> None:
    assert (await routes.card(kind="asked", id="nope")).status_code == 404


# --- and it is visible as what holds work --------------------------------------------------------
async def test_an_unanswered_question_is_on_the_board_as_something_holding_work(
    desk: Store,
) -> None:
    """ "Вопрос, который никто не заметил, — это агент, который стоит."""
    one = await desk.ask_a_person(
        "keep it?", options=["keep it"], done="the reader", who="the column agent"
    )

    (stuck,) = [it for it in await blockers.blockers(desk) if it.kind == "asked"]

    assert stuck.what == "keep it?"
    assert "the column agent" in stuck.why and "the reader" in stuck.why
    assert stuck.card == f"asked:{one.id}"


async def test_an_answered_question_stops_holding_work(desk: Store) -> None:
    """The ordinary outcome, and it is not an error: it means the thing got unstuck."""
    one = await desk.ask_a_person("keep it?", options=["keep it"])
    await desk.answer_a_question(one.id, "keep it")

    assert [it for it in await blockers.blockers(desk) if it.kind == "asked"] == []


def test_the_column_says_what_kind_of_thing_it_is_and_what_clearing_it_costs() -> None:
    """Every kind on that column has both, because a card that says neither is one somebody has to
    open to find out whether it is theirs."""
    assert "asked" in blockers.PLAINLY
    assert "asked" in blockers.ROUGHLY


async def test_pressing_an_option_records_it_through_the_page(desk: Store) -> None:
    """The route, not just the store underneath it: a card whose buttons post somewhere that does
    not write is a card that looks answered and is not."""
    one = await desk.ask_a_person("keep it?", options=["keep it", "drop it"])

    back = await routes.answer_a_question(_a_form({"id": one.id, "answer": "drop it"}))

    assert back.status_code == 204
    said = await desk.question(one.id)
    assert said is not None and said.answer == "drop it"


async def test_a_press_with_nothing_on_it_writes_nothing(desk: Store) -> None:
    """A textarea somebody submitted empty is not an answer of "", which the store would then
    show to the asker as a decision."""
    one = await desk.ask_a_person("keep it?")

    await routes.answer_a_question(_a_form({"id": one.id, "answer": "  "}))

    said = await desk.question(one.id)
    assert said is not None and said.waiting
