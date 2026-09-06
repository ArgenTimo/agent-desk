"""The loop that brings back what somebody put off (031-deferred.sql).

`waking.py` decides what a moment is; this decides what happens when one arrives. The two facts a
condition can be about are injected, so none of this needs a busy machine or a real gate.
"""

from __future__ import annotations

import pathlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from agent_desk.ideas import inbox, waking
from agent_desk.store.repo import Idea, Store
from agent_desk.web import later

KEY = "origin:acme/api"
NOW = datetime(2026, 3, 4, 14, 30, tzinfo=UTC)


@pytest.fixture
async def desk(tmp_path: pathlib.Path) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    yield store
    await store.close()


async def _deferred(desk: Store, said: str, *, at: int | None, when: str | None) -> Idea:
    idea = await inbox.capture(desk, said, project_key=KEY)
    await desk.defer_idea(idea.id, at=at, when=when)
    return idea


@pytest.fixture
def a_checkout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(later, "_a_checkout_of", lambda key: "/home/someone/api")


@pytest.fixture
def nothing_running(monkeypatch: pytest.MonkeyPatch) -> None:
    async def quiet() -> bool:
        return False

    monkeypatch.setattr(later, "anything_running", quiet)


@pytest.mark.unit
async def test_a_pool_with_nothing_deferred_costs_nothing(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ordinary console, and the tick must not read the registry to find that out."""

    async def never() -> bool:  # pragma: no cover - the point is that it is not called
        raise AssertionError("the registry was read on a console with nothing deferred")

    monkeypatch.setattr(later, "anything_running", never)
    await inbox.capture(desk, "an ordinary thought", project_key=KEY)

    assert await later.tick(desk) == 0


@pytest.mark.unit
async def test_a_moment_that_has_not_come_leaves_the_idea_where_it_is(
    desk: Store, nothing_running: None, a_checkout: None
) -> None:
    idea = await _deferred(
        desk,
        "напомни завтра",
        at=int((datetime.now(UTC) + timedelta(days=1)).timestamp()),
        when=None,
    )

    assert await later.tick(desk) == 0
    assert await desk.tasks() == []
    again = await desk.idea(idea.id)
    assert again is not None and again.deferred


@pytest.mark.unit
async def test_a_moment_that_has_come_puts_the_work_in_the_queue(
    desk: Store, nothing_running: None, a_checkout: None
) -> None:
    """ "И в этот момент срабатывать сама." The queue, not an agent: docs/adr/0007 says the loop
    decides when, and whether an agent may then start is the arming switch that already exists."""
    idea = await _deferred(
        desk,
        "доделать канарейку",
        at=int((datetime.now(UTC) - timedelta(minutes=5)).timestamp()),
        when=None,
    )

    assert await later.tick(desk) == 1

    tasks = await desk.tasks()
    assert len(tasks) == 1
    assert tasks[0].repo_key == KEY
    assert tasks[0].source_kind == "deferred"
    assert tasks[0].source_ref == idea.id
    assert tasks[0].instruction == "доделать канарейку"
    assert tasks[0].waiting, "it was started rather than queued; nothing here may start an agent"


@pytest.mark.unit
async def test_a_moment_fires_once_and_not_on_every_pass(
    desk: Store, nothing_running: None, a_checkout: None
) -> None:
    """The failure this guards is specific to conditions: "when nothing is running" stays true
    for as long as nothing is running, and without `woke_at` the same work would be queued every
    minute for the rest of the afternoon."""
    await _deferred(desk, "когда освободится — прибраться", at=None, when="free")

    assert await later.tick(desk) == 1
    assert await later.tick(desk) == 0
    assert await later.tick(desk) == 0
    assert len(await desk.tasks()) == 1


@pytest.mark.unit
async def test_a_condition_waits_for_the_condition(
    desk: Store, a_checkout: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    busy = True

    async def machine() -> bool:
        return busy

    monkeypatch.setattr(later, "anything_running", machine)
    await _deferred(desk, "когда освободится — прибраться", at=None, when="free")

    assert await later.tick(desk) == 0, "it fired while the machine was still busy"
    busy = False
    assert await later.tick(desk) == 1


@pytest.mark.unit
async def test_a_moment_that_arrives_with_nowhere_to_run_still_stops_waiting(
    desk: Store, nothing_running: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """It fires, queues nothing, and lands back in the pool as an ordinary idea.

    The alternative is an idea that stays deferred against a moment that has already passed,
    which is invisible in exactly the way the old behaviour was.
    """
    monkeypatch.setattr(later, "_a_checkout_of", lambda key: None)
    idea = await _deferred(desk, "когда освободится", at=None, when="free")

    assert await later.tick(desk) == 1
    assert await desk.tasks() == []
    again = await desk.idea(idea.id)
    assert again is not None and not again.deferred


@pytest.mark.unit
async def test_an_idea_with_no_project_fires_without_inventing_one(
    desk: Store, nothing_running: None, a_checkout: None
) -> None:
    idea = await inbox.capture(desk, "когда освободится, подумать")
    assert idea.project_key is None

    assert await later.tick(desk) == 1
    assert await desk.tasks() == []


@pytest.mark.unit
async def test_writing_a_moment_into_a_message_is_what_defers_it(desk: Store) -> None:
    """The door in. Nothing else has to be pressed: "напомни завтра" *is* the deferral."""
    idea = await inbox.capture(desk, "напомни завтра про хинты", project_key=KEY)

    stored = await desk.idea(idea.id)
    assert stored is not None
    assert stored.deferred
    assert stored.wakes_at is not None
    assert [one.id for one in await desk.deferred_ideas()] == [idea.id]


@pytest.mark.unit
async def test_an_ordinary_thought_is_not_deferred_by_accident(desk: Store) -> None:
    idea = await inbox.capture(desk, "кэшировать результаты проб", project_key=KEY)

    stored = await desk.idea(idea.id)
    assert stored is not None and not stored.deferred
    assert await desk.deferred_ideas() == []


@pytest.mark.unit
async def test_deferring_again_clears_the_record_that_it_already_fired(
    desk: Store, nothing_running: None, a_checkout: None
) -> None:
    idea = await _deferred(desk, "когда освободится", at=None, when="free")
    assert await later.tick(desk) == 1
    assert await later.tick(desk) == 0

    await desk.defer_idea(idea.id, at=None, when="free")
    assert await later.tick(desk) == 1, "an idea deferred a second time never came back"


@pytest.mark.unit
async def test_only_one_pass_wins_a_due_idea(desk: Store) -> None:
    """Two overlapping passes must not queue the same work twice; the row count says who won."""
    idea = await _deferred(desk, "когда освободится", at=None, when="free")

    assert await desk.idea_woke(idea.id) is True
    assert await desk.idea_woke(idea.id) is False


@pytest.mark.unit
async def test_a_project_that_has_never_finished_anything_is_not_green(desk: Store) -> None:
    """Unknown is not green. Reporting it as green is the inferred status CLAUDE.md's fifth rule
    is about, and here it would start work on the strength of a gate nobody ran."""
    assert await later.gate_is_green(desk, KEY) is False


@pytest.mark.unit
async def test_the_gate_is_green_when_the_last_thing_landed_and_nothing_is_in_flight(
    desk: Store,
) -> None:
    task = await desk.queue_task(
        repo_key=KEY,
        cwd="/home/someone/api",
        title="a change",
        instruction="do the thing",
        source_kind="idea",
    )
    await desk.take_next_task(KEY)
    await desk.task_started(task.id, "agent-1")
    assert await later.gate_is_green(desk, KEY) is False, "in flight is not green"

    await desk.finish_task(task.id)
    assert await later.gate_is_green(desk, KEY) is False, (
        "a task that finished without offering a branch says nothing about the gate"
    )

    await desk.task_landed(task.id, "merged", landed=True)
    assert await later.gate_is_green(desk, KEY) is True

    failed = await desk.queue_task(
        repo_key=KEY,
        cwd="/home/someone/api",
        title="another",
        instruction="do the other thing",
        source_kind="idea",
    )
    await desk.take_next_task(KEY)
    await desk.task_started(failed.id, "agent-2")
    await desk.finish_task(failed.id)
    await desk.task_landed(failed.id, "the gate said no", landed=False)
    assert await later.gate_is_green(desk, KEY) is False


@pytest.mark.unit
async def test_a_deferred_idea_says_on_its_card_when_it_comes_back() -> None:
    """A deferral nobody can see is the thing this replaced."""
    from agent_desk.web.routes import env

    wake = waking.read("завтра, когда пройдёт гейт", now=NOW)
    assert wake is not None
    idea = Idea(
        id="01",
        block_id=None,
        text="доделать",
        summary="доделать",
        state="new",
        source_kind="typed",
        source_ref=None,
        context={},
        created_at=0,
        wakes_at=wake.at,
        wakes_when=wake.when,
    )

    html = env.get_template("_card_idea.html").render(idea=idea, said="", projects=[])

    assert "comes back" in html
    assert "once the gate is green" in html
