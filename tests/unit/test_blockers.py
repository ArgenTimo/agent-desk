"""What is actually stopped, and the two things this column still refuses to claim.

The three placeholders that stood here for a year were the right refusal to the wrong question:
a guessed blocker is CLAUDE.md's fifth rule broken, but every card here is a fact this console
wrote down about its *own* work. So most of these assert what is on a card, and the last one
asserts what is still not.
"""

from __future__ import annotations

import pathlib
from collections.abc import AsyncIterator
from types import SimpleNamespace

import pytest
from agent_desk.ideas import inbox
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
async def test_a_failed_task_holds_up_the_ideas_it_was_going_to_build(
    desk: Store, tmp_path: pathlib.Path
) -> None:
    """And not the rest of the project's queue, which is what it used to claim.

    The old count was every waiting task in the blocker's project, put on every blocker in it: a
    project with three blockers and five queued tasks showed five on each of the three, the same
    five. What a failed task actually stops is the ideas it recorded when it was queued, and
    those are the ones somebody wants named.
    """
    wanted = await inbox.capture(desk, "cache the probe results", project_key=KEY)
    other = await inbox.capture(desk, "something else entirely", project_key=KEY)
    stuck = await desk.queue_task(
        repo_key=KEY,
        cwd=str(tmp_path),
        title="the one that failed",
        instruction="x",
        source_kind="idea",
        source_ref=wanted.id,
    )
    await desk.task_failed(stuck.id, "it fell over")
    # Queued work of its own, in the same project, which this blocker does not stop.
    for number in range(3):
        await desk.queue_task(
            repo_key=KEY,
            cwd=str(tmp_path),
            title=f"waiting {number}",
            instruction="x",
            source_kind="instruction",
        )

    (found,) = await blockers.blockers(desk)

    assert [held.id for held in found.holding_up] == [wanted.id]
    assert found.holds == 1
    assert other.id not in [held.id for held in found.holding_up]
    assert found.holding_up[0].card == f"idea:{wanted.id}", (
        "the thing that is stuck cannot be opened from the blocker holding it up"
    )
    assert found.roughly, "an estimate that is named as a rule of thumb beats saying nothing"


@pytest.mark.unit
async def test_an_idea_that_got_built_anyway_is_not_still_held_up(
    desk: Store, tmp_path: pathlib.Path
) -> None:
    """A blocker naming work that is finished is a blocker nobody trusts twice."""
    idea = await inbox.capture(desk, "cache the probe results", project_key=KEY)
    stuck = await desk.queue_task(
        repo_key=KEY,
        cwd=str(tmp_path),
        title="the one that failed",
        instruction="x",
        source_kind="idea",
        source_ref=idea.id,
    )
    await desk.task_failed(stuck.id, "it fell over")
    await desk.set_idea_state(idea.id, "done")

    (found,) = await blockers.blockers(desk)

    assert found.holding_up == ()


@pytest.mark.unit
async def test_a_project_that_switched_itself_off_holds_up_its_whole_queue(
    desk: Store, tmp_path: pathlib.Path
) -> None:
    """This is the one case where the project's queue *is* the answer: nothing in it can start
    while the switch is off, which is a causal link rather than a shared label."""
    idea = await inbox.capture(desk, "the deferred one", project_key=KEY)
    await desk.queue_task(
        repo_key=KEY,
        cwd=str(tmp_path),
        title="from an idea",
        instruction="x",
        source_kind="idea",
        source_ref=idea.id,
    )
    await desk.queue_task(
        repo_key=KEY,
        cwd=str(tmp_path),
        title="found work",
        instruction="x",
        source_kind="found",
    )
    await desk.arm(KEY, per_hour=2)
    await desk.disarm(KEY, why="two in a row died")

    found = [one for one in await blockers.blockers(desk) if one.kind == "project"]

    assert len(found) == 1
    held = found[0].holding_up
    assert len(held) == 2
    # An idea where the task names one, and the task itself where it does not — a queued piece of
    # work with no idea behind it is still something somebody is waiting for.
    assert {one.kind for one in held} == {"idea", "task"}
    assert idea.id in [one.id for one in held]


