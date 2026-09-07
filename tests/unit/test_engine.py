"""Running a drawing: one step at a time, in the order the lines describe.

The guarantees here are what make an engine safe to have in this program at all, and every one of
them is a thing that would be invisible if it broke: it queues rather than starts, it stops rather
than skipping, it waits rather than guessing.
"""

from __future__ import annotations

import ast
import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk import process
from agent_desk.store.repo import Store
from agent_desk.web import engine

KEY = "origin:acme/api"
ENGINE = pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "engine.py"


@pytest.fixture
async def desk(tmp_path: pathlib.Path) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    yield store
    await store.close()


async def _drawing(desk: Store, tmp_path: pathlib.Path) -> list[str]:
    """Two Actions, one after the other."""
    await desk.set_card_role("idea:one", "action")
    await desk.set_card_field("idea:one", "do", "read the logs")
    await desk.set_card_role("idea:two", "action")
    await desk.set_card_field("idea:two", "do", "write it up")
    await desk.tie_cards(from_name="idea:one", to_name="idea:two", kind="then")
    return ["idea:two", "idea:one"]


@pytest.mark.unit
def test_the_engine_never_starts_an_agent_itself() -> None:
    """The one guarantee everything else rests on.

    The console already knows how to start work carefully: a project has to be armed, one agent at
    a time, an hour's budget, two failures switch it off. An engine calling `dispatch.start`
    itself would be outside every one of those, and the first anybody would know is a drawing with
    nine steps starting nine agents at three in the morning.

    Asserted against the syntax tree, because the whole module is *about* dispatching and the word
    appears in its prose several times over.
    """
    tree = ast.parse(ENGINE.read_text(encoding="utf-8"))
    called = {
        f"{node.func.value.id}.{node.func.attr}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
    }

    assert "dispatch.start" not in called, (
        "the engine starts agents itself, outside the arming switch, the seat rule and the "
        "hour's budget"
    )
    assert "store.queue_task" in called, "it does not queue either, so it does nothing"


@pytest.mark.unit
async def test_a_run_queues_its_first_step_and_only_its_first(
    desk: Store, tmp_path: pathlib.Path
) -> None:
    """Sequencing is the whole point. A tick that raced ahead through four steps because three
    were quick would be a tick that ignored the order it was given."""
    names = await _drawing(desk, tmp_path)
    run, why = await engine.begin(desk, names=names, repo_key=KEY, cwd=str(tmp_path))
    assert run is not None and why == ""

    await engine.tick(desk)

    tasks = await desk.tasks()
    assert len(tasks) == 1
    assert tasks[0].title == "idea:one" or "read the logs" in tasks[0].instruction
    assert tasks[0].source_kind == "step"
    assert tasks[0].source_ref == f"{run.id}|idea:one"


@pytest.mark.unit
async def test_the_order_comes_from_the_lines_and_not_from_the_bench(
    desk: Store, tmp_path: pathlib.Path
) -> None:
    """ "Порядок берётся из связей, а не из того, в каком порядке карточки положили на верстак."
    The cards are handed over with the second one first, on purpose."""
    names = await _drawing(desk, tmp_path)
    assert names[0] == "idea:two"

    run, _ = await engine.begin(desk, names=names, repo_key=KEY, cwd=str(tmp_path))
    assert run is not None
    await engine.tick(desk)

    (task,) = await desk.tasks()
    assert "read the logs" in task.instruction, "it started with the second step"


@pytest.mark.unit
async def test_the_next_step_is_told_what_the_last_one_produced(
    desk: Store, tmp_path: pathlib.Path
) -> None:
    """ "Result одного шага должен быть входом для следующего." This is the whole feature, and it
    is invisible when it breaks: the second step simply runs without knowing anything."""
    names = await _drawing(desk, tmp_path)
    run, _ = await engine.begin(desk, names=names, repo_key=KEY, cwd=str(tmp_path))
    assert run is not None
    await engine.tick(desk)

    (first,) = await desk.tasks()
    await desk.take_next_task(KEY)
    await desk.finish_task(first.id)
    await desk.task_landed(first.id, "found six dead sessions", landed=True)
    await engine.tick(desk)  # settles the first
    await engine.tick(desk)  # queues the second

    second = next(one for one in await desk.tasks() if one.id != first.id)
    assert "found six dead sessions" in second.instruction
    assert "what it produced" in second.instruction, (
        "what a step made is not told apart from what it was asked to do"
    )


