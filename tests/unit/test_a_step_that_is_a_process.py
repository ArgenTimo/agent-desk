"""A step whose work is another drawing (01M1XC4Z1Y8C…).

"Схема из тридцати шагов нечитаема. Нужен шаг, внутри которого лежит другая схема, и который
снаружи выглядит одной карточкой — иначе конструктор упирается в потолок примерно на десяти шагах,
а все интересные процессы длиннее."

**No sixth role.** adr/0011 closed the list at five and gave the reason. A step that runs another
drawing is still an Action — something to do — and what differs is what it does the work with, so
it is a field. Every part of the console that reasons about roles is unchanged.
"""

from __future__ import annotations

import pathlib
import tempfile
from collections.abc import AsyncIterator

import pytest
from agent_desk import process, roles
from agent_desk.store.repo import Store, TemplateStep
from agent_desk.web import engine


@pytest.fixture
async def desk() -> AsyncIterator[Store]:
    with tempfile.TemporaryDirectory() as where:
        store = Store(pathlib.Path(where) / "agent-desk.db")
        await store.open()
        yield store
        await store.close()


async def _a_saved_process(store: Store, name: str = "a release") -> None:
    await store.keep_template(
        name=name,
        steps=[
            TemplateStep(ord=1, role="action", label="run the tests", fields={"do": "run them"}),
            TemplateStep(ord=2, role="action", label="ship it", fields={"do": "ship"}),
        ],
        lines=[],
    )


def _card(name: str, runs: str = "") -> process.Card:
    return process.Card(
        name=name,
        role="action",
        label="the whole release",
        said={"do": "do the release", **({"runs": runs} if runs else {})},
    )


@pytest.mark.unit
def test_it_is_a_field_on_an_action_rather_than_a_sixth_role() -> None:
    """Five names with a meaning each is a language; six is a list (adr/0011)."""
    assert "runs" in [one.name for one in roles.fields_of("action")]
    assert len(roles.FIELDS) == 5
    assert process.STEPS == ("action", "decision", "event")


@pytest.mark.unit
async def test_a_step_that_names_a_process_starts_one_and_waits(desk: Store) -> None:
    await _a_saved_process(desk)
    outer = await desk.start_run(cards=["step:outer"], repo_key="k", cwd="/tmp")

    moved = await engine._do(desk, outer, _card("step:outer", "a release"), [], [])

    assert moved == 1
    (step,) = await desk.run_steps(outer.id)
    assert step.state == "going", "the outer step is not waiting for anything"
    assert step.task_id is None, "it queued an agent as well as a process"

    inner = await desk.run_inside(outer.id, "step:outer")
    assert inner is not None
    assert len(inner.names) == 2, "the drawing inside it was not made"


@pytest.mark.unit
async def test_the_inner_run_gets_its_own_cards(desk: Store) -> None:
    """The reason a template always makes new ones: a process run twice must not overwrite what
    the first time produced."""
    await _a_saved_process(desk)
    outer = await desk.start_run(cards=["step:outer"], repo_key="k", cwd="/tmp")

    await engine._do(desk, outer, _card("step:outer", "a release"), [], [])
    first = await desk.run_inside(outer.id, "step:outer")
    await engine._do(desk, outer, _card("step:outer", "a release"), [], [])
    second = await desk.run_inside(outer.id, "step:outer")

    assert first is not None and second is not None
    assert set(first.names).isdisjoint(second.names)


