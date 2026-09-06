"""The buttons that decide something, rather than record something about it.

The pool had four states and no way to act. Everything on a card said what somebody *thought* —
keep it, discard it, write it up — and the only door from a thought to work went through a typed
message and the classifier. These are the presses that were missing, and the routes behind them.
"""

from __future__ import annotations

import pathlib
from collections.abc import AsyncIterator
from types import SimpleNamespace

import pytest
from agent_desk.ideas import inbox
from agent_desk.store.repo import Store
from agent_desk.web import routes

KEY = "origin:acme/api"


@pytest.fixture
async def desk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    yield store
    await store.close()


@pytest.fixture
def a_project(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """One project with one checkout, which is what "build it" needs to have somewhere to run."""
    monkeypatch.setattr(
        routes,
        "shape",
        lambda rows, groups: [
            SimpleNamespace(key=KEY, name="api", instances=[SimpleNamespace(path=str(tmp_path))])
        ],
    )
    monkeypatch.setattr(routes, "board", lambda: ([], 0))


@pytest.mark.unit
async def test_build_it_puts_the_idea_in_its_project_s_queue(
    desk: Store, a_project: None, tmp_path: pathlib.Path
) -> None:
    """The decision the column did not have. It queues rather than starts: docs/adr/0007 says the
    loop decides when, and the arming switch is where that was already answered."""
    idea = await inbox.capture(desk, "cache the probe results", project_key=KEY)

    await routes._build_it(idea)

    (task,) = await desk.tasks()
    assert task.repo_key == KEY
    assert task.cwd == str(tmp_path)
    assert task.instruction == "cache the probe results"
    assert task.source_kind == "idea"
    # What gets marked built when its agent finishes (agent_desk/web/autostart.py).
    assert task.source_ref == idea.id
    assert task.waiting


@pytest.mark.unit
async def test_an_idea_pointed_at_nothing_queues_nothing(desk: Store, a_project: None) -> None:
    """There is nowhere to do it, and inventing a destination would be worse than a button that
    visibly does nothing."""
    idea = await inbox.capture(desk, "a thought about nothing in particular")

    await routes._build_it(idea)

    assert await desk.tasks() == []


@pytest.mark.unit
async def test_an_idea_whose_project_has_no_checkout_here_queues_nothing(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(routes, "board", lambda: ([], 0))
    monkeypatch.setattr(
        routes, "shape", lambda rows, groups: [SimpleNamespace(key=KEY, name="api", instances=[])]
    )
    idea = await inbox.capture(desk, "cache the probe results", project_key=KEY)

    await routes._build_it(idea)

    assert await desk.tasks() == []


@pytest.mark.unit
async def test_putting_an_idea_off_reads_the_same_phrases_a_message_does(desk: Store) -> None:
    """The control offers a handful of phrases and they go through `waking.read`, the function
    that reads one out of a typed message. Two readers of the same phrase would drift."""
    from datetime import UTC, datetime

    from agent_desk.ideas import waking

    for said, expected in (
        ("tomorrow", "at"),
        ("next week", "at"),
        ("in 2 hours", "at"),
        ("когда освободится", "free"),
        ("once the gate is green", "gate"),
    ):
        wake = waking.read(said, now=datetime.now(UTC))
        assert wake is not None, f"the control offers {said!r} and nothing reads it"
        if expected == "at":
            assert wake.at is not None
        else:
            assert wake.when == expected


@pytest.mark.unit
async def test_the_answer_to_is_it_built_is_a_persons_and_writes_only_the_shape(
    desk: Store,
) -> None:
    """ "No, it does not exist" corrects what a background pass read out of the words. It must not
    touch `state`, which is the column a person sets by keeping or discarding — saying the pass
    was wrong is not the same act as saying what to do about the idea."""
    idea = await inbox.capture(desk, "cache the probe results", project_key=KEY)
    await desk.appraise_idea(idea.id, size="small", shape="built")

    await desk.set_idea_shape(idea.id, "")

    again = await desk.idea(idea.id)
    assert again is not None
    assert again.shape == ""
    assert again.state == "new", "answering a question about the text moved the idea's state"
    assert again.size == "small", "the rest of the appraisal was thrown away with the answer"


@pytest.mark.unit
async def test_the_column_offers_the_decisions_on_a_live_card(desk: Store, a_project: None) -> None:
    """StrictUndefined, and a template that renders in a test but not on the board is a 500 in
    front of somebody."""
    idea = await inbox.capture(desk, "cache the probe results", project_key=KEY)
    await desk.appraise_idea(idea.id, size="small", shape="built")

    html = await routes.render_ideas()

    assert f"/ideas/{idea.id}/build" in html, "there is no way to turn an idea into work"
    assert f"/ideas/{idea.id}/later" in html, "there is no way to put one off"
    assert f"/ideas/{idea.id}/shape" in html, "the is-it-built question still has no answer"
    assert "no, it does not" in html
    assert "yes, it exists" in html
    assert "when nothing is running" in html


@pytest.mark.unit
async def test_a_deferred_idea_offers_the_way_back_instead_of_the_menu(
    desk: Store, a_project: None
) -> None:
    await inbox.capture(desk, "напомни завтра про хинты", project_key=KEY)

    html = await routes.render_ideas()

    assert "bring it back now" in html
    assert "comes back" in html
    assert "not now, ask me" not in html, "a deferred idea is offered the deferral menu again"


@pytest.mark.unit
async def test_a_discarded_idea_is_offered_no_decisions(desk: Store, a_project: None) -> None:
    """Every one of these is about work that is going to happen. On something somebody has
    already said no to, they are noise at best."""
    idea = await inbox.capture(desk, "cache the probe results", project_key=KEY)
    await desk.set_idea_state(idea.id, "dropped")

    html = await routes.render_ideas()

    assert f"/ideas/{idea.id}/build" not in html
    assert f"/ideas/{idea.id}/later" not in html


async def _post(path: str, fields: dict[str, str]) -> tuple[int, str]:
    from tests.unit.test_input import _post as post

    status, html, _ = await post(path, fields, htmx=True)
    return status, html


@pytest.mark.unit
async def test_the_route_behind_build_it(desk: Store, a_project: None) -> None:
    idea = await inbox.capture(desk, "cache the probe results", project_key=KEY)

    status, _ = await _post(f"/ideas/{idea.id}/build", {"from": "column"})

    assert status == 200
    assert len(await desk.tasks()) == 1


@pytest.mark.unit
async def test_the_route_behind_later_and_the_way_back_out(desk: Store, a_project: None) -> None:
    idea = await inbox.capture(desk, "cache the probe results", project_key=KEY)

    await _post(f"/ideas/{idea.id}/later", {"from": "column", "when": "tomorrow"})
    stored = await desk.idea(idea.id)
    assert stored is not None and stored.deferred

    await _post(f"/ideas/{idea.id}/later", {"from": "column", "when": "never"})
    stored = await desk.idea(idea.id)
    assert stored is not None and not stored.deferred


@pytest.mark.unit
async def test_a_phrase_with_no_moment_in_it_defers_nothing(desk: Store, a_project: None) -> None:
    """The empty option on the control. Reading a moment out of nothing would put somebody's
    idea in a queue they never asked for."""
    idea = await inbox.capture(desk, "cache the probe results", project_key=KEY)

    await _post(f"/ideas/{idea.id}/later", {"from": "column", "when": ""})

    stored = await desk.idea(idea.id)
    assert stored is not None and not stored.deferred


@pytest.mark.unit
async def test_the_route_behind_the_answer_to_is_it_built(desk: Store, a_project: None) -> None:
    idea = await inbox.capture(desk, "cache the probe results", project_key=KEY)
    await desk.appraise_idea(idea.id, size="small", shape="built")

    await _post(f"/ideas/{idea.id}/shape", {"from": "column", "shape": "none"})

    stored = await desk.idea(idea.id)
    assert stored is not None and stored.shape == ""
    assert stored.state == "new"


@pytest.mark.unit
async def test_a_shape_this_program_does_not_have_is_refused(desk: Store, a_project: None) -> None:
    """The path segment is validated; so is the field. A select is not a promise about the body."""
    idea = await inbox.capture(desk, "cache the probe results", project_key=KEY)
    await desk.appraise_idea(idea.id, size="small", shape="built")

    await _post(f"/ideas/{idea.id}/shape", {"from": "column", "shape": "whatever I like"})

    stored = await desk.idea(idea.id)
    assert stored is not None and stored.shape == "built"


@pytest.mark.unit
async def test_a_discarded_idea_cannot_be_built_or_deferred_through_the_route(
    desk: Store, a_project: None
) -> None:
    """The template hides the buttons; the route has to mean it."""
    idea = await inbox.capture(desk, "cache the probe results", project_key=KEY)
    await desk.set_idea_state(idea.id, "dropped")

    status, _ = await _post(f"/ideas/{idea.id}/build", {"from": "column"})

    assert status == 409
    assert await desk.tasks() == []


@pytest.mark.unit
async def test_running_the_gate_again_on_a_branch_that_would_not_merge(
    desk: Store, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What somebody does about an unmerged branch once they have pushed a fix — and it was two
    pages away from the card that named it."""
    from agent_desk import land

    task = await desk.queue_task(
        repo_key=KEY, cwd=str(tmp_path), title="a change", instruction="x", source_kind="found"
    )
    await desk.take_next_task(KEY)
    await desk.finish_task(task.id)
    await desk.task_landed(task.id, "not merged: the gate said no", landed=False)

    offered: list[tuple[str, str]] = []

    def second_time(cwd: str, worktree: str, *, push: bool = True) -> land.Landed:
        offered.append((cwd, worktree))
        return land.Landed(landed=True, detail="merged", branch="worktree-a-change")

    monkeypatch.setattr(routes.land, "land", second_time)

    await _post(f"/tasks/{task.id}/land", {"key": KEY})

    assert offered == [(str(tmp_path), routes.autostart.worktree_of(task))]
    again = next(one for one in await desk.tasks() if one.id == task.id)
    assert again.landed is True
    assert again.detail == "merged"


@pytest.mark.unit
async def test_a_task_that_never_finished_is_not_offered_to_the_gate(
    desk: Store, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """There is no branch yet. Running a gate on one would be running it on whatever the worktree
    happened to contain."""

    def never(*args: object, **kwargs: object) -> object:  # pragma: no cover - must not be called
        raise AssertionError("the gate was run on a task that has not finished")

    monkeypatch.setattr(routes.land, "land", never)
    task = await desk.queue_task(
        repo_key=KEY, cwd=str(tmp_path), title="a change", instruction="x", source_kind="found"
    )

    status, _ = await _post(f"/tasks/{task.id}/land", {"key": KEY})

    assert status == 200


@pytest.mark.unit
async def test_build_it_starts_straight_away_when_the_project_is_armed(
    desk: Store, a_project: None, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ "Пусть сразу запускается если проект армирован." Pressing a button and watching nothing
    happen for a minute is the wrong answer to "build it", and the switch is where somebody
    already said this project may start work by itself."""
    started: list[str] = []

    def start(task: object, *, cwd: str, name: str) -> object:
        started.append(name)
        return SimpleNamespace(started=True, agent_id="agent-1", detail="")

    monkeypatch.setattr(routes.dispatch, "start", start)
    monkeypatch.setattr(routes.autostart, "live_agents", lambda: set())
    await desk.arm(KEY, per_hour=4)
    idea = await inbox.capture(desk, "cache the probe results", project_key=KEY)

    await routes._build_it(idea)

    assert started == ["cache the probe results"]
    (task,) = await desk.tasks()
    assert not task.waiting, "it was queued and left there on an armed project"
    assert task.agent_id == "agent-1"


@pytest.mark.unit
async def test_build_it_only_queues_when_the_project_is_not_armed(
    desk: Store, a_project: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Off is the default and it means what it says. The queue is where the work waits until
    somebody switches the project on or presses start on it themselves."""

    def never(*args: object, **kwargs: object) -> object:  # pragma: no cover
        raise AssertionError("an agent was started in a project nobody armed")

    monkeypatch.setattr(routes.dispatch, "start", never)
    idea = await inbox.capture(desk, "cache the probe results", project_key=KEY)

    await routes._build_it(idea)

    (task,) = await desk.tasks()
    assert task.waiting


@pytest.mark.unit
async def test_build_it_respects_the_seat_the_loop_respects(
    desk: Store, a_project: None, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One agent at a time in a project, which is the loop's rule and not a different one — the
    button asks `why_not`, the same function the loop asks."""
    monkeypatch.setattr(routes.autostart, "live_agents", lambda: {"agent-0"})
    monkeypatch.setattr(routes.autostart, "still_going", lambda agent, live: (True, None))

    def never(*args: object, **kwargs: object) -> object:  # pragma: no cover
        raise AssertionError("a second agent was started in a project already running one")

    monkeypatch.setattr(routes.dispatch, "start", never)
    await desk.arm(KEY, per_hour=4)
    busy = await desk.queue_task(
        repo_key=KEY, cwd=str(tmp_path), title="already going", instruction="x", source_kind="idea"
    )
    await desk.take_next_task(KEY)
    await desk.task_started(busy.id, "agent-0")

    idea = await inbox.capture(desk, "cache the probe results", project_key=KEY)
    await routes._build_it(idea)

    queued = [one for one in await desk.tasks() if one.waiting]
    assert len(queued) == 1, "it jumped a seat the loop would have waited for"


@pytest.mark.unit
async def test_a_start_that_fails_is_recorded_on_the_task_rather_than_lost(
    desk: Store, a_project: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed start with nothing written down is a task that reads as running forever."""

    def refuses(task: object, *, cwd: str, name: str) -> object:
        return SimpleNamespace(started=False, agent_id="", detail="no such directory")

    monkeypatch.setattr(routes.dispatch, "start", refuses)
    monkeypatch.setattr(routes.autostart, "live_agents", lambda: set())
    await desk.arm(KEY, per_hour=4)
    idea = await inbox.capture(desk, "cache the probe results", project_key=KEY)

    await routes._build_it(idea)

    (task,) = await desk.tasks()
    assert task.failed_at is not None
    assert task.detail == "no such directory"


@pytest.mark.unit
async def test_the_last_thing_done_to_an_idea_can_be_put_back(desk: Store, a_project: None) -> None:
    """Discard is one press and the idea leaves the column. Before this the only way back was to
    go and find it in the inbox — a different page and a different frame of mind, which in
    practice means nobody goes and the press quietly becomes permanent."""
    idea = await inbox.capture(desk, "cache the probe results", project_key=KEY)
    await desk.set_idea_state(idea.id, "kept")

    await _post(f"/ideas/{idea.id}/drop", {"from": "column"})
    assert (await desk.idea(idea.id)).state == "dropped"  # type: ignore[union-attr]

    html = await routes.render_ideas()
    assert "discarded" in html and "undo" in html

    await _post("/ideas/undo", {})

    assert (await desk.idea(idea.id)).state == "kept", (
        "it came back as something other than what it was"
    )


@pytest.mark.unit
async def test_undo_puts_back_the_state_this_program_recorded_not_one_it_is_sent(
    desk: Store, a_project: None
) -> None:
    """A form field naming a state would be a way to set any state on any idea from anywhere."""
    idea = await inbox.capture(desk, "cache the probe results", project_key=KEY)
    await _post(f"/ideas/{idea.id}/drop", {"from": "column"})

    await _post("/ideas/undo", {"was": "done", "id": idea.id})

    assert (await desk.idea(idea.id)).state == "new"  # type: ignore[union-attr]


@pytest.mark.unit
async def test_there_is_nothing_to_undo_before_anything_has_been_done(
    desk: Store, a_project: None
) -> None:
    await inbox.capture(desk, "cache the probe results", project_key=KEY)

    html = await routes.render_ideas()

    assert "undo" not in html
    # And pressing it anyway is not a crash.
    status, _ = await _post("/ideas/undo", {})
    assert status == 200


@pytest.mark.unit
async def test_undoing_twice_does_not_walk_an_idea_backwards(desk: Store, a_project: None) -> None:
    """The slot holds the last thing done, not a history. Once it has been used it is empty, so a
    second press cannot move the idea again."""
    idea = await inbox.capture(desk, "cache the probe results", project_key=KEY)
    await _post(f"/ideas/{idea.id}/keep", {"from": "column"})
    await _post(f"/ideas/{idea.id}/drop", {"from": "column"})

    await _post("/ideas/undo", {})
    await _post("/ideas/undo", {})

    assert (await desk.idea(idea.id)).state == "kept"  # type: ignore[union-attr]
