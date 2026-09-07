"""A run that is neither going nor over (01M1XC4Z1T2A… and 01M1XC4Z1M3F…).

"Сегодня прогон либо идёт, либо остановлен насовсем. Между ними нет «пока не надо» — а именно оно
нужно, когда упёрлись в лимит или ждут человека."

"Движок останавливает прогон на упавшем шаге и это правильно… Но дальше нет ничего: единственный
способ продолжить — запустить всё заново с первого шага. Прогон, который умеет только начинаться
сначала, — это прогон, который запускают один раз."

Two ideas and one missing thing. Every reason a run stops is one of two kinds — it is over, or it
is *not now* — and recording the second as the first is what made starting from the top the only
way forward.
"""

from __future__ import annotations

import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk.store.repo import Store

CONSOLE = (
    pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "static" / "console.js"
)


@pytest.fixture
async def desk(tmp_path: pathlib.Path) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    yield store
    await store.close()


async def _run(store: Store) -> str:
    run = await store.start_run(cards=["step:1", "step:2"], repo_key="k", cwd="/tmp")
    return run.id


async def _one(store: Store, run_id: str):  # type: ignore[no-untyped-def]
    return next(one for one in await store.runs() if one.id == run_id)


# --- not now -------------------------------------------------------------------------------------
@pytest.mark.unit
async def test_a_run_can_be_set_aside_and_picked_up(desk: Store) -> None:
    run_id = await _run(desk)
    await desk.set_run_step(run_id=run_id, name="step:1", state="done", made="did it")

    await desk.pause_run(run_id)
    paused = await _one(desk, run_id)
    assert paused.going is False
    assert paused.waiting is True, "set aside reads as finished"

    await desk.carry_on_run(run_id)
    assert (await _one(desk, run_id)).going is True


@pytest.mark.unit
async def test_setting_aside_keeps_every_step_it_has_done(desk: Store) -> None:
    """It picks up where it stopped. A pause that lost the steps would be a stop with a friendlier
    word on it, and doing the first three again is how a rerun becomes a second deploy."""
    run_id = await _run(desk)
    await desk.set_run_step(run_id=run_id, name="step:1", state="done", made="did it")

    await desk.pause_run(run_id)
    await desk.carry_on_run(run_id)

    assert [(one.name, one.state) for one in await desk.run_steps(run_id)] == [("step:1", "done")]


@pytest.mark.unit
async def test_a_run_that_reached_its_end_stays_ended(desk: Store) -> None:
    """Over is over. Starting it again is running the drawing, which is a different button and
    makes new cards."""
    run_id = await _run(desk)
    await desk.end_run(run_id)

    await desk.pause_run(run_id)
    await desk.carry_on_run(run_id)

    over = await _one(desk, run_id)
    assert over.finished_at is not None
    assert over.going is False and over.waiting is False


# --- and carrying on from a step that failed -----------------------------------------------------
@pytest.mark.unit
async def test_a_failed_step_can_be_fixed_and_the_run_carries_on(desk: Store) -> None:
    run_id = await _run(desk)
    await desk.set_run_step(run_id=run_id, name="step:1", state="failed", detail="it broke")
    await desk.end_run(run_id, why="step:1: it broke")

    stopped = await _one(desk, run_id)
    assert stopped.going is False and stopped.stopped_why

    await desk.carry_on_run(run_id)

    going = await _one(desk, run_id)
    assert going.going is True
    assert going.stopped_why is None, "it still carries the reason it stopped for"
    assert [(one.name, one.state) for one in await desk.run_steps(run_id)] == [
        ("step:1", "waiting")
    ], "the failed step is not back in the queue"


@pytest.mark.unit
async def test_only_the_failed_step_goes_back(desk: Store) -> None:
    """The ones before it are done, and doing them twice is how a rerun becomes a second deploy.
    The ones after it never ran."""
    run_id = await _run(desk)
    await desk.set_run_step(run_id=run_id, name="step:1", state="done", made="deployed it")
    await desk.set_run_step(run_id=run_id, name="step:2", state="failed", detail="it broke")
    await desk.end_run(run_id, why="step:2: it broke")

    await desk.carry_on_run(run_id)

    assert {one.name: one.state for one in await desk.run_steps(run_id)} == {
        "step:1": "done",
        "step:2": "waiting",
    }


@pytest.mark.unit
async def test_the_failed_step_loses_the_words_that_were_about_the_failure(desk: Store) -> None:
    """`detail` said why it stopped. Left behind, a step that is waiting to be tried again reads
    as one that has already gone wrong."""
    run_id = await _run(desk)
    await desk.set_run_step(run_id=run_id, name="step:1", state="failed", detail="it broke")
    await desk.end_run(run_id, why="step:1: it broke")

    await desk.carry_on_run(run_id)

    assert (await desk.run_steps(run_id))[0].detail == ""


# --- what the page is told -----------------------------------------------------------------------
@pytest.mark.unit
def test_the_bar_says_which_of_the_three_it_is() -> None:
    """Working, waiting for somebody, or stopped and holding its place. They are read differently
    and only one of them was ever shown."""
    console = CONSOLE.read_text(encoding="utf-8")

    bar = console[console.index("function showRunBar(") :]
    bar = bar[: bar.index("\n}\n")]

    assert "set aside — it kept its place" in bar
    assert "stopped at" in bar
    assert "waiting:" in bar


@pytest.mark.unit
def test_the_buttons_appear_for_the_states_they_belong_to() -> None:
    """ "Not now" on a run that has already stopped is a button that does nothing, and "carry on"
    on a run that is going is a button that means nothing."""
    console = CONSOLE.read_text(encoding="utf-8")

    bar = console[console.index("function showRunBar(") :]
    bar = bar[: bar.index("\n}\n")]

    assert "['[data-pause]', going.going]" in bar
    assert "['[data-carry-on]', going.canCarryOn]" in bar


@pytest.mark.unit
async def test_the_run_says_whether_it_can_carry_on(desk: Store) -> None:
    """The page cannot work it out from `going` alone: a run that is over and a run that stopped
    at a step both say going is false."""
    import json

    from agent_desk.web import routes

    old_store, routes.store = routes.store, desk
    try:
        run_id = await _run(desk)
        await desk.end_run(run_id, why="step:1: it broke")
        stopped = json.loads((await routes.workbench_runs()).body)["runs"][0]

        await desk.carry_on_run(run_id)
        await desk.end_run(run_id)
        over = json.loads((await routes.workbench_runs()).body)["runs"][0]
    finally:
        routes.store = old_store

    assert stopped["canCarryOn"] is True and stopped["going"] is False
    assert over["canCarryOn"] is False and over["going"] is False
