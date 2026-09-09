"""This has failed like this before (01M1XED1DTZB50QJ43YJ8WQB1M).

"Задача упала с текстом, который почти совпадает с текстом падения на прошлой неделе. Консоль это
видит и говорит: то же самое было тогда-то… Все данные есть: `task.detail` хранится, задачи не
удаляются. Дешёвая функция с эффектом памяти команды."
"""

from __future__ import annotations

import pathlib
from typing import ClassVar

import pytest
from agent_desk import recalling

pytestmark = pytest.mark.unit

CARD = (
    pathlib.Path(__file__).resolve().parents[2]
    / "agent_desk"
    / "web"
    / "templates"
    / "_card_blocker.html"
)

A_FAILURE = "Traceback: ConnectionResetError while writing to /tmp/run-4172/pipe after 31s"


def _before(id: str, detail: str, at: int = 1) -> recalling.Before:
    return recalling.Before(id=id, title=f"task {id}", detail=detail, at=at)


def test_the_same_failure_with_different_numbers_and_paths_is_the_same_failure() -> None:
    """Two runs of one failure differ in a path, a line number, a duration. Those are what is
    taken out before comparing rather than what is allowed to make one look like another."""
    again = "Traceback: ConnectionResetError while writing to /tmp/run-9981/pipe after 4s"

    (only,) = recalling.like_this(A_FAILURE, [_before("a", again)])

    assert only.id == "a"
    assert only.alike >= recalling.ALIKE


def test_a_different_failure_is_not_recalled() -> None:
    """A console that says "this happened before" about something that did not is a console whose
    memory nobody trusts twice."""
    assert recalling.like_this(A_FAILURE, [_before("a", "the gate went red: 3 tests failed")]) == []


def test_a_failure_that_said_nothing_matches_nothing() -> None:
    """Two runs about which the console knows equally little are not the same failure."""
    assert recalling.like_this("", [_before("a", A_FAILURE)]) == []
    assert recalling.like_this(A_FAILURE, [_before("a", "")]) == []


def test_the_most_alike_comes_first_and_the_newest_breaks_a_tie() -> None:
    same = A_FAILURE
    nearly = A_FAILURE.replace("ConnectionResetError", "ConnectionResetError (again)")

    found = recalling.like_this(
        A_FAILURE, [_before("old", same, 1), _before("new", same, 9), _before("near", nearly, 5)]
    )

    assert [one.id for one in found][:2] == ["new", "old"]


def test_only_a_few_are_offered() -> None:
    """A memory that lists twelve is a list somebody scrolls past."""
    found = recalling.like_this(A_FAILURE, [_before(str(at), A_FAILURE, at) for at in range(10)])

    assert len(found) == 3


def test_it_says_when_and_what_it_was_called_and_nothing_more() -> None:
    """Nobody records what fixed a failure, and a sentence claiming it would be an invention
    sitting exactly where somebody is looking for a fact.

    Rendered and then read, not matched against the source: the first version of this searched the
    template for "what fixed it" and failed on the comment explaining that it does not say that —
    a substring check tripping over its own documentation, twice in one shift."""
    from agent_desk.web.routes import env

    said = env.get_template("_card_blocker.html").render(
        one=_a_blocker(),
        card_id="blocker:x",
        before=[recalling.Match(id="a", title="fix the reader", at=1, alike=0.9)],
    )
    shown = " ".join(said.split())

    assert "It has failed like this before" in shown
    assert "fix the reader" in shown
    for claiming in ("what fixed it", "what helped", "this fixed", "try "):
        assert claiming not in shown.lower(), f"the card offers {claiming!r}"


def _a_blocker() -> object:
    class Stuck:
        kind = "task"
        what = "a task"
        why = A_FAILURE
        when = 1
        repo_key = "k"
        ref = "task:x"
        card = "task:x"
        action = ""
        action_says = ""
        carries: ClassVar[dict[str, str]] = {}
        holding_up: ClassVar[list[object]] = []

    return Stuck()


def test_a_blocker_with_no_earlier_failure_says_nothing_about_one() -> None:
    from agent_desk.web.routes import env

    said = env.get_template("_card_blocker.html").render(
        one=_a_blocker(), card_id="blocker:x", before=[]
    )

    assert "failed like this before" not in said
