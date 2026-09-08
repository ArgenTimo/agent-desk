"""A card that says what an answer has to be, and can decide it
(01M1XA1V9AS0WFJTGGZ6YRR9QZ).

"Без этого верстак — площадка для игры. С этим — харнесс: карточка-проверка на выходе шага
(содержит, не содержит, разбирается как JSON, короче N) и понятное «прошло/не прошло» на схеме.
Проверка — это Result с зубами: то, что уже описано полем «что считается сделанным», но проверяемое
машиной."

A Result has always said what counts as done. It said it to a person, in a sentence, and nothing
read it. This is that same field read by something that can decide — and only where it is written in
one of four forms, because a check guessed at from prose would be a pass or a fail invented from a
sentence somebody wrote for a human.
"""

from __future__ import annotations

import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk import checking, process
from agent_desk.store.repo import Store
from agent_desk.web import engine

pytestmark = pytest.mark.unit


@pytest.fixture
async def desk(tmp_path: pathlib.Path) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    yield store
    await store.close()


# --- reading one -------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("said", "kind"),
    [
        ("contains OK", "contains"),
        ("содержит OK", "contains"),
        ("does not contain ERROR", "missing"),
        ("не содержит ERROR", "missing"),
        ("is JSON", "json"),
        ("разбирается как JSON", "json"),
        ("shorter than 200 characters", "shorter"),
        ("короче 200 символов", "shorter"),
    ],
)
def test_the_four_forms_in_both_languages(said: str, kind: str) -> None:
    found = checking.read(said)

    assert found is not None
    assert found.kind == kind


def test_a_sentence_for_a_person_is_not_a_check() -> None:
    """Turning "the migration is applied cleanly" into a failed check would make every drawing
    older than this one red."""
    assert checking.read("the migration is applied cleanly") is None
    assert checking.read("") is None


def test_a_caveat_is_not_a_check() -> None:
    """ "Contains a thing, unless it is empty" is a sentence. Reading the first three words of it
    would make a check out of the caveat."""
    found = checking.read("contains OK, unless the input was empty")

    assert found is not None
    assert found.against == "OK, unless the input was empty", (
        "it read part of the sentence as the thing to look for"
    )


def test_quotes_around_the_thing_are_not_part_of_it() -> None:
    found = checking.read('contains "OK"')

    assert found is not None and found.against == "OK"


# --- deciding one -------------------------------------------------------------------------------------
def test_json_that_parses_passes() -> None:
    ok, why = checking.passes(checking.Check("json"), '{"a": 1}')

    assert ok and "is JSON" in why


def test_json_that_does_not_parse_says_what_went_wrong() -> None:
    """ "It failed" is a fact somebody has to investigate; "it is not JSON: Expecting value" is one
    they can act on."""
    ok, why = checking.passes(checking.Check("json"), "not json at all")

    assert not ok and "not JSON" in why


def test_shorter_than_is_shorter_and_not_equal() -> None:
    assert checking.passes(checking.Check("shorter", "5"), "abcde")[0] is False
    assert checking.passes(checking.Check("shorter", "5"), "abcd")[0] is True


def test_a_failure_says_what_was_asked_and_what_was_there() -> None:
    _ok, why = checking.passes(checking.Check("shorter", "5"), "abcdefg")

    assert "7 characters" in why
    assert "shorter than 5" in why


def test_contains_ignores_case() -> None:
    assert checking.passes(checking.Check("contains", "ok"), "Everything OK here")[0]


def test_does_not_contain_is_the_other_way_round() -> None:
    assert checking.passes(checking.Check("missing", "ERROR"), "all fine")[0]
    assert not checking.passes(checking.Check("missing", "ERROR"), "an ERROR happened")[0]


# --- and on the diagram --------------------------------------------------------------------------------
def _cards() -> tuple[process.Card, process.Card]:
    step = process.Card(name="step:a", role="action", label="ask", said={"asks": "say it"})
    check = process.Card(
        name="step:c", role="result", label="the check", said={"counts": "contains OK"}
    )
    return step, check


async def test_a_passing_check_is_written_on_its_own_card(desk: Store) -> None:
    """ "Понятное «прошло/не прошло» на схеме" — on the check, not only in the run's log."""
    step, check = _cards()
    lines = [process.Line(from_name=step.name, to_name=check.name, kind="makes")]
    run = await desk.start_run(cards=[step.name, check.name], repo_key="", cwd="")

    broke = await engine._checked(desk, run, step, "everything OK", [step, check], lines)

    assert broke == ""
    assert (await desk.cards_made())[check.name].startswith("passed")


async def test_a_failing_check_says_why_and_stops_the_run(desk: Store) -> None:
    step, check = _cards()
    lines = [process.Line(from_name=step.name, to_name=check.name, kind="makes")]
    run = await desk.start_run(cards=[step.name, check.name], repo_key="", cwd="")

    broke = await engine._checked(desk, run, step, "nothing here", [step, check], lines)

    assert "the check" in broke
    assert (await desk.cards_made())[check.name].startswith("failed")


async def test_every_check_is_run_and_not_only_the_first(desk: Store) -> None:
    """Two Results on one step are two things somebody wanted to be true, and stopping at the first
    failure would hide the second until the first was fixed."""
    step, first = _cards()
    second = process.Card(name="step:c2", role="result", label="also", said={"counts": "is JSON"})
    lines = [
        process.Line(from_name=step.name, to_name=first.name, kind="makes"),
        process.Line(from_name=step.name, to_name=second.name, kind="makes"),
    ]
    run = await desk.start_run(cards=[step.name], repo_key="", cwd="")

    broke = await engine._checked(desk, run, step, "nothing", [step, first, second], lines)

    assert "the check" in broke and "also" in broke


async def test_a_result_that_is_a_sentence_changes_nothing(desk: Store) -> None:
    step = process.Card(name="step:a", role="action", label="ask", said={"asks": "say it"})
    said = process.Card(
        name="step:c", role="result", label="done", said={"counts": "the release is out"}
    )
    lines = [process.Line(from_name=step.name, to_name=said.name, kind="makes")]
    run = await desk.start_run(cards=[step.name], repo_key="", cwd="")

    broke = await engine._checked(desk, run, step, "anything", [step, said], lines)

    assert broke == ""
    assert said.name not in await desk.cards_made()


async def test_a_check_on_another_step_is_not_applied_to_this_one(desk: Store) -> None:
    """A Result hanging off a different step is a statement about that step."""
    step, check = _cards()
    other = process.Card(name="step:b", role="action", label="other", said={"asks": "x"})
    lines = [process.Line(from_name=other.name, to_name=check.name, kind="makes")]
    run = await desk.start_run(cards=[step.name], repo_key="", cwd="")

    assert await engine._checked(desk, run, step, "nothing here", [step, other, check], lines) == ""


def test_both_endings_of_a_step_are_checked() -> None:
    """A step answered by a model and a step done by an agent both produce something, and a check
    that only saw one of them would pass silently on the other."""
    source = (
        pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "engine.py"
    ).read_text(encoding="utf-8")

    assert source.count("_checked(store, run, card") == 2
