"""An Event the console answers itself (01M1XED1CGNH52K6DVGX3MRH1B).

"Сегодня Event ждёт, пока человек скажет «случилось». Но консоль уже сама знает кучу фактов: гейт
позеленел… ни одна сессия не занята, наступило время. Достаточно дать Event условие из того же
списка, что у отложенных задач… Это переход от «схема, которую я запускаю» к «схема, которая
живёт»."
"""

from __future__ import annotations

import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk import process
from agent_desk.ideas import waking
from agent_desk.store.repo import Store
from agent_desk.web import engine

pytestmark = pytest.mark.unit

ENGINE = pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "engine.py"


@pytest.fixture
async def desk(tmp_path: pathlib.Path) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    yield store
    await store.close()


def _an_event(awaits: str) -> process.Card:
    return process.Card(name="step:wait", role="event", label="wait", said={"awaits": awaits})


async def test_a_condition_this_console_can_check_answers_itself(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ "Схема, которая живёт" rather than one somebody runs."""
    monkeypatch.setattr(engine.later, "anything_running", _says(False))
    monkeypatch.setattr(engine.later, "gate_is_green", _says(True))
    run = await desk.start_run(cards="step:wait", repo_key="k", cwd="/tmp")

    await engine._wait_for(desk, run, _an_event("once the gate is green"), None)

    (step,) = await desk.run_steps(run.id)
    assert step.state == "done"
    assert "it came true" in step.made


async def test_a_condition_that_is_not_true_yet_holds(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Held, not failed: a run waiting on Tuesday's release is a run that is fine."""
    monkeypatch.setattr(engine.later, "anything_running", _says(False))
    monkeypatch.setattr(engine.later, "gate_is_green", _says(False))
    run = await desk.start_run(cards="step:wait", repo_key="k", cwd="/tmp")

    await engine._wait_for(desk, run, _an_event("once the gate is green"), None)

    (step,) = await desk.run_steps(run.id)
    assert step.state == "held"
    assert "waiting for it to be true" in step.detail


async def test_it_is_asked_again_on_every_tick(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A condition is a fact about the world, and the world is what changes while a run is held."""
    monkeypatch.setattr(engine.later, "anything_running", _says(False))
    monkeypatch.setattr(engine.later, "gate_is_green", _says(False))
    run = await desk.start_run(cards="step:wait", repo_key="k", cwd="/tmp")
    await engine._wait_for(desk, run, _an_event("once the gate is green"), None)
    (held,) = await desk.run_steps(run.id)

    monkeypatch.setattr(engine.later, "gate_is_green", _says(True))
    await engine._wait_for(desk, run, _an_event("once the gate is green"), held)

    (step,) = await desk.run_steps(run.id)
    assert step.state == "done"


async def test_free_text_still_waits_for_a_person(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Free text is not a condition and never becomes one by being guessed at: "когда всё
    устаканится" would otherwise be a moment that never arrives or one that arrives at random."""
    monkeypatch.setattr(engine.later, "anything_running", _says(False))
    monkeypatch.setattr(engine.later, "gate_is_green", _says(True))
    run = await desk.start_run(cards="step:wait", repo_key="k", cwd="/tmp")

    await engine._wait_for(desk, run, _an_event("когда всё устаканится"), None)

    (step,) = await desk.run_steps(run.id)
    assert step.state == "held"
    assert step.detail == "когда всё устаканится"


async def test_an_event_that_says_nothing_still_waits_for_a_person(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(engine.later, "anything_running", _says(False))
    monkeypatch.setattr(engine.later, "gate_is_green", _says(True))
    run = await desk.start_run(cards="step:wait", repo_key="k", cwd="/tmp")

    await engine._wait_for(desk, run, _an_event(""), None)

    (step,) = await desk.run_steps(run.id)
    assert step.state == "held"


def test_the_vocabulary_is_the_one_deferred_thoughts_already_use() -> None:
    """A second list of conditions would be a second thing to keep in step, and the day they
    differ is the day a card waits for something nothing can answer."""
    source = ENGINE.read_text(encoding="utf-8")

    assert "waking.read(" in source and "waking.has_come(" in source
    assert set(waking.CONDITIONS) == {"free", "gate"}


def _says(what: bool):  # type: ignore[no-untyped-def]
    async def answer(*rest: object, **more: object) -> bool:
        return what

    return answer
