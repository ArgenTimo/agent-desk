"""What one step cost and how long it took (01M1XA1V9JVT7ZBKJ1YQW907DF).

"Токены, деньги, секунды. Для разработчика это половина смысла: промпт, который лучше на 3% и
дороже вдвое, — это плохой промпт, и увидеть это надо на схеме, а не в счёте в конце месяца."

043 counts what the console spends in a day and stops at a ceiling. That is a fuse, and a fuse
answers "may I ask another question" — it cannot answer "which of these two prompts is the
expensive one", because by the time the day's total is interesting the two are mixed into it.
"""

from __future__ import annotations

import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk.store.repo import Store
from agent_desk.web import engine

pytestmark = pytest.mark.unit

CONSOLE = (
    pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "static" / "console.js"
)


@pytest.fixture
async def desk(tmp_path: pathlib.Path) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    yield store
    await store.close()


# --- what is kept -----------------------------------------------------------------------------------
async def test_a_step_remembers_what_it_cost(desk: Store) -> None:
    run = await desk.start_run(cards=["step:a"], repo_key="", cwd="")

    await desk.set_run_step(run_id=run.id, name="step:a", state="done", usd=0.0123, ms=4200)

    (step,) = await desk.run_steps(run.id)
    assert step.usd == pytest.approx(0.0123)
    assert step.ms == 4200


async def test_a_later_write_does_not_erase_the_measurement(desk: Store) -> None:
    """A step is written several times as it goes — queued, then done — and a write with no
    measurement in it must not throw away the one that had it."""
    run = await desk.start_run(cards=["step:a"], repo_key="", cwd="")
    await desk.set_run_step(run_id=run.id, name="step:a", state="going", usd=0.05, ms=900)

    await desk.set_run_step(run_id=run.id, name="step:a", state="done", made="the answer")

    (step,) = await desk.run_steps(run.id)
    assert step.usd == pytest.approx(0.05)
    assert step.ms == 900


async def test_nothing_measured_is_zero_and_not_a_guess(desk: Store) -> None:
    """Every step run before this existed, and every step done by an agent: the CLI reports a cost
    for a headless answer and this console does not price an agent's work."""
    run = await desk.start_run(cards=["step:a"], repo_key="", cwd="")
    await desk.set_run_step(run_id=run.id, name="step:a", state="done")

    (step,) = await desk.run_steps(run.id)
    assert (step.usd, step.ms) == (0.0, 0)


# --- how it is measured ------------------------------------------------------------------------------
async def test_asking_reports_what_the_call_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    async def costs(prompt: str, **how: object) -> object:
        note = how.get("on_cost")
        if callable(note):
            note(0.04)
        yield "an answer"

    monkeypatch.setattr(engine, "stream_answer", costs)

    came = await engine._ask("anything")

    assert came.said == "an answer"
    assert came.usd == pytest.approx(0.04)
    assert came.ms >= 0


async def test_a_call_that_failed_still_says_how_long_it_took(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A prompt that takes forty seconds and then fails is a fact about the prompt."""

    async def breaks(prompt: str, **_how: object) -> object:
        raise OSError("gone")
        yield ""  # pragma: no cover - unreachable, and the signature needs it

    monkeypatch.setattr(engine, "stream_answer", breaks)

    came = await engine._ask("anything")

    assert came.gone
    assert came.ms >= 0


def test_a_fan_costs_what_both_calls_cost() -> None:
    """Two models asked is two calls, and a card that reported one of them would understate every
    comparison."""
    source = (
        pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "engine.py"
    ).read_text(encoding="utf-8")

    assert "spent, took = spent + came.usd, took + came.ms" in source


def test_a_decision_is_priced_too() -> None:
    """A harness that priced the answers and not the branching would understate every drawing with
    a fork in it."""
    source = (
        pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "engine.py"
    ).read_text(encoding="utf-8")
    start = source.index("async def _decide(")
    body = source[start : source.index("\n\n\nasync def", start)]

    assert "usd=came.usd, ms=came.ms" in body


# --- and where it is read ------------------------------------------------------------------------------
def test_it_is_on_the_card() -> None:
    source = "\n".join(
        line
        for line in CONSOLE.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("//")
    )

    assert "writeCost(pin, step, dearest)" in source
    assert "class = 'pin-cost'" in source or "line.className = 'pin-cost'" in source


def test_a_step_nobody_measured_says_nothing_rather_than_nothing_spent() -> None:
    """A line saying "$0.00" would be this console claiming a step was free."""
    source = "\n".join(
        line
        for line in CONSOLE.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("//")
    )
    start = source.index("function writeCost(")
    body = source[start : source.index("\n}\n", start)]

    assert "if (!said.length) {" in body
    assert "line?.remove();" in body


# --- and the same fact as a width -----------------------------------------------------------------
@pytest.mark.unit
def test_what_a_step_cost_is_a_width_as_well_as_a_number() -> None:
    """ "Дорогие шаги видно, не читая цифр." Eight cards each saying $0.03 and one saying $0.19 all
    read as "some money" until one of them is five times wider than the rest."""
    console = CONSOLE.read_text(encoding="utf-8")
    start = console.index("function writeCost(")
    body = console[start : console.index("\n}\n", start)]

    assert "--of-the-dearest" in body
    assert "step.usd / dearest" in body


@pytest.mark.unit
def test_the_bar_is_drawn_against_the_dearest_step_and_not_a_fixed_sum() -> None:
    """A bar scaled to some number of dollars would be full on one pipeline and invisible on the
    next, which is a picture of the scale rather than of the work."""
    console = CONSOLE.read_text(encoding="utf-8")
    start = console.index("function showRuns(")
    body = console[start : console.index("\n}\n", start)]

    assert "Math.max(0, ...[...states.values()].map((step) => step.usd || 0))" in body


@pytest.mark.unit
def test_one_step_with_a_cost_gets_no_bar() -> None:
    """It is the dearest and the cheapest at once, and a full-width bar under it would say
    something about a comparison nobody has made."""
    console = CONSOLE.read_text(encoding="utf-8")
    start = console.index("function writeCost(")
    body = console[start : console.index("\n}\n", start)]

    assert "dearest !== step.usd" in body
