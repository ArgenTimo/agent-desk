"""What a step may do, and the distinction the whole feature rests on.

"Это то, что отличает конструктор, которому можно доверить запуск, от схемы, которую страшно
нажать." What makes it trustworthy is that each switch says whether this console *enforces* it or
only asks — a row of switches that look alike but do not work alike is worse than no switches.
"""

from __future__ import annotations

import pathlib

import pytest
from agent_desk import allowed


@pytest.mark.unit
def test_every_permission_says_whether_it_is_held_or_only_asked_for() -> None:
    """The field that keeps this from being a permissions screen that lies by omission."""
    for one in allowed.ALLOWED.values():
        assert one.held in ("enforced", "asked"), f"{one.name} says it is {one.held!r}"
        assert one.how, f"{one.name} does not say what makes it true"


@pytest.mark.unit
def test_the_one_this_console_cannot_hold_says_so() -> None:
    """Reaching the network goes into the briefing in words and nothing here stops an agent that
    ignores it. Saying that plainly is more useful than leaving it out, and far more useful than
    a switch that implies otherwise."""
    assert allowed.ALLOWED["net"].held == "asked"
    assert "nothing here can stop" in allowed.ALLOWED["net"].how

    assert allowed.only_asked(("read", "work", "net")) == ("net",)
    assert allowed.enforced(("read", "work", "net")) == ("read", "work")


@pytest.mark.unit
def test_every_enforced_permission_names_a_branch_that_actually_exists() -> None:
    """A permission for something nothing in this program reads would be a switch that does
    nothing — which is the exact failure the module docstring exists to prevent. Each of these is
    checked against the code that would have to honour it."""
    pkg = pathlib.Path(__file__).resolve().parents[2] / "agent_desk"
    dispatching = (pkg / "dispatch.py").read_text(encoding="utf-8")
    landing = (pkg / "land.py").read_text(encoding="utf-8")

    # `work`: an agent in a worktree of its own.
    assert "worktree" in dispatching
    # `land` and `push`: this console calls the landing, and tells it whether to push.
    assert "def land(" in landing
    assert "push: bool" in landing
    # `read`: answering without starting an agent is a thing this program already does.
    assert (pkg / "answer" / "session.py").exists()


@pytest.mark.unit
def test_a_step_nobody_has_touched_runs_the_way_tasks_already_run() -> None:
    """Nothing granted is not everything refused. Its own copy and nothing further — and merging
    or pushing is a thing somebody should have to say out loud."""
    assert allowed.leave_for(None) == ("work",)
    assert allowed.leave_for([]) == ("work",)
    assert allowed.NATURALLY == ("work",)


@pytest.mark.unit
def test_a_permission_this_program_does_not_have_is_dropped_rather_than_kept() -> None:
    """Stored rows outlive the list. One left behind by a permission that has since been removed
    must not read as a permission that is still held."""
    assert allowed.leave_for(["work", "fly"]) == ("work",)
    # And a row set that is *entirely* unknown falls back rather than granting nothing at all,
    # because "this step may do nothing" is not a state anything here can act on.
    assert allowed.leave_for(["fly"]) == ("work",)


@pytest.mark.unit
def test_read_wins_over_work_when_both_are_somehow_set() -> None:
    """They are two answers to one question — is there an agent in a worktree. This is the branch
    that decides whether a process can write to disk, so the narrower reading is the only safe
    one."""
    assert allowed.reads_only(("read", "work"))
    assert not allowed.reads_only(("work", "land"))
