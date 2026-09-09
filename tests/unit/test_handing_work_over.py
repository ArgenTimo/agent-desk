"""Two agents hand work to each other through the board (01M21NAVEEHZ8XJHZBWQ71BMRB).

«Сегодня передача выглядит так: один агент рассказывает человеку, человек пересказывает второму. Два
пересказа, и оба неточные.»

The board is the shared place both write to and which is nobody's context. Nothing here writes into
a session, so the first of the five rules is untouched.
"""

from __future__ import annotations

import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk.mcp import tools
from agent_desk.store.repo import Store
from agent_desk.web import routes

pytestmark = pytest.mark.unit


@pytest.fixture
async def desk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    monkeypatch.setattr(routes, "board", lambda: ([], []))
    yield store
    await store.close()


def _said(back: dict[str, object]) -> str:
    return back["content"][0]["text"]  # type: ignore[index,return-value]


async def test_what_an_agent_found_becomes_cards_on_a_workbench(desk: Store) -> None:
    """ "Итог работы агента — карточки на верстаке, а не абзац в задаче." A paragraph is read whole
    or not at all; cards are taken one at a time."""
    await tools.call(
        desk,
        "leave",
        {
            "name": "the migration",
            "found": [
                "the reader trusts the registry pid",
                "the tail is read twice on every tick",
            ],
            "who": "the first agent",
        },
    )

    (chat,) = await desk.open_threads()
    on_it = await desk.bench_cards(chat.id)
    assert chat.subject == "the migration"
    assert [card.label for card in on_it] == [
        "the reader trusts the registry pid",
        "the tail is read twice on every tick",
    ]
    assert {card.came for card in on_it} == {"left by the first agent"}


async def test_what_did_not_work_says_so_on_the_card(desk: Store) -> None:
    """ "Что не получилось — половина ценности передачи и та, которую пересказ теряет первой." The
    first line becomes the summary, which is what a folded card shows across the room, so the
    outcome belongs on that line."""
    await tools.call(
        desk,
        "leave",
        {
            "name": "the migration",
            "did_not": ["reading the tail in a thread — it deadlocked on the store"],
        },
    )

    (one,) = await desk.ideas()
    assert one.summary.startswith("did not work — ")
    assert "deadlocked on the store" in one.text


async def test_the_detail_of_a_failure_survives_under_its_first_line(desk: Store) -> None:
    """Only the first line is rewritten. What the agent wrote below it is what the next one reads
    when the summary is not enough."""
    await tools.call(
        desk,
        "leave",
        {"did_not": ["the thread deadlocked\nit holds the store open across the await"]},
    )

    (one,) = await desk.ideas()
    assert one.text.startswith("did not work — the thread deadlocked")
    assert "it holds the store open across the await" in one.text


async def test_the_second_agent_reads_it_off_the_same_bench(desk: Store) -> None:
    """The handoff, end to end: one call leaves it, the other picks it up — and no human retold
    anything in between."""
    await tools.call(
        desk,
        "leave",
        {
            "name": "the migration",
            "found": ["the reader trusts the registry pid"],
            "did_not": ["reading the tail in a thread"],
        },
    )

    said = _said(await tools.call(desk, "bench", {"name": "the migration"}))

    assert "the reader trusts the registry pid" in said
    assert "did not work — reading the tail in a thread" in said


async def test_leaving_something_does_not_rearrange_what_is_already_there(desk: Store) -> None:
    """A workbench somebody arranged is theirs. What is left lands below what is on it, keeping the
    order and the coordinates of everything that was placed by hand (042)."""
    chat = await desk.create_thread("the migration")
    was = await desk.create_idea(text_="already here", summary="already here", source_kind="typed")
    from agent_desk.store.repo import BenchCard

    theirs = BenchCard(
        name=f"idea:{was.id}",
        kind="idea",
        card_id=was.id,
        label="already here",
        x=300,
        y=200,
        shown="open",
        spent=False,
        ord=0,
        by_hand=True,
    )
    await desk.keep_bench([theirs], thread_id=chat.id)

    await tools.call(
        desk, "leave", {"name": "the migration", "found": ["the tail is read twice on every tick"]}
    )

    first, second = await desk.bench_cards(chat.id)
    assert (first.x, first.y, first.by_hand) == (300, 200, True)
    assert second.y > first.y


async def test_leaving_nothing_says_so(desk: Store) -> None:
    said = _said(await tools.call(desk, "leave", {"name": "the migration"}))

    assert "Nothing was left" in said
    assert await desk.ideas() == []


async def test_a_finding_nobody_can_read_is_refused_by_name(desk: Store) -> None:
    """The inbox refuses a first line that cannot be understood without opening the card. Said in
    full, because the caller is the one who can write a better one."""
    said = _said(await tools.call(desk, "leave", {"name": "the migration", "found": ["..."]}))

    assert "Not left:" in said
