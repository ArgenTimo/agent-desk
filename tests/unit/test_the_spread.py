"""Several runs of one drawing, and what they disagreed about
(01M1XA1V9T96HECGYPGVGJ230Q, 01M1XA1V9E9SE2070SQ9MPN625).

"Модель отвечает по-разному. Схема, прогнанная один раз, показывает одну выдачу из распределения, и
решение по ней — это решение по шуму."

"Один пример ничего не говорит о промпте… прогон схемы по каждой строке, с таблицей результатов и
долей прошедших проверок. Это то место, где «поиграться» превращается в «померить»."

Two ideas and one thing: running a drawing twenty times with one input and running it once per line
of a set are the same act with a different list of inputs.

And a third, which is `test_comparing_runs.py`: what changed between the last two runs is the same
history read the same way, so the counting here and the two columns there are one module, one route
and one panel — the columns are the last two, and the count is what the row says about the rest.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import AsyncIterator
from typing import ClassVar
from urllib.parse import urlencode

import pytest
from agent_desk import comparing
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
    found = comparing.over(
        [[_Step("a", "done", "one")], [_Step("a", "done", "two")], [_Step("a", "done", "one")]]
    )

    (row,) = found.rows
    assert row.answers == (("one", 2), ("two", 1))
    assert "2 different answers across 3 runs (2, 1)" in row.says


def test_every_run_agreeing_is_said_plainly() -> None:
    found = comparing.over([[_Step("a", "done", "x")]] * 3)

    assert found.rows[0].says == "the same; every run answered the same"


def test_whitespace_alone_is_not_a_different_answer() -> None:
    found = comparing.over(
        [
            [_Step("a", "done", "one two")],
            [_Step("a", "done", "one   two\n")],
            [_Step("a", "done", "one two ")],
        ]
    )

    assert len(found.rows[0].answers) == 1


def test_the_share_that_passed_is_counted() -> None:
    """ "Доля прошедших проверок" — a check that failed fails its step, so this is readable from the
    states without a second record of it."""
    found = comparing.over(
        [[_Step("a", "done", "x")], [_Step("a", "failed")], [_Step("a", "done", "x")]]
    )

    assert found.said.startswith("2 of 3 runs finished without a step failing")
    assert "1 of 3 did not pass" in found.rows[0].says


def test_a_step_every_run_failed_at_counts_the_failures_and_nothing_else() -> None:
    """There are no answers to count when nothing got through it, and "0 different answers" is a
    sentence about a step nobody would recognise as the one that broke every run."""
    found = comparing.over([[_Step("a", "failed")]] * 3)

    assert found.rows[0].says == "neither run produced anything; 3 of 3 did not pass"


def test_a_step_no_run_reached_says_so() -> None:
    found = comparing.over([[_Step("a", "failed"), _Step("b", "waiting")]] * 2)

    assert found.rows[1].says == "no run got here"


def test_the_steps_are_in_the_order_they_were_reached() -> None:
    """Sorting by how often a step was reached would put the steps of a run that failed early at the
    bottom, where they read as unimportant rather than as the place it stopped."""
    found = comparing.over([[_Step("first", "done"), _Step("second", "done")]] * 2)

    assert [row.name for row in found.rows] == ["first", "second"]


def test_nothing_run_is_a_sentence_and_not_a_zero() -> None:
    assert comparing.over([]).said == "nothing has been run yet"


def test_a_pair_is_not_told_what_its_own_columns_already_show() -> None:
    """The counting is what the whole set adds. Two runs are the two columns, and "2 different
    answers across 2 runs" beside them would be the panel reading itself back."""
    found = comparing.over([[_Step("a", "done", "one")], [_Step("a", "done", "two")]])

    assert found.rows[0].says == "different"


def test_it_does_not_score_or_rank() -> None:
    """There is no number that says one prompt is better than another, and inventing one here would
    be this console making the judgement somebody ran twenty examples to make themselves."""
    source = (
        pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "comparing.py"
    ).read_text(encoding="utf-8")

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


async def test_runs_started_in_one_millisecond_still_have_a_last_two(desk: Store) -> None:
    """Five runs started in a loop share a timestamp, and which of them the panel calls "the last
    two" is not a thing to leave to whatever order the rows come back in."""
    name = await _a_pipeline(desk)

    _status, said = await _repeat({"cards": name, "times": "5"})

    started = list(said["runs"])  # type: ignore[call-overload]
    assert [one.id for one in await desk.runs()] == started[::-1]


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
    for said in ("one", "two", "one"):
        run = await desk.start_run(cards=[name], repo_key="", cwd="")
        await desk.set_run_step(run_id=run.id, name=name, state="done", made=said)

    answer = await routes.compare_the_runs(name)
    back = json.loads(bytes(answer.body).decode())

    assert "3 of 3 runs finished" in back["said"]
    (row,) = back["rows"]
    assert row["label"] == "ask"
    # The columns are the last two runs, and the counting is what the row says about all three.
    assert (row["before"], row["after"]) == ("two", "one")
    assert "2 different answers across 3 runs (2, 1)" in row["says"]


def test_one_control_is_offered_and_it_wants_two_runs() -> None:
    """One run has no spread, and a table of one column is what a person presses once and never
    again. One control, because the spread and the comparison were two answers to one question."""
    source = "\n".join(
        line
        for line in CONSOLE.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("//")
    )
    start = source.index("function showCompare(")
    body = source[start : source.index("\n}\n", start)]

    assert body.count("runsOfThisBench().length < 2") == 1
    assert "spread-runs" not in source


def test_repeating_is_offered_only_for_a_drawing_of_prompts() -> None:
    source = "\n".join(
        line
        for line in CONSOLE.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("//")
    )
    start = source.index("function showCompare(")
    body = source[start : source.index("\n}\n", start)]

    assert "processSaid.fixed" in body
