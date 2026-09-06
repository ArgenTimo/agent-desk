"""The loop that decides when, and never what (docs/adr/0007).

Almost every test here asserts that nothing started. That is the shape of the thing: the loop is
one line of code and five reasons to refuse, and the reasons are what somebody has to trust at
three in the morning.
"""

from __future__ import annotations

import asyncio
import contextlib
import pathlib
import time
from collections.abc import AsyncIterator

import pytest
from agent_desk import dispatch
from agent_desk.observe.model import JobEnd
from agent_desk.store.repo import Store, Task
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

    def fake_start(
        instruction: str, *, cwd: str, name: str, env: object = None
    ) -> dispatch.Started:
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
        lambda instruction, *, cwd, name, env=None: dispatch.Started(False, detail="no disk space"),
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


# --- an agent that finds its own work (docs/adr/0008) ---------------------------------------------
@pytest.mark.unit
async def test_nothing_is_explored_in_a_project_that_was_not_switched_on(
    desk: Store, tmp_path: pathlib.Path, started: list[str]
) -> None:
    """Arming the queue says "start what I put here"; exploring is a second decision."""
    await desk.arm(KEY, per_hour=5)

    assert await autostart.tick(desk, live=set()) is None
    assert started == []
    assert await autostart.why_not_explore(desk, KEY, live=set()) == "not exploring"


@pytest.mark.unit
async def test_queued_work_always_comes_before_anything_it_finds(
    desk: Store, tmp_path: pathlib.Path, started: list[str]
) -> None:
    """Exploration happens when there is nothing a human chose, and never instead of it."""
    await desk.arm(KEY, per_hour=5)
    await desk.explore(KEY, per_day=3, on=True)
    await _queue(desk, tmp_path, "what a person asked for")

    task = await autostart.tick(desk, live=set())

    assert task is not None and task.title == "what a person asked for"
    assert task.source_kind == "typed"
    assert len(started) == 1


@pytest.mark.unit
async def test_with_an_empty_queue_it_goes_looking_and_says_so(
    desk: Store, tmp_path: pathlib.Path, started: list[str]
) -> None:
    """And what it produces is marked as its own, which is the whole of docs/adr/0008."""
    await desk.explore(KEY, per_day=3, on=True)
    # It needs somewhere to work: a project it has run something in before.
    done = await desk.queue_task(
        repo_key=KEY,
        cwd=str(tmp_path),
        title="an earlier task",
        instruction="earlier",
        source_kind="typed",
    )
    await desk.take_next_task(KEY)
    await desk.task_started(done.id, "old")
    await desk.finish_task(done.id)

    found = await autostart.tick(desk, live=set())

    assert found is not None
    assert found.source_kind == "found"
    assert "looking for something to fix" in found.title
    # One thing, small, tested, and not a redesign.
    assert "exactly one" in started[0]
    assert "must not do: add a feature" in started[0]


@pytest.mark.unit
async def test_the_day_s_budget_stops_it_looking_again(
    desk: Store, tmp_path: pathlib.Path, started: list[str]
) -> None:
    await desk.explore(KEY, per_day=1, on=True)
    seed = await desk.queue_task(
        repo_key=KEY, cwd=str(tmp_path), title="seed", instruction="seed", source_kind="typed"
    )
    await desk.take_next_task(KEY)
    await desk.task_started(seed.id, "old")
    await desk.finish_task(seed.id)

    first = await autostart.tick(desk, live=set())
    assert first is not None
    (running,) = [t for t in await desk.tasks() if t.source_kind == "found"]
    await desk.finish_task(running.id)

    assert await autostart.tick(desk, live=set()) is None
    assert len(started) == 1
    assert "day's budget is spent" in await autostart.why_not_explore(desk, KEY, live=set())


@pytest.mark.unit
async def test_it_does_not_look_while_its_own_agent_is_still_out(
    desk: Store, tmp_path: pathlib.Path, started: list[str]
) -> None:
    """One agent per project, whatever started it."""
    await desk.explore(KEY, per_day=9, on=True)
    seed = await desk.queue_task(
        repo_key=KEY, cwd=str(tmp_path), title="seed", instruction="seed", source_kind="typed"
    )
    await desk.take_next_task(KEY)
    await desk.task_started(seed.id, "agent1")
    await desk.finish_task(seed.id)

    await autostart.tick(desk, live=set())
    assert len(started) == 1

    assert await autostart.tick(desk, live={"agent1"}) is None
    assert len(started) == 1


