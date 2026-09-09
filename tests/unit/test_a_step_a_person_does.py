"""A step a person does, with the same standing as one an agent does
(01M1XED1D09FG337BD6C0PFNAF).

"У Action есть разрешения; добавить среди них «это делает человек» — и шаг встаёт в очередь к
человеку, показывает, что от него нужно, ждёт нажатия и отдаёт результат дальше по цепочке."

"Без этого любой настоящий процесс обрывается на первом же согласовании."
"""

from __future__ import annotations

import pathlib

import pytest
from agent_desk import allowed, process

pytestmark = pytest.mark.unit

CONSOLE = (
    pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "static" / "console.js"
)
ENGINE = pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "engine.py"


def test_it_is_a_permission_and_not_a_sixth_role() -> None:
    """It is a fact about *this step*, not a new kind of thing: the same Action, done by a
    person."""
    assert allowed.is_allowed("hands")
    assert "hands" not in process.STEPS
    assert allowed.ALLOWED["hands"].says == "a person does this one"


def test_it_is_enforced_in_the_strongest_sense_any_of_them_are() -> None:
    """No agent is started, so there is nothing to obey or to ignore — unlike `net`, which is asked
    for in words and cannot be held."""
    assert allowed.ALLOWED["hands"].held == "enforced"
    assert "hands" in allowed.enforced(("hands", "net"))


def test_a_step_nobody_has_touched_is_still_done_by_an_agent() -> None:
    """The default is unchanged: this is something somebody says out loud about one step."""
    assert "hands" not in allowed.NATURALLY
    assert "hands" not in allowed.leave_for(None)


def test_the_run_holds_before_it_asks_or_starts_anything() -> None:
    """The whole of the permission is that nothing is started, so it is read before the work is
    assembled rather than after."""
    source = ENGINE.read_text(encoding="utf-8")
    start = source.index("async def _do(")
    body = source[start : source.index("\nasync def ", start + 10)]

    assert 'if "hands" in given:' in body
    assert body.index('if "hands" in given:') < body.index("reads_only")


def test_it_says_what_is_wanted_rather_than_only_that_it_waits() -> None:
    """A queue entry reading "waiting" and nothing else is one nobody can act on."""
    source = ENGINE.read_text(encoding="utf-8")
    start = source.index("async def _wait_for_a_person(")
    body = source[start : source.index("\nasync def ", start + 10)]

    assert 'card.said.get("do")' in body
    assert 'state="held"' in body, "a run waiting for an approval is a run that is fine"


def test_the_same_press_answers_it_and_says_which_wait_it_is_answering() -> None:
    """An Event waits for the world; this waits for you, and "it happened" is the wrong thing to
    press when what is being asked is whether *you* have done it."""
    source = "\n".join(
        line
        for line in CONSOLE.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("//")
    )

    assert "'I have done it'" in source
    assert "dataset.byHand" in source
