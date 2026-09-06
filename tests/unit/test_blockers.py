"""What is actually stopped, and the two things this column still refuses to claim.

The three placeholders that stood here for a year were the right refusal to the wrong question:
a guessed blocker is CLAUDE.md's fifth rule broken, but every card here is a fact this console
wrote down about its *own* work. So most of these assert what is on a card, and the last one
asserts what is still not.
"""

from __future__ import annotations

import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk.store.repo import Store
from agent_desk.web import blockers

KEY = "origin:acme/api"


@pytest.fixture
async def desk(tmp_path: pathlib.Path) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    yield store
    await store.close()


@pytest.mark.unit
async def test_a_console_where_nothing_is_stuck_shows_nothing(desk: Store) -> None:
    assert await blockers.blockers(desk) == []


@pytest.mark.unit
async def test_a_task_that_failed_is_a_blocker_with_the_reason_and_a_retry(
    desk: Store, tmp_path: pathlib.Path
) -> None:
    task = await desk.queue_task(
        repo_key=KEY,
        cwd=str(tmp_path),
        title="build the thing",
        instruction="build it",
        source_kind="instruction",
    )
    await desk.task_failed(task.id, "the worktree name was not one the CLI would take")

    found = await blockers.blockers(desk)

    assert len(found) == 1
    assert found[0].kind == "task"
    assert found[0].what == "build the thing"
    assert "worktree name" in found[0].why
    # A blocker whose fix is one click and does not offer it is not much of a card.
    assert found[0].action == f"/tasks/{task.id}/retry"


@pytest.mark.unit
async def test_a_branch_a_gate_refused_is_work_nobody_has_read(
    desk: Store, tmp_path: pathlib.Path
) -> None:
    """docs/adr/0008: it merges when the project's own gate passes. When it does not, the branch
    sits in a worktree, and that is exactly a thing that has stopped."""
    task = await desk.queue_task(
        repo_key=KEY,
        cwd=str(tmp_path),
        title="looking for something to fix",
        instruction="find one",
        source_kind="found",
    )
    await desk.take_next_task(KEY)
    await desk.task_started(task.id, "agent1")
    await desk.finish_task(task.id)
    await desk.task_landed(task.id, "not merged: `make verify` failed: 1 test", landed=False)

    found = await blockers.blockers(desk)

    assert [one.kind for one in found] == ["branch"]
    assert "make verify" in found[0].why


@pytest.mark.unit
async def test_a_switch_that_turned_itself_off_says_so_here(
    desk: Store, tmp_path: pathlib.Path
) -> None:
    """Both of them: a project that stopped starting work (docs/adr/0007) and a session that
    stopped being kept going (docs/adr/0009)."""
    await desk.arm(KEY, per_hour=2)
    await desk.disarm(KEY, why="two starts in a row failed: no such directory")
    await desk.kick_session("abc12345", on=True, session_id="abc12345-x", cwd=str(tmp_path))
    await desk.stop_kicking("abc12345", why="two in a row failed: it would not resume")

    found = {one.kind: one for one in await blockers.blockers(desk)}

    assert "no such directory" in found["project"].why
    assert "would not resume" in found["session"].why
    # The project card is draggable into the middle, because there is one to drag.
    assert found["project"].card == f"project:{KEY}"


@pytest.mark.unit
async def test_the_newest_thing_that_stopped_is_at_the_top(
    desk: Store, tmp_path: pathlib.Path
) -> None:
    """A column somebody glances at is read from the top."""
    for title in ("the older one", "the newer one"):
        task = await desk.queue_task(
            repo_key=KEY,
            cwd=str(tmp_path),
            title=title,
            instruction="build it",
            source_kind="instruction",
        )
        await desk.task_failed(task.id, "it fell over")

    found = await blockers.blockers(desk)

    assert [one.what for one in found] == ["the newer one", "the older one"]


@pytest.mark.unit
async def test_a_column_of_forty_is_a_column_nobody_reads(
    desk: Store, tmp_path: pathlib.Path
) -> None:
    for number in range(blockers.MOST_SHOWN + 5):
        task = await desk.queue_task(
            repo_key=KEY,
            cwd=str(tmp_path),
            title=f"task {number}",
            instruction="build it",
            source_kind="instruction",
        )
        await desk.task_failed(task.id, "it fell over")

    assert len(await blockers.blockers(desk)) == blockers.MOST_SHOWN


@pytest.mark.unit
def test_the_two_things_this_column_still_will_not_claim() -> None:
    """ "Waiting on a person" and "waiting on a run" are not on disk. The first is rendered as an
    inference on the session card, in amber; neither is ever a red card here (CLAUDE.md, rule
    five)."""
    source = pathlib.Path(blockers.__file__).read_text()
    assert "waiting on a person" in source, "the refusal is written down where it applies"
    for line in source.splitlines():
        if line.strip().startswith("kind="):
            assert "waiting" not in line


