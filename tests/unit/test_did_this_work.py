"""The two numbers docs/09-roadmap.md says this project is judged by (docs/stories/06).

That page ends with a section called `What is measured`, and it is unambiguous about why those two:

    Two numbers, from the beginning, because they are the ones that say whether this worked:
      * Terminal opens to check status, per day. Phase 1 exists to drive this to zero.
      * Ideas captured, and of those, promoted. Capture with no promotion means the inbox is a
        drain, not a notebook.

Neither was anywhere in the product. The second had been derivable from `idea` since the first
migration and was never shown; the first was never recorded at all. On the author's own store the
answer was four hundred and sixty-seven built out of four hundred and seventy-nine captured — the
tool working, on a surface where nobody could see it.
"""

from __future__ import annotations

import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk.store.repo import Store
from agent_desk.web import routes

pytestmark = pytest.mark.unit

WEEK_MS = 7 * 24 * 60 * 60 * 1000


@pytest.fixture
async def desk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    yield store
    await store.close()


async def _idea(desk: Store, summary: str, state: str = "new") -> str:
    idea = await desk.create_idea(
        text_=summary, summary=summary, source_kind="typed", author="human"
    )
    if state != "new":
        await desk.set_idea_state(idea.id, state)  # type: ignore[arg-type]
    return idea.id


# --- ideas captured, and of those, built -----------------------------------------------------------
async def test_the_pool_counts_what_went_in_and_what_came_out(desk: Store) -> None:
    for n in range(4):
        await _idea(desk, f"a thought {n}", "done" if n < 3 else "new")

    captured, built = await desk.ideas_since(0)

    assert (captured, built) == (4, 3)


async def test_promoted_is_on_the_way_and_done_is_the_far_end(desk: Store) -> None:
    """The roadmap's word is "promoted" and the state that means a thought became something is
    `done`. A count that used `promoted` would report an idea that was built as though it had
    stalled — the state is one step on the way, not the destination."""
    await _idea(desk, "still going", "promoted")
    await _idea(desk, "finished", "done")

    assert await desk.ideas_since(0) == (2, 1)


async def test_what_was_set_aside_counts_as_captured_and_not_as_built(desk: Store) -> None:
    """A thought somebody decided against is still a thought that was written down. Counting it as
    built would make the measure say the inbox is working by discarding it."""
    await _idea(desk, "no, on reflection", "dropped")

    assert await desk.ideas_since(0) == (1, 0)


async def test_the_measure_is_over_a_window_and_not_over_all_time(desk: Store) -> None:
    """An all-time total stops moving, and a number that stops moving is one nobody looks at
    twice."""
    old = await _idea(desk, "from months ago", "done")
    async with desk.engine.begin() as conn:
        from sqlalchemy import text as sql

        await conn.execute(
            sql("UPDATE idea SET created_at = :at WHERE id = :id"),
            {"at": 1_000, "id": old},
        )
    await _idea(desk, "this week", "done")

    assert await desk.ideas_since(0) == (2, 2)
    assert await desk.ideas_since(500_000) == (1, 1)


# --- and the times the board sent somebody to a terminal --------------------------------------------
async def test_a_terminal_this_console_opened_is_counted(desk: Store) -> None:
    """The honest half of the roadmap's other measure. A terminal somebody opens themselves is not
    visible from here and never will be; this one is."""
    assert await desk.terminals_since(0) == 0

    await desk.went_to_a_terminal("aaaaaaaa-0000-4000-8000-000000000001")
    await desk.went_to_a_terminal("bbbbbbbb-0000-4000-8000-000000000002")

    assert await desk.terminals_since(0) == 2


async def test_a_press_that_opened_nothing_sent_nobody_anywhere(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The route records it only when a terminal actually opened. A machine with no terminal this
    console knows how to open answers "the command is copied instead", and counting that would make
    the measure say the board failed somebody it never sent anywhere."""
    from agent_desk import opening

    monkeypatch.setattr(opening.shutil, "which", lambda name: None)

    await routes.open_a_session("aaaaaaaa-0000-4000-8000-000000000001")

    assert await desk.terminals_since(0) == 0


async def test_a_press_that_opened_one_is_recorded_by_the_route(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent_desk import opening

    monkeypatch.setattr(opening, "open_it", lambda session_id: opening.Opened(True, "opened in x"))

    await routes.open_a_session("aaaaaaaa-0000-4000-8000-000000000001")

    assert await desk.terminals_since(0) == 1


# --- and what the column says about it --------------------------------------------------------------
async def test_an_inbox_that_is_being_emptied_says_nothing_extra(desk: Store) -> None:
    """ "A counter that reads $0.14 of $25.00 all day teaches people to stop reading it" is this
    console's own argument about its spend counter."""
    for n in range(6):
        await _idea(desk, f"a thought {n}", "done")

    worked = await routes._did_this_work()

    assert not worked.draining


async def test_an_inbox_that_is_only_filling_up_says_so(desk: Store) -> None:
    """ "Capture with no promotion means the inbox is a drain, not a notebook" — and the fix for
    that is in docs/05-ideas.md, which is a reason to say it rather than to say nothing."""
    for n in range(6):
        await _idea(desk, f"a thought {n}")

    worked = await routes._did_this_work()

    assert worked.draining


async def test_a_pool_with_almost_nothing_in_it_is_not_judged(desk: Store) -> None:
    """One thought written down and not yet built is a Tuesday afternoon, not a drain."""
    await _idea(desk, "the only one")

    assert not (await routes._did_this_work()).draining


async def test_the_column_shows_both_numbers_and_neither_when_there_is_nothing_to_say(
    desk: Store,
) -> None:
    assert "built this week" not in await routes.render_column()
    assert "a terminal" not in await routes.render_column()

    await _idea(desk, "a thought", "done")
    await desk.went_to_a_terminal("aaaaaaaa-0000-4000-8000-000000000001")
    html = await routes.render_column()

    assert "1 of 1 built this week" in html
    assert "1 → a terminal" in html


async def test_zero_terminals_is_not_shown_because_zero_is_the_point(desk: Store) -> None:
    """Phase one exists to drive that number to zero, so a console printing "0" every day would be
    printing its own success until people stopped reading it."""
    await _idea(desk, "a thought", "done")

    assert "→ a terminal" not in await routes.render_column()
