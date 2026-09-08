"""A ticket dragged onto the workbench is a card (01M1ZQ3JPM9AC5RN8SE4AK9VAH).

It has been draggable out of the right-hand column since that column existed, and it arrived on the
bench saying "could not read this one": `render_card` knows the four kinds that come off the board
and a ticket comes out of the store, so the route 404-ed and the page rendered its error.

Part of "Вынести на верстак то, к чему есть доступ" (01M1X8DA5KM5K6VZDKWKM664Y0).
"""

from __future__ import annotations

import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk.store.repo import Store
from agent_desk.web import routes

pytestmark = pytest.mark.unit

TICKETS = (
    pathlib.Path(__file__).resolve().parents[2]
    / "agent_desk"
    / "web"
    / "templates"
    / "_tickets.html"
)


@pytest.fixture
async def desk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    yield store
    await store.close()


async def _a_ticket(store: Store, **over: object) -> str:
    made = await store.queue_task(
        repo_key="origin:acme/api",
        cwd="/home/dev/api",
        title="API-14 · the reader drops a trailing slash",
        instruction="Fix the trailing slash in the registry reader.",
        source_kind=str(over.get("source_kind", "tracker")),
        source_ref=over.get("source_ref", "API-14"),  # type: ignore[arg-type]
    )
    return made.id


async def test_the_column_offers_the_drag_that_used_to_break(desk: Store) -> None:
    """Asserted here so the two halves cannot drift: the column says a ticket is draggable, and the
    card route is what catches it."""
    assert 'data-kind="task"' in TICKETS.read_text(encoding="utf-8")
    assert 'draggable="true"' in TICKETS.read_text(encoding="utf-8")


async def test_a_ticket_reads_as_a_card(desk: Store) -> None:
    ident = await _a_ticket(desk)

    answer = await routes.card("task", ident)

    assert answer.status_code == 200
    assert "Fix the trailing slash in the registry reader." in bytes(answer.body).decode()


async def test_it_says_where_the_work_was_decided(desk: Store) -> None:
    """ "An idea is a thought somebody had *here*, and a ticket is work somebody decided
    *elsewhere*" — and which of the two this is decides what may be done with it."""
    ident = await _a_ticket(desk)

    body = bytes((await routes.card("task", ident)).body).decode()

    assert "Read from this project's own board" in body
    assert "API-14" in body
    assert "Nothing here transitions it" in body


async def test_a_ticket_queued_here_does_not_claim_to_come_from_a_board(desk: Store) -> None:
    ident = await _a_ticket(desk, source_kind="human", source_ref=None)

    body = bytes((await routes.card("task", ident)).body).decode()

    assert "Queued here by hand" in body
    assert "own board" not in body


async def test_it_does_not_repeat_the_queue_buttons(desk: Store) -> None:
    """Whether an agent has started is on the column's card, where the buttons that change it are.
    A second copy on the bench is a second thing to go stale in front of somebody."""
    ident = await _a_ticket(desk)

    body = bytes((await routes.card("task", ident)).body).decode()

    assert "take it on" not in body
    assert "/start" not in body


async def test_a_ticket_that_has_gone_says_so_rather_than_rendering_an_error(desk: Store) -> None:
    answer = await routes.card("task", "01ZZZZZZZZZZZZZZZZZZZZZZZZ")

    assert answer.status_code == 404
    assert "not in the queue any more" in bytes(answer.body).decode()


async def test_the_hundred_and_first_ticket_is_still_readable(desk: Store) -> None:
    """Read by id rather than filtered out of `tasks()`, which is capped: a card whose ticket
    happened to be past the cap would render "could not read this one" for a row sitting in the
    table."""
    first = await _a_ticket(desk)
    for number in range(120):
        await desk.queue_task(
            repo_key="origin:acme/api",
            cwd="/home/dev/api",
            title=f"filler {number}",
            instruction="x",
            source_kind="human",
        )

    assert await desk.task(first) is not None
    assert (await routes.card("task", first)).status_code == 200