@pytest.mark.unit
async def test_a_blocker_has_a_name_of_its_own_so_it_can_be_dragged_and_opened(
    desk: Store, tmp_path: pathlib.Path
) -> None:
    """A card somebody can only look at from the corner of their eye is one they cannot act on."""
    task = await desk.queue_task(
        repo_key=KEY,
        cwd=str(tmp_path),
        title="build the thing",
        instruction="build it",
        source_kind="instruction",
    )
    await desk.task_failed(task.id, "it fell over")

    found = await blockers.blockers(desk)
    assert found[0].id == f"task:{task.id}"

    opened = await blockers.one(desk, found[0].id)
    assert opened is not None and opened.what == "build the thing"


@pytest.mark.unit
async def test_a_blocker_that_cleared_is_gone_rather_than_an_error(
    desk: Store, tmp_path: pathlib.Path
) -> None:
    """A blocker is a view of facts that live elsewhere. Gone is the ordinary outcome — it means
    the thing got unstuck."""
    task = await desk.queue_task(
        repo_key=KEY,
        cwd=str(tmp_path),
        title="build the thing",
        instruction="build it",
        source_kind="instruction",
    )
    await desk.task_failed(task.id, "it fell over")
    stuck = (await blockers.blockers(desk))[0].id

    # What "retry" does: the failed row goes and a fresh one takes its place.
    await desk.drop_task(task.id)

    assert await blockers.one(desk, stuck) is None


@pytest.mark.unit
async def test_a_blocker_says_what_it_is_holding_up_and_roughly_what_it_costs(
    desk: Store, tmp_path: pathlib.Path
) -> None:
    """The two things that decide whether somebody clears it now or after lunch."""
    stuck = await desk.queue_task(
        repo_key=KEY,
        cwd=str(tmp_path),
        title="the one that failed",
        instruction="x",
        source_kind="instruction",
    )
    await desk.task_failed(stuck.id, "it fell over")
    for number in range(3):
        await desk.queue_task(
            repo_key=KEY,
            cwd=str(tmp_path),
            title=f"waiting {number}",
            instruction="x",
            source_kind="instruction",
        )

    (found,) = await blockers.blockers(desk)

    assert found.holding_up == 3
    assert found.roughly, "an estimate that is named as a rule of thumb beats saying nothing"


@pytest.mark.unit
async def test_saying_a_blocker_is_cleared_does_not_clear_it(
    desk: Store, tmp_path: pathlib.Path
) -> None:
    """The whole design: a blocker that vanished because a button was pressed is one that comes
    back as a surprise when the agent waiting on it fails for the same reason."""
    stuck = await desk.queue_task(
        repo_key=KEY,
        cwd=str(tmp_path),
        title="the one that failed",
        instruction="x",
        source_kind="instruction",
    )
    await desk.task_failed(stuck.id, "it fell over")
    (found,) = await blockers.blockers(desk)

    await desk.claim_cleared(found.id)

    (still,) = await blockers.blockers(desk)
    assert still.claimed, "it has to say a claim was made"
    assert still.checked == "", "and that nothing has checked yet"


@pytest.mark.unit
async def test_a_claim_that_was_right_takes_the_blocker_with_it(
    desk: Store, tmp_path: pathlib.Path
) -> None:
    """Checked by recomputing rather than by asking anybody: every blocker here was computed from
    something the console can look at again."""
    from agent_desk.web import autostart

    stuck = await desk.queue_task(
        repo_key=KEY,
        cwd=str(tmp_path),
        title="the one that failed",
        instruction="x",
        source_kind="instruction",
    )
    await desk.task_failed(stuck.id, "it fell over")
    (found,) = await blockers.blockers(desk)
    await desk.claim_cleared(found.id)

    # Somebody retried it, so it is not stuck any more.
    await desk.drop_task(stuck.id)

    assert await autostart.check_claims(desk) == 1
    assert await blockers.blockers(desk) == []
    assert await desk.claims() == {}, "nothing left to remember"


@pytest.mark.unit
async def test_a_claim_that_was_wrong_is_answered_with_the_reason(
    desk: Store, tmp_path: pathlib.Path
) -> None:
    """ "Только если разблокировано — блок уходит." Otherwise it says why it is still there."""
    from agent_desk.web import autostart

    stuck = await desk.queue_task(
        repo_key=KEY,
        cwd=str(tmp_path),
        title="the one that failed",
        instruction="x",
        source_kind="instruction",
    )
    await desk.task_failed(stuck.id, "the worktree name was not one the CLI would take")
    (found,) = await blockers.blockers(desk)
    await desk.claim_cleared(found.id)

    assert await autostart.check_claims(desk) == 1

    (still,) = await blockers.blockers(desk)
    assert not still.claimed
    assert "still blocked" in still.checked
    assert "worktree name" in still.checked


@pytest.mark.unit
async def test_checking_nothing_costs_nothing(desk: Store) -> None:
    """The ordinary case on every tick."""
    from agent_desk.web import autostart

    assert await autostart.check_claims(desk) == 0
