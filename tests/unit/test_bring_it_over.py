"""Ask for something on the board in words, and get it on the workbench
(01M1Z9ZZTPYYK3ER7SPSHHJJQ2).

"Ctrl+K ищет по подписи. Нужно «принеси сюда сессию, которая чинит парсер» — то есть найти по
смыслу и положить, одним предложением. Дешёвая ветка: ничего не запускается, а промах виден сразу
и снимается кнопкой."

Which is the licence to guess. Nothing is started, and a wrong card lands where somebody can see it
and takes one press to remove — so this may read a sentence and act on it, where the branches that
raise agents may not.
"""

from __future__ import annotations

import pathlib
from collections.abc import AsyncIterator
from typing import Any

import pytest
from agent_desk import telling
from agent_desk.answer import classify
from agent_desk.store.repo import Store
from agent_desk.web import blocks, routes

pytestmark = pytest.mark.unit


@pytest.fixture
async def desk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    yield store
    await store.close()


class _Session:
    def __init__(self, ident: str, name: str) -> None:
        self.session_id = ident
        self.name = name


class _Row:
    def __init__(self, ident: str, name: str) -> None:
        self.session = _Session(ident, name)
        self.tail = None


async def _asked(store: Store, said: str) -> Any:
    thread = await store.create_thread("a chat")
    return await store.create_block(
        thread_id=thread.id, kind="question", input=said, thread_set_by="human"
    )


# --- what is offered to the reader ------------------------------------------------------------------
def test_it_is_asked_which_of_the_board_they_mean() -> None:
    asked = classify.wanted_prompt("bring me the session fixing the parser", ["session · parser"])

    assert "What is on the board" in asked
    assert "session · parser" in asked


def test_it_is_told_that_the_wrong_card_is_worse_than_none() -> None:
    """They then have to notice it is wrong, which is work the console created."""
    asked = classify.wanted_prompt("bring it", ["session · x"])

    assert "worse answer than bringing none" in asked


def test_the_reader_is_the_one_that_reads_which_of_these() -> None:
    """The ways a model can fail to name a card are the same ways whatever it was asked, so there
    is one reader and not one per question."""
    assert classify.read_which("2", 3) == [2]
    assert classify.read_which("none", 3) == []


async def test_nothing_offered_costs_no_model_call() -> None:
    assert await classify.wanted("bring it", []) == []


# --- what happens ------------------------------------------------------------------------------------
async def test_what_was_asked_for_lands_on_the_workbench(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    block = await _asked(desk, "принеси сюда сессию, которая чинит парсер")

    async def picks_the_first(_text: str, _cards: list[str]) -> list[int]:
        return [1]

    monkeypatch.setattr(blocks.classifier, "wanted", picks_the_first)

    await blocks._bring_one_over(desk, block, [_Row("abc", "rewriting the parser")])

    again = await desk.block(block.id)
    assert again is not None
    said, names = telling.read_drawn(again.answer or "")
    assert names == ["session:abc"]
    assert "rewriting the parser" in said


async def test_the_ideas_in_the_pool_can_be_asked_for_too(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent_desk.ideas import inbox

    idea = await inbox.capture(desk, "cache the probe results")
    block = await _asked(desk, "bring me the one about caching")

    offered: list[list[str]] = []

    async def watch(_text: str, cards: list[str]) -> list[int]:
        offered.append(cards)
        return [1]

    monkeypatch.setattr(blocks.classifier, "wanted", watch)

    await blocks._bring_one_over(desk, block, [])

    assert offered == [["idea · cache the probe results"]]
    again = await desk.block(block.id)
    assert again is not None
    assert telling.read_drawn(again.answer or "")[1] == [f"idea:{idea.id}"]


async def test_nothing_matching_brings_nothing_and_says_so(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    block = await _asked(desk, "bring me the thing about penguins")

    async def nothing(_text: str, _cards: list[str]) -> list[int]:
        return []

    monkeypatch.setattr(blocks.classifier, "wanted", nothing)

    await blocks._bring_one_over(desk, block, [_Row("abc", "rewriting the parser")])

    again = await desk.block(block.id)
    assert again is not None
    assert "Nothing on the board matched" in (again.answer or "")
    assert telling.read_drawn(again.answer or "")[1] == []


async def test_an_empty_board_says_so_rather_than_asking_a_model(desk: Store) -> None:
    block = await _asked(desk, "bring me something")

    await blocks._bring_one_over(desk, block, [])

    again = await desk.block(block.id)
    assert again is not None
    assert "nothing on the board to bring over" in (again.answer or "")


async def test_a_request_for_tickets_still_fetches_them_rather_than_searching(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The two are told apart before either runs: "покажи тикеты" is a list to fetch, and anything
    else is something already here."""
    block = await _asked(desk, "покажи открытые PR-ы")
    searched = []
    monkeypatch.setattr(blocks, "_bring_one_over", lambda *a, **k: searched.append(1))

    await blocks._show_them(desk, block, [], [])

    again = await desk.block(block.id)
    assert again is not None
    assert searched == []
    assert "know whose board to read" in (again.answer or "")