@pytest.mark.unit
async def test_what_it_found_is_offered_to_the_project_when_its_agent_goes(
    desk: Store, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """docs/adr/0008, as amended: the branch is merged when the project's own gate passes on it,
    and what happened is written against the task either way."""
    from agent_desk import land
    from agent_desk.web import autostart as loop

    offered: list[tuple[str, str]] = []

    def fake_land(cwd: str, worktree_name: str) -> land.Landed:
        offered.append((cwd, worktree_name))
        return land.Landed(True, "merged and pushed — `make verify` passed")

    monkeypatch.setattr(loop.land, "land", fake_land)

    task = await desk.queue_task(
        repo_key=KEY,
        cwd=str(tmp_path),
        title="looking for something to fix in project",
        instruction="go and look",
        source_kind="found",
    )
    await desk.take_next_task(KEY)
    await desk.task_started(task.id, "agent4")

    await loop.settle(desk, set())

    # Offered under the same name its worktree was made with.
    assert offered == [(str(tmp_path), loop._worktree_of(task))]
    settled = next(one for one in await desk.tasks() if one.id == task.id)
    assert settled.finished_at is not None
    assert settled.detail is not None and "merged and pushed" in settled.detail


@pytest.mark.unit
async def test_work_a_person_queued_is_never_merged_by_the_loop(
    desk: Store, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only what the loop found itself. A task somebody wrote is theirs to land."""
    from agent_desk.web import autostart as loop

    monkeypatch.setattr(
        loop.land, "land", lambda cwd, name: pytest.fail("it merged somebody's own task")
    )
    task = await desk.queue_task(
        repo_key=KEY,
        cwd=str(tmp_path),
        title="what a person asked for",
        instruction="do it",
        source_kind="typed",
    )
    await desk.take_next_task(KEY)
    await desk.task_started(task.id, "agent5")

    await loop.settle(desk, set())

    settled = next(one for one in await desk.tasks() if one.id == task.id)
    assert settled.finished_at is not None


@pytest.mark.unit
async def test_a_project_with_no_checkout_here_is_not_explored(
    desk: Store, started: list[str]
) -> None:
    """It has to know where to work. A repository key alone is not a directory."""
    await desk.explore(KEY, per_day=3, on=True)

    assert await autostart.tick(desk, live=set()) is None
    assert started == []


@pytest.mark.unit
async def test_two_failed_explorations_switch_the_project_off(
    desk: Store, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same rule as the queue: a rule that keeps firing into a broken condition stops.

    `armed is False` is not the assertion that matters here and never was: this project was never
    armed, so that line held on the day exploring kept running anyway. The switch that has to go
    off is the one that started this — otherwise a project whose worktrees will not create asks
    for another every thirty seconds, all night, which is the failure the rule exists to end.
    """
    tried: list[str] = []

    def refuses(instruction: str, *, cwd: str, name: str, env: object = None) -> dispatch.Started:
        tried.append(instruction)
        return dispatch.Started(False, detail="no disk space")

    monkeypatch.setattr(dispatch, "start", refuses)
    await desk.explore(KEY, per_day=9, on=True)
    seed = await desk.queue_task(
        repo_key=KEY, cwd=str(tmp_path), title="seed", instruction="seed", source_kind="typed"
    )
    await desk.take_next_task(KEY)
    await desk.task_started(seed.id, "old")
    await desk.finish_task(seed.id)

    await autostart.tick(desk, live=set())
    await autostart.tick(desk, live=set())

    arming = await desk.autostart(KEY)
    assert arming.armed is False
    assert arming.exploring is False
    assert arming.disarmed_why is not None and "no disk space" in arming.disarmed_why

    await autostart.tick(desk, live=set())
    assert len(tried) == 2, "it went looking again after switching itself off"


@pytest.mark.unit
async def test_the_loop_survives_a_tick_that_raises(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A loop that took the console down with it would be a worse failure than anything it was
    started to do."""
    calls: list[int] = []
    # An event rather than a poll: the loop tells the test it has gone round twice, instead of the
    # test guessing how long that takes.
    went_round_twice = asyncio.Event()

    async def explodes(store: Store, live: set[str] | None = None) -> None:
        calls.append(1)
        if len(calls) >= 2:
            went_round_twice.set()
        raise RuntimeError("something went wrong in a pass")

    monkeypatch.setattr(autostart, "tick", explodes)
    monkeypatch.setattr(autostart, "TICK_SECONDS", 0.01)

    running = asyncio.create_task(autostart.run(desk))
    # Waited for rather than slept past. The first version gave it 50ms and asserted two passes
    # had happened, which is a race against however long it takes to *render* the traceback the
    # failure logs — and that got slower under a new pytest, so the test failed while the loop it
    # was testing carried on working perfectly.
    try:
        async with asyncio.timeout(5):
            await went_round_twice.wait()
    finally:
        running.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await running

    assert len(calls) >= 2, "it stopped after the first failure"


@pytest.mark.unit
async def test_an_agent_that_died_before_it_ran_does_not_mark_its_ideas_built(
    desk: Store, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The failure this reader was written for: six agents exited in under a second on a worktree
    name the CLI would not accept, and every idea they carried was marked built."""
    idea = await desk.create_idea(text_="a thought", summary="a thought", source_kind="typed")
    task = await desk.queue_task(
        repo_key=KEY,
        cwd=str(tmp_path),
        title="берём в работу",
        instruction="build it",
        source_kind="idea",
        source_ref=idea.id,
    )
    await desk.take_next_task(KEY)
    await desk.task_started(task.id, "deadone")
    monkeypatch.setattr(
        autostart.jobs,
        "read_job",
        lambda short: JobEnd(state="failed", detail="exit 1 before init — Invalid worktree name"),
    )

    assert await autostart.settle(desk, set()) == []

    assert (await desk.idea(idea.id)).state == "new"  # type: ignore[union-attr]
    died = next(one for one in await desk.tasks() if one.id == task.id)
    assert died.failed_at is not None and died.finished_at is None
    assert died.detail is not None and "Invalid worktree name" in died.detail


@pytest.mark.unit
async def test_two_agents_that_die_in_a_row_disarm_the_project(
    desk: Store, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rule firing into a broken condition stops rather than retrying harder — and a start that
    dies a second later is the same broken condition as one that never started."""
    await desk.arm(KEY, per_hour=5)
    monkeypatch.setattr(
        autostart.jobs, "read_job", lambda short: JobEnd(state="failed", detail="it fell over")
    )
    for number in range(2):
        task = await desk.queue_task(
            repo_key=KEY,
            cwd=str(tmp_path),
            title=f"try {number}",
            instruction="build it",
            source_kind="instruction",
        )
        await desk.take_next_task(KEY)
        await desk.task_started(task.id, f"dead{number}")
        await autostart.settle(desk, set())

    arming = await desk.autostart(KEY)
    assert not arming.armed
    assert arming.disarmed_why is not None and "it fell over" in arming.disarmed_why


@pytest.mark.unit
async def test_a_job_the_cli_has_forgotten_keeps_the_weaker_claim(
    desk: Store, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`claude rm` removes the job directory. Absence is not evidence of failure, and guessing
    either way is worse than saying what is known (CLAUDE.md, rule five)."""
    idea = await desk.create_idea(text_="a thought", summary="a thought", source_kind="typed")
    task = await desk.queue_task(
        repo_key=KEY,
        cwd=str(tmp_path),
        title="build it",
        instruction="build it",
        source_kind="idea",
        source_ref=idea.id,
    )
    await desk.take_next_task(KEY)
    await desk.task_started(task.id, "tidiedaway")
    monkeypatch.setattr(autostart.jobs, "read_job", lambda short: None)

    assert await autostart.settle(desk, set()) == [idea.id]
    settled = next(one for one in await desk.tasks() if one.id == task.id)
    assert settled.finished_at is not None and settled.failed_at is None


@pytest.mark.unit
def test_the_branch_the_cli_actually_made_is_preferred_over_a_second_guess() -> None:
    """Deriving the slug twice is two copies of the CLI's rules to keep in step."""
    task = Task(
        id="t",
        repo_key=KEY,
        cwd="/tmp",
        title="looking for something to fix in agent-desk, and then some",
        instruction="",
        source_kind="found",
        queued_at=0,
    )
    assert autostart._worktree_of(task, JobEnd(state="done", worktreeBranch="worktree-a-name")) == (
        "a-name"
    )
    # No job file, or one from a CLI that stopped recording it: the derivation is the fallback.
    assert autostart._worktree_of(task, None) == dispatch._worktree_name(task.title)
    assert autostart._worktree_of(task, JobEnd(state="done")) == dispatch._worktree_name(task.title)


@pytest.mark.unit
async def test_an_agent_still_working_settles_nothing_even_when_the_registry_forgot_it(
    desk: Store, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The registry is a weak signal and this is the direction it is weak in."""
    idea = await desk.create_idea(text_="a thought", summary="a thought", source_kind="typed")
    task = await desk.queue_task(
        repo_key=KEY,
        cwd=str(tmp_path),
        title="build it",
        instruction="build it",
        source_kind="idea",
        source_ref=idea.id,
    )
    await desk.take_next_task(KEY)
    await desk.task_started(task.id, "busyone")
    monkeypatch.setattr(autostart.jobs, "read_job", lambda short: JobEnd(state="working"))

    assert await autostart.settle(desk, set()) == []

    assert (await desk.idea(idea.id)).state == "new"  # type: ignore[union-attr]
    assert await autostart.running_for(desk, KEY, set()) == 1


@pytest.mark.unit
async def test_a_finished_agent_gives_up_its_seat_though_its_process_lives_on(
    desk: Store, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `--bg` agent idles at its prompt for as long as the machine is up. A seat rule that
    watched only the registry would hold that project's seat forever, and nothing would start."""
    task = await desk.queue_task(
        repo_key=KEY,
        cwd=str(tmp_path),
        title="build it",
        instruction="build it",
        source_kind="instruction",
    )
    await desk.take_next_task(KEY)
    await desk.task_started(task.id, "doneone")
    monkeypatch.setattr(autostart.jobs, "read_job", lambda short: JobEnd(state="done"))

    assert await autostart.running_for(desk, KEY, {"doneone"}) == 0
    assert await autostart.settle(desk, {"doneone"}) == []
    finished = next(one for one in await desk.tasks() if one.id == task.id)
    assert finished.finished_at is not None and finished.failed_at is None


@pytest.mark.unit
def test_only_the_two_states_the_cli_writes_when_it_is_over_end_a_task() -> None:
    """The safe direction: a value this program has not seen must not end somebody's task."""
    assert JobEnd(state="done").terminal
    assert JobEnd(state="failed").terminal
    assert not JobEnd(state="working").terminal
    assert not JobEnd(state="a state nobody has seen yet").terminal


@pytest.mark.unit
def test_with_no_job_file_the_registry_is_the_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """A job `claude rm` has forgotten: a weak signal, used as the weak signal it is."""
    monkeypatch.setattr(autostart.jobs, "read_job", lambda short: None)
    assert autostart.still_going("gone", {"gone"}) == (True, None)
    assert autostart.still_going("gone", set()) == (False, None)


@pytest.mark.unit
async def test_an_agent_this_module_cannot_name_keeps_its_seat(
    desk: Store, tmp_path: pathlib.Path
) -> None:
    """A started task with no agent recorded is unanswerable, and the safe answer changes
    nothing."""
    idea = await desk.create_idea(text_="a thought", summary="a thought", source_kind="typed")
    task = await desk.queue_task(
        repo_key=KEY,
        cwd=str(tmp_path),
        title="build it",
        instruction="build it",
        source_kind="idea",
        source_ref=idea.id,
    )
    await desk.take_next_task(KEY)
    await desk.task_started(task.id, "")

    assert autostart.still_going(None, set()) == (True, None)
    assert await autostart.settle(desk, set()) == []
    assert (await desk.idea(idea.id)).state == "new"  # type: ignore[union-attr]


@pytest.mark.unit
async def test_a_board_fills_the_queue_and_marks_where_it_came_from(
    desk: Store, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """docs/adr/0010: a ticket is a decision somebody already made in a system built for making
    it, so it becomes a *task* — never an idea, and counted apart from what a person queued."""
    from agent_desk.tracker import jira

    await desk.arm(KEY, per_hour=5)
    await desk.set_link(
        repo_key=KEY,
        name="jira",
        url="https://x.atlassian.net/browse/DUCK",
        token_env="DUCK_TOKEN",
    )
    monkeypatch.setattr(
        jira,
        "read_board",
        lambda where: jira.Read(
            True,
            tickets=(
                jira.Ticket(key="DUCK-1", summary="the export is wrong", status="To Do"),
                jira.Ticket(
                    key="DUCK-2",
                    summary="the import",
                    status="To Do",
                    blocked_by="Blocked on the vendor key.",
                ),
            ),
        ),
    )
    arming = await desk.autostart(KEY)

    assert await autostart.pull_tickets(desk, arming) == 1

    (task,) = await desk.tasks(repo_key=KEY)
    assert task.source_kind == "tracker"
    assert task.source_ref == "DUCK-1"
    assert "DUCK-1" in task.title
    # Nothing reached the pool: it is a person's notebook (docs/05-ideas.md).
    assert await desk.ideas() == []

    # The blocked one is not queued and not silently dropped — a board full of blocked work must
    # not look like an empty board.
    (stuck,) = await desk.tracker_blockers()
    assert stuck.key == "DUCK-2"
    assert "vendor key" in stuck.said

    # And running again queues nothing twice.
    assert await autostart.pull_tickets(desk, arming) == 0


@pytest.mark.unit
async def test_a_ticket_that_was_unblocked_stops_being_a_blocker(
    desk: Store, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replaced rather than merged, which is the only way this stays true without anybody telling
    the console anything."""
    from agent_desk.tracker import jira

    await desk.set_link(
        repo_key=KEY,
        name="jira",
        url="https://x.atlassian.net/browse/DUCK",
        token_env="DUCK_TOKEN",
    )
    arming = await desk.autostart(KEY)

    monkeypatch.setattr(
        jira,
        "read_board",
        lambda where: jira.Read(
            True,
            tickets=(jira.Ticket(key="DUCK-2", summary="the import", blocked_by="Blocked."),),
        ),
    )
    await autostart.pull_tickets(desk, arming)
    assert len(await desk.tracker_blockers()) == 1

    monkeypatch.setattr(
        jira,
        "read_board",
        lambda where: jira.Read(True, tickets=(jira.Ticket(key="DUCK-2", summary="the import"),)),
    )
    await autostart.pull_tickets(desk, arming)

    assert await desk.tracker_blockers() == []


@pytest.mark.unit
async def test_a_project_with_no_tracker_reads_nothing_and_is_not_an_error(
    desk: Store, tmp_path: pathlib.Path
) -> None:
    """Which is every project by default."""
    assert await autostart.pull_tickets(desk, await desk.autostart(KEY)) == 0


@pytest.mark.unit
async def test_a_tracker_that_cannot_be_read_queues_nothing_and_says_nothing_false(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unreadable board must not look like an empty one to anything downstream."""
    from agent_desk.tracker import jira

    await desk.set_link(
        repo_key=KEY,
        name="jira",
        url="https://x.atlassian.net/browse/DUCK",
        token_env="DUCK_TOKEN",
    )
    monkeypatch.setattr(
        jira, "read_board", lambda where: jira.Read(False, detail="DUCK_TOKEN is not set")
    )

    assert await autostart.pull_tickets(desk, await desk.autostart(KEY)) == 0
    assert await desk.tasks(repo_key=KEY) == []
    # And nothing was recorded as unblocked either, which a naive "replace with what we found"
    # would have done.
    assert await desk.tracker_blockers() == []


@pytest.mark.unit
async def test_the_loop_stops_when_the_cancel_lands_inside_a_tick(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`app.lifespan` cancels this task and then waits for it, so it has to end.

    The cancel arriving while the loop is parked between passes was always fine. The one that
    matters is the other one: a tick sits in a thread for as long as `land.land` takes — `make
    install` and then the repository's own gate — and a cancellation swallowed there leaves the
    loop running and the TaskGroup holding it waiting for a task that never finishes.
    """
    in_a_tick = asyncio.Event()

    async def slow(store: Store, live: set[str] | None = None) -> None:
        in_a_tick.set()
        await asyncio.sleep(30)

    monkeypatch.setattr(autostart, "tick", slow)

    running = asyncio.create_task(autostart.run(desk))
    await in_a_tick.wait()
    running.cancel()
    _, pending = await asyncio.wait({running}, timeout=1)

    for task in pending:
        # It went round again and is now in the sleep, where a cancel does land. Ending it here
        # rather than leaving it for the loop to be torn down with.
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    assert not pending, "the loop swallowed the cancellation and went on running"


@pytest.mark.unit
async def test_open_pull_requests_become_blockers_and_never_queued_work(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ "В качестве блокеров также могут висеть PR с github, которые ожидают ревью/апрува/мержа —
    для тех проектов, которые подключили гитхаб как коннектор."

    Never queued: a review is not something an agent can give."""
    from agent_desk.tracker import github

    await desk.set_link(
        repo_key=KEY,
        name="github",
        url="https://github.com/owner/name",
        token_env="GH_TOKEN",
        kind="github",
    )
    monkeypatch.setattr(
        github,
        "open_pulls",
        lambda repo, token_env: github.Read(
            True,
            pulls=(
                github.Pull(
                    number=12,
                    title="rewrite the parser",
                    url="https://github.com/owner/name/pull/12",
                    waiting_for="waiting for a review from biba",
                ),
            ),
        ),
    )

    assert await autostart.pull_requests(desk, await desk.autostart(KEY)) == 1

    (stuck,) = await desk.tracker_blockers()
    assert stuck.key == "#12"
    assert "review from biba" in stuck.said
    assert "pull/12" in stuck.said
    # Nothing was queued: a review is not work an agent can take on.
    assert await desk.tasks(repo_key=KEY) == []


@pytest.mark.unit
async def test_a_github_link_with_no_credential_reads_nothing(desk: Store) -> None:
    """A link with no token variable is a link, not a destination — the same rule everywhere."""
    await desk.set_link(
        repo_key=KEY, name="github", url="https://github.com/owner/name", kind="github"
    )

    assert await autostart.pull_requests(desk, await desk.autostart(KEY)) == 0
    assert await desk.tracker_blockers() == []


@pytest.mark.unit
async def test_a_pull_that_was_merged_stops_being_a_blocker(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replaced on every read, so somebody merging a pull request is all it takes."""
    from agent_desk.tracker import github

    await desk.set_link(
        repo_key=KEY, name="github", url="https://github.com/owner/name", token_env="GH_TOKEN"
    )
    monkeypatch.setattr(
        github,
        "open_pulls",
        lambda repo, token_env: github.Read(
            True, pulls=(github.Pull(number=12, title="x", url="u", waiting_for="waiting"),)
        ),
    )
    await autostart.pull_requests(desk, await desk.autostart(KEY))
    assert len(await desk.tracker_blockers()) == 1

    monkeypatch.setattr(github, "open_pulls", lambda repo, token_env: github.Read(True, pulls=()))
    await autostart.pull_requests(desk, await desk.autostart(KEY))

    assert await desk.tracker_blockers() == []


@pytest.mark.unit
async def test_a_ticket_and_a_pull_request_do_not_erase_each_other(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """They live in the same table because they are the same thing to somebody reading the column,
    and each read must only replace its own kind."""
    from agent_desk.tracker import github

    await desk.replace_tracker_blockers(KEY, [("DUCK-3", "the import", "Blocked on a vendor.")])
    await desk.set_link(
        repo_key=KEY, name="github", url="https://github.com/owner/name", token_env="GH_TOKEN"
    )
    monkeypatch.setattr(
        github,
        "open_pulls",
        lambda repo, token_env: github.Read(
            True, pulls=(github.Pull(number=12, title="x", url="u", waiting_for="waiting"),)
        ),
    )

    await autostart.pull_requests(desk, await desk.autostart(KEY))

    keys = {one.key for one in await desk.tracker_blockers()}
    assert keys == {"DUCK-3", "#12"}
