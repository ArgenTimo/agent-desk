"""The last two runs of one drawing, side by side (01M1X8DA98ZM5CA7VME8ECASZK).

"Тестировать пайплайн — значит запускать его несколько раз и смотреть, что изменилось. Сегодня шаг
хранит только последний результат (036-step-memory.sql намеренно), и для сравнения прогонов
понадобится история с номером прогона."

The history turned out to be there already: a card keeps its last result, which is what 036
deliberately does, and every *run* keeps what each of its steps produced. So this needed no storage
— it needed the comparison and somewhere to read it.

The columns are this file. What the rest of the runs said is `test_the_spread.py`, and since the
two are one reading of one history they are one module, one route and one panel: a row carries the
comparison, and grows the counting on the end of it when there is more than a pair to count.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk import comparing
from agent_desk.store.repo import Store
from agent_desk.web import routes

pytestmark = pytest.mark.unit

HERE = pathlib.Path(__file__).resolve().parents[2]
CONSOLE = HERE / "agent_desk" / "web" / "static" / "console.js"


@pytest.fixture
async def desk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    yield store
    await store.close()


class _Step:
    def __init__(self, name: str, made: str = "", state: str = "done") -> None:
        self.name, self.made, self.state = name, made, state


def _two(
    earlier: list[_Step], later: list[_Step], labels: dict[str, str] | None = None
) -> tuple[comparing.Row, ...]:
    """Two runs, newest first — the order the store answers in and the order `over` reads."""
    return comparing.over([later, earlier], labels).rows


# --- the comparison ---------------------------------------------------------------------------------
def test_a_step_that_answered_differently_is_marked() -> None:
    (row,) = _two([_Step("a", "one")], [_Step("a", "two")])

    assert row.changed
    assert row.says == "different"


def test_a_step_that_answered_the_same_is_not() -> None:
    (row,) = _two([_Step("a", "one")], [_Step("a", "one")])

    assert not row.changed
    assert row.says == "the same"


def test_whitespace_alone_is_not_a_difference() -> None:
    (row,) = _two([_Step("a", "one")], [_Step("a", " one\n")])

    assert not row.changed


def test_a_step_only_one_run_reached_says_which() -> None:
    """A run that stopped half way is the ordinary case when somebody is testing a pipeline, and
    "different" would be the wrong word for it."""
    rows = _two([_Step("a", "one")], [_Step("a", "one"), _Step("b", "two")])

    assert rows[1].says == "only the second run produced anything"


def test_a_step_that_has_since_been_removed_is_last() -> None:
    """The later run's order is the drawing as it is now: a step somebody added belongs where they
    put it, and one they removed belongs at the end rather than in the middle of a shape it is no
    longer part of."""
    rows = _two([_Step("gone", "x"), _Step("a", "one")], [_Step("a", "one")])

    assert [row.name for row in rows] == ["a", "gone"]
    assert rows[1].says == "only the first run produced anything"


def test_the_newest_run_is_the_after() -> None:
    """`store.runs()` answers newest first, and a comparison with the two the wrong way round reads
    as a pipeline getting worse every time it is improved."""
    (row,) = comparing.over([[_Step("a", "the newest")], [_Step("a", "the one before")]]).rows

    assert (row.before, row.after) == ("the one before", "the newest")


def test_the_cards_own_words_are_used_where_there_are_any() -> None:
    (row,) = _two([_Step("step:1")], [_Step("step:1")], {"step:1": "summarise"})

    assert row.label == "summarise"


def test_the_line_above_it_counts_rather_than_judges() -> None:
    """A model asked the same question twice answers differently. "It got better" is not a thing
    this program could know, and a verdict here would make noise look like progress."""
    rows = _two([_Step("a", "one"), _Step("b", "two")], [_Step("a", "one"), _Step("b", "three")])

    assert comparing.in_a_word(rows) == "1 of 2 steps produced something different"
    assert comparing.in_a_word([]) == "neither run produced anything"


def test_nothing_changed_says_so_plainly() -> None:
    rows = _two([_Step("a", "one")], [_Step("a", "one")])

    assert comparing.in_a_word(rows) == "all 1 steps produced the same thing"


def test_a_long_answer_is_cut_on_both_sides() -> None:
    """Enough to see that two answers differ and roughly how; the whole of either is one click away
    on the step itself."""
    (row,) = _two([_Step("a", "x" * 5000)], [_Step("a", "y" * 5000)])

    assert len(row.before) == comparing.SAID_CHARS
    assert len(row.after) == comparing.SAID_CHARS


def test_two_runs_say_only_what_the_two_columns_show() -> None:
    """The counting is what the whole set adds, and with a pair there is nothing it could add that
    the two columns are not already showing."""
    (row,) = _two([_Step("a", "one")], [_Step("a", "two")])

    assert row.says == "different"


def test_one_run_is_neither_a_comparison_nor_a_spread() -> None:
    """A table of one column is what a person presses once and never again — which is why the
    control waits for two, and why one produces no rows rather than half a comparison."""
    found = comparing.over([[_Step("a", "one")]])

    assert found.rows == ()
    assert found.said == "one run so far, and two are needed to see what changed"


# --- the route --------------------------------------------------------------------------------------
async def test_it_answers_with_a_row_per_step(desk: Store) -> None:
    first = await desk.start_run(cards=["step:1"], repo_key="", cwd="")
    second = await desk.start_run(cards=["step:1"], repo_key="", cwd="")
    await desk.set_run_step(run_id=first.id, name="step:1", state="done", made="one")
    await desk.set_run_step(run_id=second.id, name="step:1", state="done", made="two")

    answer = await routes.compare_the_runs("step:1")
    said = json.loads(bytes(answer.body).decode())

    assert "1 of 1 steps produced something different" in said["said"]
    assert said["rows"][0]["before"] == "one"
    assert said["rows"][0]["after"] == "two"
    assert {one["mark"] for one in said["rows"][0]["marks"]} == {"before", "after"}


async def test_one_run_is_not_two(desk: Store) -> None:
    run = await desk.start_run(cards=["step:1"], repo_key="", cwd="")
    await desk.set_run_step(run_id=run.id, name="step:1", state="done", made="one")

    answer = await routes.compare_the_runs("step:1")
    said = json.loads(bytes(answer.body).decode())

    assert said["rows"] == []
    assert "two are needed" in said["said"]


async def test_only_the_runs_of_what_was_asked_about(desk: Store) -> None:
    """The bench is what the question is about, and a run of somebody else's drawing in the same
    console is not a second opinion on this one."""
    mine = await desk.start_run(cards=["step:1"], repo_key="", cwd="")
    other = await desk.start_run(cards=["step:2"], repo_key="", cwd="")
    await desk.set_run_step(run_id=mine.id, name="step:1", state="done", made="one")
    await desk.set_run_step(run_id=other.id, name="step:2", state="done", made="two")

    said = json.loads(bytes((await routes.compare_the_runs("step:1")).body).decode())

    assert said["rows"] == []


# --- and the panel ------------------------------------------------------------------------------------
def test_the_control_appears_only_when_there_are_two_runs_to_compare() -> None:
    """Comparing one run with nothing is a table of one column, and a control that produces one is
    a control somebody presses once."""
    source = "\n".join(
        line
        for line in CONSOLE.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("//")
    )
    start = source.index("function showCompare(")
    body = source[start : source.index("\n}\n", start)]

    assert "runsOfThisBench().length < 2" in body


def test_only_the_runs_of_what_is_on_the_bench() -> None:
    source = CONSOLE.read_text(encoding="utf-8")

    assert "function runsOfThisBench(" in source
    assert "(one.cards || []).some((name) => here.has(name))" in source
