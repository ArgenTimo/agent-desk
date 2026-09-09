"""The workbench a person assembled is what a starting agent gets (01M21KTYFVX4X3GTPZVNP2DMBA).

«Если человек уже собрал верстак — выбрал карточки, провёл связи, дал файлам разрешение — то именно
это и надо отдать агенту, а не абзац, написанный про это.»

docs/adr/0006 is what permits this: a human pressed a button and a new agent starts in a worktree of
its own. Nothing is written into anybody's session.
"""

from __future__ import annotations

import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk.store.repo import BenchCard, Store
from agent_desk.web import autostart, routes

pytestmark = pytest.mark.unit


@pytest.fixture
async def desk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    yield store
    await store.close()


def _card(name: str, **over: object) -> BenchCard:
    kind, _, card_id = name.partition(":")
    fields: dict[str, object] = {
        "name": name,
        "kind": kind,
        "card_id": card_id,
        "label": name,
        "x": 10,
        "y": 20,
        "shown": "hint",
        "spent": False,
        "ord": 0,
    }
    return BenchCard(**{**fields, **over})  # type: ignore[arg-type]


# --- what the briefing carries -------------------------------------------------------------------
async def test_the_briefing_carries_the_bench_it_was_started_from(desk: Store) -> None:
    """ "Ровно тот текст, который уходит в вопрос сегодня — но в задачу агента он не уходит.\" """
    chat = await desk.create_thread("the reader")
    one = await desk.create_idea(
        text_="the reader trusts the registry pid", summary="a trusted pid", source_kind="typed"
    )
    await desk.keep_bench([_card(f"idea:{one.id}")], thread_id=chat.id)

    said = await routes.from_the_bench([], chat.id)

    assert any("a trusted pid" in line for line in said)
    assert any("the reader trusts the registry pid" in line for line in said)


async def test_the_cards_arrive_as_names_and_not_only_as_a_digest(desk: Store) -> None:
    """ "Пересказ — это то, что кто-то уже прочитал за меня и сократил. Список имён и путей
    позволяет прочитать самому то, что нужно, и не читать остальное." A file card contributes its
    path, and an agent with a path can open the file."""
    chat = await desk.create_thread("the reader")
    await desk.keep_bench(
        [_card("file:/tmp/observe/registry.py", label="registry.py")], thread_id=chat.id
    )

    said = "\n".join(await routes.from_the_bench([], chat.id))

    assert "- file:/tmp/observe/registry.py — registry.py" in said


async def test_a_file_nobody_allowed_is_a_name_and_nothing_more(desk: Store) -> None:
    """The permissions are the person's. A briefing that could open what the person has not is a
    second set of rules about what may be read (055)."""
    secret = pathlib.Path("/tmp/agent-desk-briefing-test.txt")
    secret.write_text("the paragraph nobody allowed")
    chat = await desk.create_thread("the reader")
    await desk.keep_bench([_card(f"file:{secret}")], thread_id=chat.id)

    said = "\n".join(await routes.from_the_bench([], chat.id))

    assert str(secret) in said
    assert "the paragraph nobody allowed" not in said


async def test_an_empty_bench_adds_nothing_to_the_briefing(desk: Store) -> None:
    """A heading over nothing is a heading an agent reads and learns nothing from."""
    chat = await desk.create_thread("the reader")

    assert await routes.from_the_bench([], chat.id) == []


# --- and what comes back -------------------------------------------------------------------------
async def test_what_the_agent_did_comes_back_to_the_same_bench(desk: Store) -> None:
    """ "Карточка на том верстаке, с которого запускали, замыкает круг: человек видит ответ там же,
    где собирал вопрос.\" """
    chat = await desk.create_thread("the reader")
    block = await desk.create_block(
        thread_id=chat.id, kind="question", input="build it", thread_set_by="human"
    )
    await desk.keep_bench([_card("idea:one")], thread_id=chat.id)
    task = await desk.queue_task(
        repo_key="k",
        cwd="/tmp",
        title="build it",
        instruction="build it",
        source_kind="idea",
        block_id=block.id,
    )

    await autostart._back_where_it_started(desk, task)

    names = [card.name for card in await desk.bench_cards(chat.id)]
    assert names == ["idea:one", f"task:{task.id}"]


async def test_it_comes_back_once_however_often_that_is_settled(desk: Store) -> None:
    """A card that appears twice is a bench that grows a column of the same answer."""
    chat = await desk.create_thread("the reader")
    block = await desk.create_block(
        thread_id=chat.id, kind="question", input="build it", thread_set_by="human"
    )
    await desk.keep_bench([_card("idea:one")], thread_id=chat.id)
    task = await desk.queue_task(
        repo_key="k",
        cwd="/tmp",
        title="build it",
        instruction="build it",
        source_kind="idea",
        block_id=block.id,
    )

    await autostart._back_where_it_started(desk, task)
    await autostart._back_where_it_started(desk, task)

    assert len(await desk.bench_cards(chat.id)) == 2


async def test_work_this_console_found_for_itself_lands_on_no_bench(desk: Store) -> None:
    """It was never on anybody's workbench, so there is no circle to close."""
    task = await desk.queue_task(
        repo_key="k", cwd="/tmp", title="found it", instruction="fix it", source_kind="found"
    )

    await autostart._back_where_it_started(desk, task)

    assert await desk.bench_cards() == []


async def test_a_bench_somebody_has_cleared_is_left_alone(desk: Store) -> None:
    """Nothing on it means nobody is looking at it, and a card added to a surface somebody moved on
    from appears out of nowhere next week."""
    chat = await desk.create_thread("the reader")
    block = await desk.create_block(
        thread_id=chat.id, kind="question", input="build it", thread_set_by="human"
    )
    task = await desk.queue_task(
        repo_key="k",
        cwd="/tmp",
        title="build it",
        instruction="build it",
        source_kind="idea",
        block_id=block.id,
    )

    await autostart._back_where_it_started(desk, task)

    assert await desk.bench_cards(chat.id) == []
