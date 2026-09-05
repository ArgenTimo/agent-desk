"""The loop that decides when, and never what (docs/adr/0007).

Almost every test here asserts that nothing started. That is the shape of the thing: the loop is
one line of code and five reasons to refuse, and the reasons are what somebody has to trust at
three in the morning.
"""

from __future__ import annotations

import pathlib
import time
from collections.abc import AsyncIterator

import pytest
from agent_desk import dispatch
from agent_desk.store.repo import Store
from agent_desk.web import autostart

KEY = "origin:acme/api"


@pytest.fixture
async def desk(tmp_path: pathlib.Path) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    yield store
    await store.close()


@pytest.fixture
def started(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """A dispatch that always works, and a list of what it was asked to start."""
    asked: list[str] = []

    def fake_start(instruction: str, *, cwd: str, name: str) -> dispatch.Started:
        asked.append(instruction)
        return dispatch.Started(True, agent_id=f"agent{len(asked)}")

    monkeypatch.setattr(dispatch, "start", fake_start)
    return asked


async def _queue(store: Store, tmp_path: pathlib.Path, instruction: str = "do the thing") -> None:
    await store.queue_task(
        repo_key=KEY,
        cwd=str(tmp_path),
        title=instruction[:40],
        instruction=instruction,
        source_kind="typed",
    )


# --- the five refusals ---------------------------------------------------------------------------
@pytest.mark.unit
async def test_nothing_starts_in_a_project_nobody_armed(
    desk: Store, tmp_path: pathlib.Path, started: list[str]
) -> None:
    """Off is the default everywhere, and a project with nothing switched on behaves exactly as it
    did before this ADR existed."""
    await _queue(desk, tmp_path)

    assert await autostart.tick(desk, live=set()) is None
    assert started == []
    assert await autostart.why_not(desk, KEY, live=set()) == "not armed"


@pytest.mark.unit
async def test_nothing_starts_when_the_queue_is_empty(
    desk: Store, tmp_path: pathlib.Path, started: list[str]
) -> None:
    await desk.arm(KEY, per_hour=5)

    assert await autostart.tick(desk, live=set()) is None
    assert started == []
    assert await autostart.why_not(desk, KEY, live=set()) == "nothing is queued"


@pytest.mark.unit
async def test_only_one_agent_runs_in_a_project_at_a_time(
    desk: Store, tmp_path: pathlib.Path, started: list[str]
) -> None:
    """Two agents in two worktrees of one repository, started by a rule rather than by a person,
    is the shape of the mess this ADR is careful about."""
    await desk.arm(KEY, per_hour=5)
    await _queue(desk, tmp_path, "the first")
    await _queue(desk, tmp_path, "the second")

    first = await autostart.tick(desk, live=set())
    assert first is not None and first.title == "the first"
    assert len(started) == 1

    # Its agent is on the board, so the seat is taken.
    assert await autostart.tick(desk, live={"agent1"}) is None
    assert len(started) == 1
    assert await autostart.why_not(desk, KEY, live={"agent1"}) == "one is already running"


@pytest.mark.unit
async def test_the_budget_is_spent_and_then_it_waits(
    desk: Store, tmp_path: pathlib.Path, started: list[str]
) -> None:
    """A project that has spent its hour waits, visibly, rather than queueing more."""
    await desk.arm(KEY, per_hour=1)
    await _queue(desk, tmp_path, "the first")
    await _queue(desk, tmp_path, "the second")

    await autostart.tick(desk, live=set())
    # Its agent has gone, so the seat is free and only the budget is left to say no.
    assert await autostart.tick(desk, live=set()) is None
    assert len(started) == 1
    assert "budget is spent" in await autostart.why_not(desk, KEY, live=set())


@pytest.mark.unit
async def test_two_failures_in_a_row_switch_it_off(
    desk: Store, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rule that keeps firing into a broken condition is the three-in-the-morning failure in its
    most ordinary form, and the answer is to stop rather than to retry harder."""
    monkeypatch.setattr(
        dispatch,
        "start",
        lambda instruction, *, cwd, name: dispatch.Started(False, detail="no disk space"),
    )
    await desk.arm(KEY, per_hour=9)
    await _queue(desk, tmp_path, "the first")
    await _queue(desk, tmp_path, "the second")
    await _queue(desk, tmp_path, "the third")

    await autostart.tick(desk, live=set())
    assert (await desk.autostart(KEY)).armed is True

    await autostart.tick(desk, live=set())
    arming = await desk.autostart(KEY)
    assert arming.armed is False
    assert arming.disarmed_why is not None and "no disk space" in arming.disarmed_why

    # And the third one is still there, untouched, because nothing retries.
    assert [task.title for task in await desk.tasks() if task.waiting] == ["the third"]
    assert await autostart.tick(desk, live=set()) is None


# --- what it does when nothing says no -----------------------------------------------------------
@pytest.mark.unit
async def test_it_starts_what_was_queued_and_says_which_agent_has_it(
    desk: Store, tmp_path: pathlib.Path, started: list[str]
) -> None:
    await desk.arm(KEY, per_hour=5)
    await _queue(desk, tmp_path, "run the tests again")

    task = await autostart.tick(desk, live=set())

    assert task is not None
    assert started == [dispatch.build_task("run the tests again", project="run the tests again")]
    (stored,) = await desk.tasks()
    assert stored.agent_id == "agent1"
    assert stored.started_at is not None
    assert stored.failed_at is None


@pytest.mark.unit
async def test_a_task_is_taken_once_even_if_two_ticks_overlap(
    desk: Store, tmp_path: pathlib.Path
) -> None:
    """The claim is the write itself, guarded by `started_at IS NULL`: one statement, one winner."""
    await _queue(desk, tmp_path, "only once")

    first = await desk.take_next_task(KEY)
    second = await desk.take_next_task(KEY)

    assert first is not None
    assert second is None


@pytest.mark.unit
async def test_arming_clears_whatever_switched_it_off_last_time(desk: Store) -> None:
    """The person arming it has just read the reason; leaving the count would disarm it again on
    the next single failure."""
    await desk.note_failure(KEY)
    await desk.disarm(KEY, why="two starts in a row failed")

    await desk.arm(KEY, per_hour=3)

    arming = await desk.autostart(KEY)
    assert arming.armed is True
    assert arming.failures == 0
    assert arming.disarmed_why is None
    assert arming.per_hour == 3


@pytest.mark.unit
async def test_the_budget_is_bounded_whatever_is_typed_into_it(desk: Store) -> None:
    await desk.arm(KEY, per_hour=9999)
    assert (await desk.autostart(KEY)).per_hour == 20

    await desk.arm(KEY, per_hour=0)
    assert (await desk.autostart(KEY)).per_hour == 1


@pytest.mark.unit
async def test_the_window_is_an_hour_and_older_starts_do_not_count(
    desk: Store, tmp_path: pathlib.Path
) -> None:
    await _queue(desk, tmp_path)
    task = await desk.take_next_task(KEY)
    assert task is not None

    now = int(time.time() * 1000)
    assert await desk.started_since(KEY, now - autostart.WINDOW_MS) == 1
    assert await desk.started_since(KEY, now + 1000) == 0


# --- what happens when an agent goes ------------------------------------------------------------
@pytest.mark.unit
async def test_an_idea_is_built_when_the_agent_dispatched_for_it_finishes(
    desk: Store, tmp_path: pathlib.Path
) -> None:
    """The whole claim is "an agent was dispatched for this and it finished", and it is the only
    one available: nothing reports back, and this program will not ask it to."""
    idea = await desk.create_idea(text_="cache probes", summary="cache probes", source_kind="typed")
    other = await desk.create_idea(text_="untouched", summary="untouched", source_kind="typed")
    task = await desk.queue_task(
        repo_key=KEY,
        cwd=str(tmp_path),
        title="build it",
        instruction="build it",
        source_kind="idea",
        source_ref=idea.id,
    )
    await desk.take_next_task(KEY)
    await desk.task_started(task.id, "agent9")

    # Still running: nothing is claimed.
    assert await autostart.settle(desk, {"agent9"}) == []
    assert (await desk.idea(idea.id)).state == "new"  # type: ignore[union-attr]

    # Gone: the idea it was dispatched for leaves the list, and nothing else moves.
    assert await autostart.settle(desk, set()) == [idea.id]
    assert (await desk.idea(idea.id)).state == "done"  # type: ignore[union-attr]
    assert (await desk.idea(other.id)).state == "new"  # type: ignore[union-attr]

    # And only once: a second sweep has nothing left to settle.
    assert await autostart.settle(desk, set()) == []
    settled = next(t for t in await desk.tasks() if t.id == task.id)
    assert settled.finished_at is not None


@pytest.mark.unit
async def test_a_task_that_never_started_settles_nothing(
    desk: Store, tmp_path: pathlib.Path
) -> None:
    idea = await desk.create_idea(text_="a thought", summary="a thought", source_kind="typed")
    await desk.queue_task(
        repo_key=KEY,
        cwd=str(tmp_path),
        title="build it",
        instruction="build it",
        source_kind="idea",
        source_ref=idea.id,
    )

    assert await autostart.settle(desk, set()) == []
    assert (await desk.idea(idea.id)).state == "new"  # type: ignore[union-attr]


@pytest.mark.unit
async def test_a_human_can_put_a_built_idea_back(desk: Store) -> None:
    """Built is not final. It is a claim about a dispatch, and a person who looked can disagree."""
    idea = await desk.create_idea(text_="a thought", summary="a thought", source_kind="typed")
    await desk.set_idea_state(idea.id, "done")

    await desk.set_idea_state(idea.id, "kept")

    assert (await desk.idea(idea.id)).state == "kept"  # type: ignore[union-attr]
