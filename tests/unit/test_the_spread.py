"""Several runs of one drawing, and what they disagreed about
(01M1XA1V9T96HECGYPGVGJ230Q, 01M1XA1V9E9SE2070SQ9MPN625).

"Модель отвечает по-разному. Схема, прогнанная один раз, показывает одну выдачу из распределения, и
решение по ней — это решение по шуму."

"Один пример ничего не говорит о промпте… прогон схемы по каждой строке, с таблицей результатов и
долей прошедших проверок. Это то место, где «поиграться» превращается в «померить»."

Two ideas and one thing: running a drawing twenty times with one input and running it once per line
of a set are the same act with a different list of inputs.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import AsyncIterator
from typing import ClassVar
from urllib.parse import urlencode

import pytest
from agent_desk import spread
from agent_desk.store.repo import Store
from agent_desk.web import routes

pytestmark = pytest.mark.unit

CONSOLE = (
    pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "static" / "console.js"
)


@pytest.fixture
async def desk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    yield store
    await store.close()


class _Step:
    def __init__(self, name: str, state: str, made: str = "") -> None:
        self.name, self.state, self.made = name, state, made


# --- what a spread counts ----------------------------------------------------------------------------
def test_it_counts_the_different_answers_commonest_first() -> None:
    """ "Usually this, sometimes that" is the shape of the finding."""
    found = spread.over(
        [[_Step("a", "done", "one")], [_Step("a", "done", "two")], [_Step("a", "done", "one")]]
    )

    (step,) = found.steps
    assert step.answers == (("one", 2), ("two", 1))
    assert step.says == "2 different answers"


def test_every_run_agreeing_is_said_plainly() -> None:
    found = spread.over([[_Step("a", "done", "x")], [_Step("a", "done", "x")]])

    assert found.steps[0].says == "every run answered the same"


def test_whitespace_alone_is_not_a_different_answer() -> None:
    found = spread.over([[_Step("a", "done", "one two")], [_Step("a", "done", "one   two\n")]])

    assert len(found.steps[0].answers) == 1


def test_the_share_that_passed_is_counted() -> None:
    """ "Доля прошедших проверок" — a check that failed fails its step, so this is readable from the
    states without a second record of it."""
    found = spread.over(
        [[_Step("a", "done", "x")], [_Step("a", "failed")], [_Step("a", "done", "x")]]
    )

    assert found.said == "2 of 3 runs finished without a step failing"
    assert "1 of 3 did not pass" in found.steps[0].says


def test_a_step_no_run_reached_says_so() -> None:
    found = spread.over([[_Step("a", "failed"), _Step("b", "waiting")]])

    assert found.steps[1].says == "no run got here"


def test_the_steps_are_in_the_order_they_were_reached() -> None:
    """Sorting by how often a step was reached would put the steps of a run that failed early at the
    bottom, where they read as unimportant rather than as the place it stopped."""
    found = spread.over([[_Step("first", "done"), _Step("second", "done")]])

    assert [step.name for step in found.steps] == ["first", "second"]


def test_nothing_run_is_a_sentence_and_not_a_zero() -> None:
    assert spread.over([]).said == "nothing has been run yet"


def test_it_does_not_score_or_rank() -> None:
    """There is no number that says one prompt is better than another, and inventing one here would
    be this console making the judgement somebody ran twenty examples to make themselves."""
    source = (pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "spread.py").read_text(
        encoding="utf-8"
    )

    for word in ("score", "rank", "average", "better"):
        assert f"def {word}" not in source


# --- starting them -----------------------------------------------------------------------------------
async def _repeat(fields: dict[str, str]) -> tuple[int, dict[str, object]]:
    class Request:
        async def body(self) -> bytes:
            return urlencode(fields).encode()

        headers: ClassVar[dict[str, str]] = {"content-type": "application/x-www-form-urlencoded"}

    answer = await routes.repeat_a_run(Request())  # type: ignore[arg-type]
    return answer.status_code, json.loads(bytes(answer.body).decode())


async def _a_pipeline(desk: Store) -> str:
    card = await desk.add_step_card("ask")
    await desk.set_card_role(card.name, "action")
    await desk.set_card_field(card.name, "asks", "say something")
    return card.name


async def test_it_starts_the_number_asked_for(desk: Store) -> None:
    name = await _a_pipeline(desk)

    status, said = await _repeat({"cards": name, "times": "3", "given": "the input"})

    assert status == 200
    assert said["started"] == 3
    assert len(await desk.runs()) == 3
    assert {one.given for one in await desk.runs()} == {"the input"}


async def test_a_set_of_lines_is_one_run_each(desk: Store) -> None:
    name = await _a_pipeline(desk)

    status, said = await _repeat({"cards": name, "each": "first\nsecond\nthird"})

    assert status == 200 and said["started"] == 3
    assert {one.given for one in await desk.runs()} == {"first", "second", "third"}


async def test_there_is_a_ceiling(desk: Store) -> None:
    """Ten runs of a five-step pipeline is fifty model calls, which is a number somebody should be
    able to picture before pressing."""
    name = await _a_pipeline(desk)

    _status, said = await _repeat({"cards": name, "times": "500"})

    assert said["started"] == routes.MOST_TIMES


async def test_a_drawing_that_does_work_is_refused(desk: Store) -> None:
    """Ten runs of it is ten agents in ten worktrees, which is not a thing to start from a text
    box — and a harness is prompts by definition, so nothing this is for is refused."""
    card = await desk.add_step_card("build")
    await desk.set_card_role(card.name, "action")
    await desk.set_card_field(card.name, "do", "write the migration")

    status, said = await _repeat({"cards": card.name, "times": "3"})

    assert status == 409
    assert "work in a checkout" in str(said["why"])
    assert await desk.runs() == []


# --- and reading them --------------------------------------------------------------------------------
async def test_the_spread_of_this_bench_comes_back_as_rows(desk: Store) -> None:
    name = await _a_pipeline(desk)
    for said in ("one", "two"):
        run = await desk.start_run(cards=[name], repo_key="", cwd="")
        await desk.set_run_step(run_id=run.id, name=name, state="done", made=said)

    answer = await routes.spread_of_runs(name)
    back = json.loads(bytes(answer.body).decode())

    assert "2 of 2 runs finished" in back["said"]
    (row,) = back["rows"]
    assert row["label"] == "ask"
    assert row["before"] in ("one", "two")
    assert row["after"] in ("one", "two")
    assert row["before"] != row["after"]


def test_both_controls_want_two_runs_before_they_appear() -> None:
    """One run has no spread, and a table of one column is what a person presses once and never
    again."""
    source = "\n".join(
        line
        for line in CONSOLE.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("//")
    )
    start = source.index("function showCompare(")
    body = source[start : source.index("\n}\n", start)]

    assert body.count("runsOfThisBench().length < 2") == 2


def test_repeating_is_offered_only_for_a_drawing_of_prompts() -> None:
    source = "\n".join(
        line
        for line in CONSOLE.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("//")
    )
    start = source.index("function showCompare(")
    body = source[start : source.index("\n}\n", start)]

    assert "processSaid.fixed" in body