@pytest.mark.unit
async def test_a_step_that_fails_stops_the_run_rather_than_skipping_it(
    desk: Store, tmp_path: pathlib.Path
) -> None:
    """The steps after it were described on the assumption that it worked. Running them anyway is
    how a process produces confident wrong output."""
    names = await _drawing(desk, tmp_path)
    run, _ = await engine.begin(desk, names=names, repo_key=KEY, cwd=str(tmp_path))
    assert run is not None
    await engine.tick(desk)

    (first,) = await desk.tasks()
    await desk.take_next_task(KEY)
    await desk.task_failed(first.id, "no such directory")
    await engine.tick(desk)
    await engine.tick(desk)

    assert len(await desk.tasks()) == 1, "it queued the next step over a failed one"
    (stopped,) = await desk.runs()
    assert not stopped.going
    assert "no such directory" in (stopped.stopped_why or "")


@pytest.mark.unit
async def test_a_read_only_step_is_asked_rather_than_given_an_agent(
    desk: Store, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The `read` permission enforced rather than described: no worktree and no agent at all."""

    async def answered(prompt: str) -> tuple[str, str]:
        return ("the logs say six sessions died", "")

    monkeypatch.setattr(engine, "_ask", answered)
    await desk.set_card_role("idea:one", "action")
    await desk.set_card_field("idea:one", "do", "read the logs")
    await desk.set_card_leave("idea:one", ["read"])

    run, _ = await engine.begin(desk, names=["idea:one"], repo_key=KEY, cwd=str(tmp_path))
    assert run is not None
    await engine.tick(desk)

    assert await desk.tasks() == [], "a read-only step started an agent"
    assert (await desk.cards_made())["idea:one"] == "the logs say six sessions died"


@pytest.mark.unit
async def test_an_event_waits_and_waiting_is_not_failing(
    desk: Store, tmp_path: pathlib.Path
) -> None:
    """A run waiting on Tuesday's release is a run that is fine, and a console showing it in red
    would have somebody looking for a fault."""
    await desk.set_card_role("idea:one", "event")
    await desk.set_card_field("idea:one", "awaits", "the release goes out")
    await desk.set_card_role("idea:two", "action")
    await desk.set_card_field("idea:two", "do", "write it up")
    await desk.tie_cards(from_name="idea:one", to_name="idea:two", kind="when")

    run, why = await engine.begin(
        desk, names=["idea:one", "idea:two"], repo_key=KEY, cwd=str(tmp_path)
    )
    assert run is not None, why
    await engine.tick(desk)
    await engine.tick(desk)

    (step,) = [one for one in await desk.run_steps(run.id) if one.name == "idea:one"]
    assert step.state == "held"
    assert step.detail == "the release goes out"
    assert await desk.tasks() == [], "it ran past an event that has not happened"
    assert (await desk.runs())[0].going, "waiting was treated as the run ending"


@pytest.mark.unit
async def test_somebody_saying_it_happened_lets_the_run_go_on(
    desk: Store, tmp_path: pathlib.Path
) -> None:
    """A human act, and it has to be: whether the release went out is not something this console
    can read, and guessing would start the rest of a process on the strength of nothing."""
    await desk.set_card_role("idea:one", "event")
    await desk.set_card_field("idea:one", "awaits", "the release goes out")
    await desk.set_card_role("idea:two", "action")
    await desk.set_card_field("idea:two", "do", "write it up")
    await desk.tie_cards(from_name="idea:one", to_name="idea:two", kind="when")
    run, _ = await engine.begin(
        desk, names=["idea:one", "idea:two"], repo_key=KEY, cwd=str(tmp_path)
    )
    assert run is not None
    await engine.tick(desk)

    await engine.it_happened(desk, run.id, "idea:one")
    await engine.tick(desk)

    assert len(await desk.tasks()) == 1


@pytest.mark.unit
def test_a_decision_that_did_not_decide_holds_rather_than_picking_a_way() -> None:
    """The failure this refuses: a process going the first way out because the model said
    something conversational."""
    assert engine.read_branch("2", 3) == 2
    assert engine.read_branch("2.", 3) == 2
    assert engine.read_branch("", 3) == 0
    assert engine.read_branch("I think probably the second one", 3) == 0
    assert engine.read_branch("4", 3) == 0, "it took a way that is not there"
    assert engine.read_branch("0", 3) == 0


@pytest.mark.unit
async def test_a_decision_is_asked_and_never_given_an_agent(
    desk: Store, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A decision does not write anything, so there is nothing for an agent to do."""
    asked = []

    async def answered(prompt: str) -> tuple[str, str]:
        asked.append(prompt)
        return ("2", "")

    monkeypatch.setattr(engine, "_ask", answered)
    await desk.set_card_role("idea:one", "decision")
    await desk.set_card_field("idea:one", "ask", "did the gate pass")
    await desk.set_card_role("idea:two", "action")
    await desk.set_card_field("idea:two", "do", "merge it")
    await desk.set_card_role("idea:three", "action")
    await desk.set_card_field("idea:three", "do", "fix it")
    await desk.tie_cards(from_name="idea:one", to_name="idea:two", kind="if", says="it passed")
    await desk.tie_cards(from_name="idea:one", to_name="idea:three", kind="if", says="it did not")

    run, why = await engine.begin(
        desk, names=["idea:one", "idea:two", "idea:three"], repo_key=KEY, cwd=str(tmp_path)
    )
    assert run is not None, why
    await engine.tick(desk)

    assert await desk.tasks() == [], "a decision was given an agent"
    assert "did the gate pass" in asked[0]
    assert "1. it passed" in asked[0] and "2. it did not" in asked[0]
    assert "it did not" in (await desk.cards_made())["idea:one"]


@pytest.mark.unit
async def test_a_decision_with_no_ways_out_holds_and_does_not_fail(
    desk: Store, tmp_path: pathlib.Path
) -> None:
    """Somebody is still drawing. The run cannot go past it, and that is not a fault."""
    await desk.set_card_role("idea:one", "decision")
    await desk.set_card_field("idea:one", "ask", "did the gate pass")

    run, _ = await engine.begin(desk, names=["idea:one"], repo_key=KEY, cwd=str(tmp_path))
    assert run is not None
    await engine.tick(desk)

    (step,) = await desk.run_steps(run.id)
    assert step.state == "held"
    assert (await desk.runs())[0].going


@pytest.mark.unit
async def test_a_drawing_that_cannot_run_is_refused_with_the_reason_the_panel_shows(
    desk: Store, tmp_path: pathlib.Path
) -> None:
    """One function behind both, so a button that is offered and a run that is refused cannot
    disagree about why — the same argument as autostart.why_not."""
    await desk.set_card_role("idea:one", "action")  # nothing said about what to do

    run, why = await engine.begin(desk, names=["idea:one"], repo_key=KEY, cwd=str(tmp_path))

    assert run is None
    assert why == process.ready_to_run(
        await engine.bench_of(desk, ["idea:one"]), await engine.lines_of(desk, ["idea:one"])
    )
    assert await desk.runs() == []


@pytest.mark.unit
async def test_a_drawing_with_nowhere_to_run_is_refused_rather_than_given_a_project(
    desk: Store, tmp_path: pathlib.Path
) -> None:
    await desk.set_card_role("idea:one", "action")
    await desk.set_card_field("idea:one", "do", "go")

    run, why = await engine.begin(desk, names=["idea:one"], repo_key="", cwd="")

    assert run is None
    assert "nowhere to run" in why


@pytest.mark.unit
async def test_the_cards_of_a_run_do_not_change_under_it(
    desk: Store, tmp_path: pathlib.Path
) -> None:
    """What is on a workbench is a fact about a browser and it changes while a run is going. A run
    that re-read it would change what it is doing because somebody dragged a card off in another
    tab."""
    names = await _drawing(desk, tmp_path)
    run, _ = await engine.begin(desk, names=names, repo_key=KEY, cwd=str(tmp_path))
    assert run is not None

    # A third card appears on the bench. The run has never heard of it.
    await desk.set_card_role("idea:three", "action")
    await desk.set_card_field("idea:three", "do", "something else entirely")
    await engine.tick(desk)

    assert "idea:three" not in (await desk.runs())[0].cards
    (task,) = await desk.tasks()
    assert "something else entirely" not in task.instruction


@pytest.mark.unit
async def test_a_briefing_leads_with_what_to_do_and_not_with_what_came_before(
    desk: Store, tmp_path: pathlib.Path
) -> None:
    """A briefing opening with three paragraphs of what other steps produced, reaching the
    instruction last, is one an agent skims."""
    cards = [
        process.Card(name="a:1", role="action", label="one", said={"do": "read"}, made="the logs"),
        process.Card(name="a:2", role="action", label="two", said={"do": "write it up"}),
    ]
    lines = [process.Line(from_name="a:1", to_name="a:2", kind="then")]

    said = engine.briefing("a:2", cards, lines)

    assert said.index("write it up") < said.index("the logs")


@pytest.mark.unit
def test_a_step_is_told_the_permissions_it_does_not_have() -> None:
    """An agent that knows it may not push will not spend a turn trying — and a briefing that
    silently differs from what the console allows is how an agent reports work it was not
    permitted to keep."""
    said = " ".join(engine._permission_words(("work",)))

    assert "Do not push" in said
    assert "not being offered to the gate" in said
    assert "rather than fetching" in said

    given = " ".join(engine._permission_words(("work", "land", "push", "net")))
    assert "Do not push" not in given


@pytest.mark.unit
def test_the_run_is_drawn_on_the_drawing() -> None:
    """ "Ход исполнения виден на самой схеме: где сейчас, что прошло, что упало." On the cards
    themselves rather than only in a list: the drawing is the thing somebody made, and a second
    representation of it beside the first is two things to keep in your head."""
    static = pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "static"
    console = (static / "console.js").read_text(encoding="utf-8")
    css = (static / "console.css").read_text(encoding="utf-8")

    assert "function showRuns(" in console
    assert "const STEP_MARK" in console
    for state in ("waiting", "going", "held", "done", "failed"):
        assert state in console[console.index("const STEP_MARK") :][:200], (
            f"a step in state {state} has no mark, so it draws as nothing"
        )
    assert (
        'data-step="held"' in css
        and "--attention"
        in css[css.index('data-step="held"') : css.index('data-step="held"') + 120]
    ), "a held step is drawn in red, so a run waiting on Tuesday's release looks like a fault"
    assert ".pin.at-now" in css, "there is no mark for where the run is now"


@pytest.mark.unit
async def test_the_engine_loop_lets_a_cancel_through(desk: Store) -> None:
    """The same failure that hung the console twice before: a loop that swallows CancelledError is
    a console that will not close, because `app.lifespan` cancels it and then waits for it."""
    import asyncio

    task = asyncio.create_task(engine.run(desk))
    await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.unit
def test_the_engine_is_held_open_and_cancelled_with_the_others() -> None:
    """A run that outlived the console would be a daemon, and this program does not have one."""
    app = (pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "app.py").read_text(
        encoding="utf-8"
    )

    assert "engine.run(routes.store)" in app
    assert "walking.cancel()" in app


@pytest.mark.unit
async def test_a_run_whose_last_step_is_done_ends(desk: Store, tmp_path: pathlib.Path) -> None:
    """And ends without a reason, which is how "it finished" is told apart from "it gave up"."""
    await desk.set_card_role("idea:one", "action")
    await desk.set_card_field("idea:one", "do", "the only thing")
    run, _ = await engine.begin(desk, names=["idea:one"], repo_key=KEY, cwd=str(tmp_path))
    assert run is not None
    await engine.tick(desk)

    (task,) = await desk.tasks()
    await desk.take_next_task(KEY)
    await desk.finish_task(task.id)
    await engine.tick(desk)  # settles it
    await engine.tick(desk)  # nothing left, so the run ends

    (ended,) = await desk.runs()
    assert not ended.going
    assert ended.stopped_why is None, "a run that finished says it gave up"
    assert ended.finished_at


@pytest.mark.unit
async def test_a_step_allowed_to_land_is_offered_to_the_gate(
    desk: Store, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The `land` and `push` permissions enforced rather than described: this console calls the
    landing and tells it whether to push, or does neither."""
    from agent_desk import land

    offered: list[tuple[str, bool]] = []

    def landing(cwd: str, worktree: str, *, push: bool = True) -> land.Landed:
        offered.append((worktree, push))
        return land.Landed(landed=True, detail="merged", branch="b")

    monkeypatch.setattr(engine.land, "land", landing)
    await desk.set_card_role("idea:one", "action")
    await desk.set_card_field("idea:one", "do", "the work")
    await desk.set_card_leave("idea:one", ["work", "land"])
    run, _ = await engine.begin(desk, names=["idea:one"], repo_key=KEY, cwd=str(tmp_path))
    assert run is not None
    await engine.tick(desk)

    (task,) = await desk.tasks()
    await desk.take_next_task(KEY)
    await desk.finish_task(task.id)
    await engine.tick(desk)

    assert len(offered) == 1
    assert offered[0][1] is False, "it pushed without being allowed to"
    assert (await desk.cards_made())["idea:one"] == "merged"


@pytest.mark.unit
async def test_a_step_not_allowed_to_land_is_not_offered_to_the_gate(
    desk: Store, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def never(*args: object, **kwargs: object) -> object:  # pragma: no cover
        raise AssertionError("a branch was merged by a step that was not allowed to")

    monkeypatch.setattr(engine.land, "land", never)
    await desk.set_card_role("idea:one", "action")
    await desk.set_card_field("idea:one", "do", "the work")
    run, _ = await engine.begin(desk, names=["idea:one"], repo_key=KEY, cwd=str(tmp_path))
    assert run is not None
    await engine.tick(desk)
    (task,) = await desk.tasks()
    await desk.take_next_task(KEY)
    await desk.finish_task(task.id)

    await engine.tick(desk)

    assert (await desk.run_steps(run.id))[0].state == "done"


@pytest.mark.unit
async def test_a_gate_that_says_no_stops_the_run(
    desk: Store, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing lands that the project's own gate will not take (docs/adr/0008), and the steps
    after this one assumed it had."""
    from agent_desk import land

    monkeypatch.setattr(
        engine.land,
        "land",
        lambda cwd, worktree, *, push=True: land.Landed(landed=False, detail="the gate said no"),
    )
    await desk.set_card_role("idea:one", "action")
    await desk.set_card_field("idea:one", "do", "the work")
    await desk.set_card_leave("idea:one", ["work", "land"])
    run, _ = await engine.begin(desk, names=["idea:one"], repo_key=KEY, cwd=str(tmp_path))
    assert run is not None
    await engine.tick(desk)
    (task,) = await desk.tasks()
    await desk.take_next_task(KEY)
    await desk.finish_task(task.id)

    await engine.tick(desk)

    (ended,) = await desk.runs()
    assert not ended.going
    assert "the gate said no" in (ended.stopped_why or "")


@pytest.mark.unit
async def test_a_step_that_could_not_be_asked_stops_the_run(
    desk: Store, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A model that is out of budget is a run that stops and says so, not a loop that retries the
    same wall every twenty seconds."""

    async def refused(prompt: str) -> tuple[str, str]:
        return ("", "the account is out of budget")

    monkeypatch.setattr(engine, "_ask", refused)
    await desk.set_card_role("idea:one", "action")
    await desk.set_card_field("idea:one", "do", "read it")
    await desk.set_card_leave("idea:one", ["read"])
    run, _ = await engine.begin(desk, names=["idea:one"], repo_key=KEY, cwd=str(tmp_path))
    assert run is not None

    await engine.tick(desk)

    (ended,) = await desk.runs()
    assert not ended.going
    assert "out of budget" in (ended.stopped_why or "")


@pytest.mark.unit
async def test_a_decision_that_would_not_decide_holds_the_run(
    desk: Store, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def waffled(prompt: str) -> tuple[str, str]:
        return ("it depends really", "")

    monkeypatch.setattr(engine, "_ask", waffled)
    await desk.set_card_role("idea:one", "decision")
    await desk.set_card_field("idea:one", "ask", "did it pass")
    await desk.set_card_role("idea:two", "action")
    await desk.set_card_field("idea:two", "do", "merge")
    await desk.tie_cards(from_name="idea:one", to_name="idea:two", kind="if", says="it passed")
    run, _ = await engine.begin(
        desk, names=["idea:one", "idea:two"], repo_key=KEY, cwd=str(tmp_path)
    )
    assert run is not None

    await engine.tick(desk)

    (step,) = [one for one in await desk.run_steps(run.id) if one.name == "idea:one"]
    assert step.state == "held"
    assert await desk.tasks() == [], "it went a way the decision did not choose"
    assert (await desk.runs())[0].going


@pytest.mark.unit
async def test_a_step_whose_task_has_been_taken_out_of_the_queue_stops_the_run(
    desk: Store, tmp_path: pathlib.Path
) -> None:
    """Somebody dropped it from the project's queue. The run cannot wait for a thing that is not
    there, and it must not silently start it again."""
    await desk.set_card_role("idea:one", "action")
    await desk.set_card_field("idea:one", "do", "the work")
    run, _ = await engine.begin(desk, names=["idea:one"], repo_key=KEY, cwd=str(tmp_path))
    assert run is not None
    await engine.tick(desk)
    (task,) = await desk.tasks()
    await desk.drop_task(task.id)

    await engine.tick(desk)

    (ended,) = await desk.runs()
    assert not ended.going
    assert "gone" in (ended.stopped_why or "")


@pytest.mark.unit
async def test_a_decision_is_told_what_is_already_known_about_it(
    desk: Store, tmp_path: pathlib.Path
) -> None:
    """A decision reached twice in one drawing should not answer the second time as if the first
    had not happened."""
    card = process.Card(
        name="d:1",
        role="decision",
        label="did it pass",
        said={"ask": "did it pass"},
        made="the gate came back green",
    )
    ways = [process.Line(from_name="d:1", to_name="a:1", kind="if", says="it passed")]

    asked = engine.branch_prompt(card, ways)

    assert "the gate came back green" in asked
    assert "1. it passed" in asked


@pytest.mark.unit
async def test_a_step_still_in_flight_is_left_alone(desk: Store, tmp_path: pathlib.Path) -> None:
    """The tick that finds a task still running must do nothing at all — not queue the next step,
    not re-queue this one."""
    await desk.set_card_role("idea:one", "action")
    await desk.set_card_field("idea:one", "do", "the work")
    run, _ = await engine.begin(desk, names=["idea:one"], repo_key=KEY, cwd=str(tmp_path))
    assert run is not None
    await engine.tick(desk)
    await desk.take_next_task(KEY)

    assert await engine.tick(desk) == 0
    assert len(await desk.tasks()) == 1
    assert (await desk.runs())[0].going


@pytest.mark.unit
async def test_a_run_that_cannot_be_advanced_is_stopped_rather_than_retried_for_ever(
    desk: Store, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A loop logging the same exception every twenty seconds until somebody notices is the
    failure — and the run itself is the thing that has to say what happened."""

    async def broken(store: Store, run: object) -> int:
        raise RuntimeError("the drawing makes no sense")

    await desk.set_card_role("idea:one", "action")
    await desk.set_card_field("idea:one", "do", "the work")
    run, _ = await engine.begin(desk, names=["idea:one"], repo_key=KEY, cwd=str(tmp_path))
    assert run is not None
    monkeypatch.setattr(engine, "_one", broken)

    await engine.tick(desk)

    (ended,) = await desk.runs()
    assert not ended.going
    assert "something went wrong" in (ended.stopped_why or "")
    # And the next tick does not find it again.
    assert await engine.tick(desk) == 0


@pytest.mark.unit
async def test_a_decision_that_could_not_be_asked_stops_the_run(
    desk: Store, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def refused(prompt: str) -> tuple[str, str]:
        return ("", "no answer engine is configured")

    monkeypatch.setattr(engine, "_ask", refused)
    await desk.set_card_role("idea:one", "decision")
    await desk.set_card_field("idea:one", "ask", "did it pass")
    await desk.set_card_role("idea:two", "action")
    await desk.set_card_field("idea:two", "do", "merge")
    await desk.tie_cards(from_name="idea:one", to_name="idea:two", kind="if", says="it passed")
    run, _ = await engine.begin(
        desk, names=["idea:one", "idea:two"], repo_key=KEY, cwd=str(tmp_path)
    )
    assert run is not None

    await engine.tick(desk)

    (ended,) = await desk.runs()
    assert not ended.going
    assert "no answer engine" in (ended.stopped_why or "")


@pytest.mark.unit
async def test_asking_never_raises_however_the_answer_engine_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A step that could not be asked is a step that failed, and the run says so — rather than the
    loop falling over and taking every other run with it."""

    async def blows_up(prompt: str, *, add_dirs: object = ()) -> object:
        raise OSError("no such binary")
        yield ""  # pragma: no cover - unreachable, but this has to be a generator

    monkeypatch.setattr(engine, "stream_answer", blows_up)

    said, gone = await engine._ask("anything")

    assert said == ""
    assert "no such binary" in gone


@pytest.mark.unit
def test_a_briefing_for_a_card_that_is_not_there_is_empty(desk: Store) -> None:
    """Rather than an exception halfway through building one, which would stop a run for a reason
    that has nothing to do with the drawing."""
    assert engine.briefing("nothing:here", [], []) == ""
