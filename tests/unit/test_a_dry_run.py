"""Walking a drawing without running it (01M1XED1C0SDGWHMX3GRYBE47R).

"Нажать «как если бы» — и движок проходит схему до конца: показывает порядок, какие развилки выбрал
бы, что именно получил бы на вход каждый шаг, и где остановился бы. Ни одного агента, ни одного
вызова модели, ни одной записи."

"Схему из восьми шагов сегодня нельзя проверить иначе, чем запустив её и заплатив. Холостой прогон
превращает конструктор из «страшно нажать» в «попробовал двадцать раз, потом запустил»."
"""

from __future__ import annotations

import pathlib

import pytest
from agent_desk import process

pytestmark = pytest.mark.unit

HERE = pathlib.Path(__file__).resolve().parents[2]
CONSOLE = HERE / "agent_desk" / "web" / "static" / "console.js"


def _a_step(name: str, role: str = "action", **said: str) -> process.Card:
    return process.Card(name=name, role=role, label=name, said=dict(said))


def _then(from_name: str, to_name: str) -> process.Line:
    return process.Line(from_name=from_name, to_name=to_name, kind="then")


def _filled(name: str, role: str = "action") -> process.Card:
    """A card with every field its role needs, so it is not the thing that stops the run."""
    said = {one.name: "something" for one in __import__("agent_desk").roles.fields_of(role)}
    return process.Card(name=name, role=role, label=name, said=said)


# --- the walk -------------------------------------------------------------------------------------
def test_it_walks_in_the_order_a_run_would() -> None:
    """Not new arithmetic: `order` already says the sequence, and a dry run that answered from a
    second calculation would be one that disagrees with the real one."""
    cards = [_filled("b"), _filled("a")]
    lines = [_then("a", "b")]

    walked = process.walk(cards, lines)

    assert [one.name for one in walked] == ["a", "b"]


def test_a_step_says_what_it_would_be_told() -> None:
    """ "Что именно получил бы на вход каждый шаг." The same `memory_for` a real run uses."""
    cards = [
        process.Card(name="thing", role="object", label="the log"),
        _filled("read"),
    ]
    lines = [process.Line(from_name="thing", to_name="read", kind="then")]

    (only,) = [one for one in process.walk(cards, lines) if one.name == "read"]

    assert "the log" in only.told
    assert only.told == process.memory_for("read", cards, lines)


def test_a_decision_names_the_ways_out_and_does_not_pick_one() -> None:
    """The one place a dry run has to admit what it cannot know: a Decision chooses by what it is
    told at the time."""
    cards = [_filled("choose", "decision"), _filled("left"), _filled("right")]
    lines = [
        process.Line(from_name="choose", to_name="left", kind="if", says="it is green"),
        process.Line(from_name="choose", to_name="right", kind="if", says="it is red"),
    ]

    (only,) = [one for one in process.walk(cards, lines) if one.name == "choose"]

    assert set(only.branches) == {"it is green", "it is red"}


def test_an_ordinary_step_has_no_branches() -> None:
    (only,) = process.walk([_filled("do")], [])

    assert only.branches == ()


def test_where_it_would_stop_and_what_would_never_happen() -> None:
    """ "И где остановился бы." "And then these four would never happen" is half of what somebody is
    asking when they press this."""
    cards = [_a_step("first"), _filled("second"), _filled("third")]
    lines = [_then("first", "second"), _then("second", "third")]

    walked = process.walk(cards, lines)

    assert walked[0].stops.startswith("it has not said: ")
    assert walked[1].stops == "a step before this one would have stopped the run"
    assert walked[2].stops == "a step before this one would have stopped the run"


def test_a_drawing_that_can_run_stops_nowhere() -> None:
    walked = process.walk([_filled("a"), _filled("b")], [_then("a", "b")])

    assert [one.stops for one in walked] == ["", ""]


def test_only_steps_are_walked() -> None:
    """An Object is a thing that exists and a Result is what came out. Neither is executed, and a
    walk that listed them would be describing a run that does not happen."""
    cards = [_filled("do"), process.Card(name="thing", role="object", label="a file")]

    walked = process.walk(cards, [])

    assert [one.name for one in walked] == ["do"]


def test_a_tangle_is_not_walked_into() -> None:
    """A step in a cycle has no "before", and inventing one would produce a walk whose order
    nobody chose."""
    cards = [_filled("a"), _filled("b")]
    lines = [_then("a", "b"), _then("b", "a")]

    assert process.walk(cards, lines) == ()


# --- and the console at the other end -------------------------------------------------------------
def _code() -> str:
    return "\n".join(
        line
        for line in CONSOLE.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("//")
    )


def test_the_dry_run_reads_the_same_answer_the_process_panel_does() -> None:
    """A dry run that answered from a second calculation would disagree with the real one, which is
    worse than not having it."""
    source = _code()
    start = source.index("document.querySelector('[data-asif]')")
    body = source[start : source.index("\n});", start)]

    assert "readProcess()" in body
    assert "fetch(" not in body, "it asks somewhere else and can drift"


def test_pressing_it_reads_the_bench_again() -> None:
    """A walk shown from what the bench looked like a minute ago is the wrong answer to "what would
    happen if I pressed run now"."""
    source = _code()
    start = source.index("document.querySelector('[data-asif]')")
    body = source[start : source.index("\n});", start)]

    assert "await readProcess();" in body and "showAsIf();" in body


def test_nothing_about_it_starts_anything() -> None:
    """ "Ни одного агента, ни одного вызова модели, ни одной записи." The control is next to the one
    that does start things, so this is the property that keeps them apart."""
    source = _code()
    start = source.index("function showAsIf(")
    body = source[start : source.index("\n}\n", start)]

    for spending in ("fetch(", "/workbench/run", "pressTheButton", "combine("):
        assert spending not in body, f"the dry run reaches {spending!r}"


def test_reading_the_process_happens_when_either_panel_is_open() -> None:
    """Found in the browser: written as "return when the process panel is shut", opening the dry
    run read nothing at all — and the panel said "nothing here is a step" over a bench with
    thirteen of them. A panel confidently describing a drawing it had never fetched is the fifth
    rule wearing a UI."""
    source = _code()
    start = source.index("async function readProcess(")
    body = source[start : source.index("\n}\n", start)]

    assert "asif-panel" in body
    assert "if (!panel || (panel.hidden && (!asif || asif.hidden))) return;" in body
