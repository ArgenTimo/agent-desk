"""Two runs of one drawing, side by side (01M1X8DA98ZM5CA7VME8ECASZK).

"Тестировать пайплайн — значит запускать его несколько раз и смотреть, что изменилось. Сегодня шаг
хранит только последний результат (036-step-memory.sql намеренно), и для сравнения прогонов
понадобится история с номером прогона."

The history turned out to be there already: a card keeps its last result, which is what 036
deliberately does, and every *run* keeps what each of its steps produced. So this needed no storage
— it needed the comparison and somewhere to read it.
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
    def __init__(self, name: str, made: str = "") -> None:
        self.name = name
        self.made = made


# --- the comparison ---------------------------------------------------------------------------------
def test_a_step_that_answered_differently_is_marked() -> None:
    (row,) = comparing.against([_Step("a", "one")], [_Step("a", "two")])

    assert row.changed
    assert row.says == "different"


def test_a_step_that_answered_the_same_is_not() -> None:
    (row,) = comparing.against([_Step("a", "one")], [_Step("a", "one")])

    assert not row.changed
    assert row.says == "the same"


def test_whitespace_alone_is_not_a_difference() -> None:
    (row,) = comparing.against([_Step("a", "one")], [_Step("a", " one\n")])

    assert not row.changed


def test_a_step_only_one_run_reached_says_which() -> None:
    """A run that stopped half way is the ordinary case when somebody is testing a pipeline, and
    "different" would be the wrong word for it."""
    rows = comparing.against([_Step("a", "one")], [_Step("a", "one"), _Step("b", "two")])

    assert rows[1].says == "only the second run got here"


def test_a_step_that_has_since_been_removed_is_last() -> None:
    """The later run's order is the drawing as it is now: a step somebody added belongs where they
    put it, and one they removed belongs at the end rather than in the middle of a shape it is no
    longer part of."""
    rows = comparing.against([_Step("gone", "x"), _Step("a", "one")], [_Step("a", "one")])

    assert [row.name for row in rows] == ["a", "gone"]
    assert rows[1].says == "only the first run got here"


def test_the_cards_own_words_are_used_where_there_are_any() -> None:
    (row,) = comparing.against([_Step("step:1")], [_Step("step:1")], {"step:1": "summarise"})

    assert row.label == "summarise"


def test_the_line_above_it_counts_rather_than_judges() -> None:
    """A model asked the same question twice answers differently. "It got better" is not a thing
    this program could know, and a verdict here would make noise look like progress."""
    rows = comparing.against(
        [_Step("a", "one"), _Step("b", "two")], [_Step("a", "one"), _Step("b", "three")]
    )

    assert comparing.in_a_word(rows) == "1 of 2 steps produced something different"
    assert comparing.in_a_word([]) == "neither run produced anything"


def test_nothing_changed_says_so_plainly() -> None:
    rows = comparing.against([_Step("a", "one")], [_Step("a", "one")])

    assert comparing.in_a_word(rows) == "all 1 steps produced the same thing"


def test_a_long_answer_is_cut_on_both_sides() -> None:
    """Enough to see that two answers differ and roughly how; the whole of either is one click away
    on the step itself."""
    (row,) = comparing.against([_Step("a", "x" * 5000)], [_Step("a", "y" * 5000)])

    assert len(row.before) == comparing.SAID_CHARS
    assert len(row.after) == comparing.SAID_CHARS


# --- the route --------------------------------------------------------------------------------------
async def test_it_answers_with_a_row_per_step(desk: Store) -> None:
    first = await desk.start_run(cards=["step:1"], repo_key="", cwd="")
    second = await desk.start_run(cards=["step:1"], repo_key="", cwd="")
    await desk.set_run_step(run_id=first.id, name="step:1", state="done", made="one")
    await desk.set_run_step(run_id=second.id, name="step:1", state="done", made="two")

    answer = await routes.compare_two_runs(f"{first.id},{second.id}")
    said = json.loads(bytes(answer.body).decode())

    assert said["said"] == "1 of 1 steps produced something different"
    assert said["rows"][0]["before"] == "one"
    assert said["rows"][0]["after"] == "two"


async def test_one_run_is_not_two(desk: Store) -> None:
    answer = await routes.compare_two_runs("only-one")
    said = json.loads(bytes(answer.body).decode())

    assert said["rows"] == []
    assert "two runs are needed" in said["said"]


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


def test_the_older_run_is_the_before() -> None:
    """`/workbench/runs` answers newest first, and a comparison with the two the wrong way round
    reads as a pipeline getting worse every time it is improved."""
    source = CONSOLE.read_text(encoding="utf-8")

    assert "[mine[1].id, mine[0].id].join(',')" in source


def test_only_the_runs_of_what_is_on_the_bench() -> None:
    source = CONSOLE.read_text(encoding="utf-8")

    assert "function runsOfThisBench(" in source
    assert "(one.cards || []).some((name) => here.has(name))" in source
