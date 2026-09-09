"""The pool can say "this is already here", and a person decides (01M21KTYG59HR7FDMPAJ3MMJTR).

«Ответ — предложение с кнопками, а не автоматическое связывание.» A list that quietly reorganises
itself between the moment somebody writes a thought and the moment they look at it is a list they
stop trusting to hold what they put in it.
"""

from __future__ import annotations

import pathlib
import urllib.parse
from collections.abc import AsyncIterator
from typing import ClassVar

import pytest
from agent_desk.ideas import kin
from agent_desk.store.repo import Store
from agent_desk.web import routes

pytestmark = pytest.mark.unit


@pytest.fixture
async def desk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    yield store
    await store.close()


def _a_form(fields: dict[str, str]) -> object:
    body = urllib.parse.urlencode(fields).encode()

    class Filled:
        async def body(self) -> bytes:
            return body

        headers: ClassVar[dict[str, str]] = {"content-type": "application/x-www-form-urlencoded"}

    return Filled()


def _answers(reply: str, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(prompt: str) -> AsyncIterator[str]:
        yield reply

    monkeypatch.setattr(kin, "stream_answer", fake)


async def _a_pair(desk: Store, monkeypatch: pytest.MonkeyPatch) -> tuple[str, str, str]:
    """Two ideas and an unanswered suggestion about them."""
    first = await desk.create_idea(text_="add hotkeys", summary="add hotkeys", source_kind="typed")
    again = await desk.create_idea(text_="shortcuts", summary="shortcuts", source_kind="typed")
    _answers("same 1", monkeypatch)
    await kin.suggest(desk, again)
    (offered,) = await desk.suggestions()
    return offered.id, again.id, first.id


# --- the offer -----------------------------------------------------------------------------------
async def test_the_card_offers_both_answers(desk: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    """Both, because "they are different" is an answer and not the absence of one."""
    _, again, first = await _a_pair(desk, monkeypatch)

    said = (await routes.card(kind="idea", id=again)).body.decode()

    assert "add hotkeys" in said
    assert 'value="joined"' in said and 'value="apart"' in said


async def test_pressing_join_puts_it_under_the_other_one(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    offered, again, first = await _a_pair(desk, monkeypatch)

    await routes.settle_kin(_a_form({"id": offered, "took": "joined"}))

    moved = await desk.idea(again)
    assert moved is not None and moved.parent_id == first
    assert await desk.suggestions() == []


async def test_pressing_apart_leaves_both_where_they_are(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    offered, again, _ = await _a_pair(desk, monkeypatch)

    await routes.settle_kin(_a_form({"id": offered, "took": "apart"}))

    still = await desk.idea(again)
    assert still is not None and still.parent_id is None
    assert await desk.suggestions() == []


async def test_a_pair_somebody_answered_is_never_offered_again(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A suggestion that comes back after being refused is noise with a memory problem."""
    offered, again, _ = await _a_pair(desk, monkeypatch)
    await routes.settle_kin(_a_form({"id": offered, "took": "apart"}))

    one = await desk.idea(again)
    assert one is not None
    await kin.suggest(desk, one)

    assert await desk.suggestions() == []
    assert len(await desk.suggestions(waiting=False)) == 1


async def test_what_somebody_decided_is_kept(desk: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    offered, _, _ = await _a_pair(desk, monkeypatch)

    await routes.settle_kin(_a_form({"id": offered, "took": "apart"}))

    (settled,) = await desk.suggestions(waiting=False)
    assert settled.took == "apart"
    assert settled.settled_at is not None


async def test_a_suggestion_whose_other_half_is_gone_is_not_drawn(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A button pointing at nothing is worse than no button."""
    _, again, first = await _a_pair(desk, monkeypatch)
    await desk.delete_idea(first)

    said = (await routes.card(kind="idea", id=again)).body.decode()

    assert 'value="joined"' not in said


async def test_a_press_on_a_suggestion_that_is_gone_is_not_a_crash(desk: Store) -> None:
    assert (await routes.settle_kin(_a_form({"id": "nope", "took": "joined"}))).status_code == 404


# --- and the same check, after the fact ----------------------------------------------------------
async def test_the_check_can_be_run_over_a_pool_that_was_already_there(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """«Та же проверка задним числом: "эти две выглядят одной".» A notebook that only
    de-duplicates what arrives after the feature was built keeps all of its duplicates."""
    await desk.create_idea(text_="add hotkeys", summary="add hotkeys", source_kind="typed")
    await desk.create_idea(text_="shortcuts", summary="shortcuts", source_kind="typed")
    _answers("same 1", monkeypatch)

    back = await routes.look_for_kin()

    assert await desk.suggestions() != []
    assert b'"suggested"' in back.body


async def test_writing_a_thought_down_never_waits_for_the_check(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ "Проверка не задерживает запись: мысль сохраняется до того, как что-то спрошено." The
    judgement reads a row that is already there, so a model that never answers costs a suggestion
    and never a thought."""
    asked: list[str] = []

    async def slow(prompt: str) -> AsyncIterator[str]:
        asked.append(prompt)
        raise kin.AnswerFailed("no model here")
        yield ""  # pragma: no cover

    monkeypatch.setattr(kin, "stream_answer", slow)
    await desk.create_idea(text_="add hotkeys", summary="add hotkeys", source_kind="typed")
    written = await desk.create_idea(text_="shortcuts", summary="shortcuts", source_kind="typed")

    assert await kin.suggest(desk, written) == "new"
    assert asked, "the model was asked, after the row was written"
    assert await desk.idea(written.id) is not None


def test_only_so_many_ideas_are_compared_at_once() -> None:
    """ "С ограничением на длину списка." A pool larger than this is one where the model's
    attention is the bottleneck rather than its judgement."""
    assert kin.MOST_COMPARED == 40