@pytest.mark.unit
async def test_the_step_finishes_when_the_process_inside_it_does(desk: Store) -> None:
    await _a_saved_process(desk)
    outer = await desk.start_run(cards=["step:outer"], repo_key="k", cwd="/tmp")
    await engine._do(desk, outer, _card("step:outer", "a release"), [], [])
    inner = await desk.run_inside(outer.id, "step:outer")
    assert inner is not None

    # Still going: the outer step waits.
    (step,) = await desk.run_steps(outer.id)
    assert await engine._settle(desk, outer, _card("step:outer", "a release"), step) == 0

    for name in inner.names:
        await desk.set_run_step(run_id=inner.id, name=name, state="done", made="did it")
    await desk.end_run(inner.id)

    (step,) = await desk.run_steps(outer.id)
    assert await engine._settle(desk, outer, _card("step:outer", "a release"), step) == 1
    (settled,) = await desk.run_steps(outer.id)
    assert settled.state == "done"
    assert "2 steps inside it" in settled.made


@pytest.mark.unit
async def test_a_process_that_stopped_stops_the_step_and_the_run(desk: Store) -> None:
    """The same sentence an ordinary failed step gets: the steps after it were described on the
    assumption that it worked."""
    await _a_saved_process(desk)
    outer = await desk.start_run(cards=["step:outer"], repo_key="k", cwd="/tmp")
    await engine._do(desk, outer, _card("step:outer", "a release"), [], [])
    inner = await desk.run_inside(outer.id, "step:outer")
    assert inner is not None
    await desk.end_run(inner.id, why="the gate said no")

    (step,) = await desk.run_steps(outer.id)
    await engine._settle(desk, outer, _card("step:outer", "a release"), step)

    (settled,) = await desk.run_steps(outer.id)
    assert settled.state == "failed"
    assert "the gate said no" in settled.detail
    assert not (await desk.run_inside(outer.id, "step:outer") or inner).going
    assert next(one for one in await desk.runs() if one.id == outer.id).going is False


@pytest.mark.unit
async def test_naming_a_process_that_is_not_there_stops_rather_than_guesses(desk: Store) -> None:
    """A step pointing at a drawing nobody saved is a step nobody can run, and picking a
    similarly-named one would be the guess the fifth rule forbids."""
    outer = await desk.start_run(cards=["step:outer"], repo_key="k", cwd="/tmp")

    await engine._do(desk, outer, _card("step:outer", "one that does not exist"), [], [])

    (step,) = await desk.run_steps(outer.id)
    assert step.state == "failed"
    assert "no saved process" in step.detail


@pytest.mark.unit
async def test_an_ordinary_action_is_untouched(desk: Store) -> None:
    """The field is absent on every step drawn before this and on most drawn after."""
    outer = await desk.start_run(cards=["step:outer"], repo_key="k", cwd="/tmp")

    await engine._do(desk, outer, _card("step:outer"), [], [])

    (step,) = await desk.run_steps(outer.id)
    assert step.task_id is not None, "an ordinary Action no longer queues an agent"
    assert await desk.run_inside(outer.id, "step:outer") is None


@pytest.mark.unit
async def test_the_drawing_inside_arrives_whole(desk: Store) -> None:
    """Its lines and its permissions, not only its steps. A nested process that lost the lines
    between its steps would run them in whatever order they were saved in, which is not the
    process anybody drew — and one that lost its permissions would run with the wrong ones.
    """
    from agent_desk.store.repo import TemplateLine

    await desk.keep_template(
        name="a release",
        steps=[
            TemplateStep(
                ord=1, role="action", label="run the tests", fields={"do": "run"}, leave=("read",)
            ),
            TemplateStep(ord=2, role="decision", label="did it pass?", fields={"ask": "pass?"}),
        ],
        lines=[TemplateLine(from_ord=1, to_ord=2, kind="then", says="then")],
    )
    outer = await desk.start_run(cards=["step:outer"], repo_key="k", cwd="/tmp")

    await engine._do(desk, outer, _card("step:outer", "a release"), [], [])

    inner = await desk.run_inside(outer.id, "step:outer")
    assert inner is not None
    drawn = [
        one
        for one in await desk.card_ties()
        if one.from_name in inner.names and one.to_name in inner.names
    ]
    assert len(drawn) == 1, "the steps inside it arrived unjoined"
    assert (await desk.card_leaves())[inner.names[0]] == ["read"]