@pytest.mark.unit
async def test_a_switched_off_session_belongs_to_the_project_it_is_checked_out_in(
    desk: Store, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """It used to belong to nothing, which meant it showed under every project's filter and was
    counted under none of them — the "не правильно мапятся на проекты" of the report."""
    blockers._projects.clear()
    monkeypatch.setattr(blockers, "repository_of", lambda cwd: SimpleNamespace(key=KEY, name="api"))
    await desk.kick_session("abc123", on=True, session_id="abc123-full", cwd=str(tmp_path))
    await desk.stop_kicking("abc123", why="two in a row failed")

    found = [one for one in await blockers.blockers(desk) if one.kind == "session"]

    assert len(found) == 1
    assert found[0].repo_key == KEY, "a switched-off session is still somebody's project's problem"
    assert found[0].about_a_project
    assert await blockers.blockers(desk, only=KEY), "it is filtered out of its own project"


@pytest.mark.unit
async def test_a_blocker_about_no_project_says_so_rather_than_reading_as_yours(desk: Store) -> None:
    """A failed question belongs to no project. It survives a project filter — hiding it behind
    one it was never part of would lose it — and the card says which of the two it is."""
    thread = await desk.create_thread("why is it slow")
    block = await desk.create_block(
        thread_id=thread.id, kind="question", input="why is it slow", thread_set_by="human"
    )
    await desk.fail_block(block.id, "the run came back empty")

    (found,) = await blockers.blockers(desk, only=KEY)

    assert found.kind == "answer"
    assert not found.about_a_project
    assert found.repo_key == ""


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


@pytest.mark.unit
async def test_the_column_renders_what_is_held_up_by_name(
    desk: Store, tmp_path: pathlib.Path
) -> None:
    """StrictUndefined means a template referring to a field the dataclass lost is a 500 at the
    moment somebody opens the board, not a caught test. This renders the real one."""
    from agent_desk.web.routes import env

    idea = await inbox.capture(desk, "cache the probe results", project_key=KEY)
    stuck = await desk.queue_task(
        repo_key=KEY,
        cwd=str(tmp_path),
        title="the one that failed",
        instruction="x",
        source_kind="idea",
        source_ref=idea.id,
    )
    await desk.task_failed(stuck.id, "it fell over")

    html = env.get_template("_blockers.html").render(found=await blockers.blockers(desk), only="")

    assert "holding up 1 thing" in html
    assert "cache the probe results" in html
    assert "a job that failed" in html, "the card still shows this program's word for the kind"
    assert f'data-card="idea:{idea.id}"' in html, "what is stuck cannot be dragged onto the bench"


@pytest.mark.unit
async def test_the_open_card_renders_for_every_kind_of_blocker(
    desk: Store, tmp_path: pathlib.Path
) -> None:
    """One template, six kinds, and StrictUndefined between them."""
    from agent_desk.web.routes import env

    await desk.arm(KEY, per_hour=2)
    await desk.disarm(KEY, why="two starts in a row failed")
    await desk.kick_session("abc12345", on=True, session_id="abc-x", cwd=str(tmp_path))
    await desk.stop_kicking("abc12345", why="two in a row failed")
    stuck = await desk.queue_task(
        repo_key=KEY, cwd=str(tmp_path), title="a job", instruction="x", source_kind="instruction"
    )
    await desk.task_failed(stuck.id, "it fell over")

    kinds = set()
    for one in await blockers.blockers(desk):
        kinds.add(one.kind)
        html = env.get_template("_card_blocker.html").render(one=one, card_id=one.id)
        assert "What is waiting on it" in html
        assert "Which project it belongs to" in html

    assert kinds == {"project", "session", "task"}


@pytest.mark.unit
def test_every_kind_a_blocker_can_be_has_plain_words_for_it() -> None:
    """A card that prints `kind` asks the reader to learn six of this program's words. Both maps
    are keyed by the same set, and a kind missing from either is a card that says nothing useful
    or offers no sense of what clearing it costs."""
    assert set(blockers.PLAINLY) == set(blockers.ROUGHLY)


@pytest.mark.unit
async def test_a_stuck_ticket_names_the_idea_this_console_filed_as_it(desk: Store) -> None:
    """The one link a ticket blocker is allowed to draw: the filing this program wrote itself
    when somebody sent the idea to the board (docs/adr/0005). Not "ideas in the same project",
    which would be a picture of a guess in the column that exists to refuse them."""
    idea = await inbox.capture(desk, "cache the probe results", project_key=KEY)
    other = await inbox.capture(desk, "unrelated, same project", project_key=KEY)
    await desk.record_filing(
        idea_id=idea.id, tracker="jira", issue_key="API-42", url="https://x/API-42"
    )
    await desk.replace_tracker_blockers(KEY, [("API-42", "cache probes", "waiting on infra")])

    (found,) = await blockers.blockers(desk)

    assert found.kind == "ticket"
    assert [held.id for held in found.holding_up] == [idea.id]
    assert other.id not in [held.id for held in found.holding_up]


@pytest.mark.unit
async def test_a_pull_request_is_its_own_kind_rather_than_a_ticket_with_a_hash(
    desk: Store,
) -> None:
    """They both stop on a person and they are still not the same thing to somebody deciding what
    to do about one. The column used to call both "ticket" and leave the `#` to explain it."""
    await desk.replace_tracker_blockers(KEY, [("#7", "the folder cards", "waiting for review")])

    (found,) = await blockers.blockers(desk)

    assert found.kind == "pull"
    assert found.holding_up == (), "nothing here records what a pull request is holding up"


@pytest.mark.unit
async def test_a_session_in_a_directory_that_is_not_a_checkout_still_gets_a_project(
    desk: Store, tmp_path: pathlib.Path
) -> None:
    """A folder somebody works in without git is its own project, which is what
    `repository_of` says and what this must not second-guess."""
    blockers._projects.clear()
    await desk.kick_session("abc999", on=True, session_id="abc999-x", cwd=str(tmp_path))
    await desk.stop_kicking("abc999", why="two in a row failed")

    (found,) = await blockers.blockers(desk)

    assert found.repo_key == f"dir:{tmp_path}"
    # And it is remembered, because this runs on every render of the column.
    assert blockers._projects[str(tmp_path)] == f"dir:{tmp_path}"


@pytest.mark.unit
async def test_a_session_whose_directory_has_gone_belongs_to_nothing(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The blocker is still real — the session did stop being kept going. It simply cannot be
    filed under a project, and an empty key is how that is said."""
    blockers._projects.clear()

    def gone(cwd: str) -> object:
        raise OSError("no such directory")

    monkeypatch.setattr(blockers, "repository_of", gone)
    await desk.kick_session("abc998", on=True, session_id="abc998-x", cwd="/gone")
    await desk.stop_kicking("abc998", why="two in a row failed")

    (found,) = await blockers.blockers(desk)

    assert found.repo_key == ""
    assert not found.about_a_project
