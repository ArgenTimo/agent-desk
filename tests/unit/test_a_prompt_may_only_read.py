"""A step that sends a prompt may only read, and that cannot be switched off
(01M1X8DA8XDSQ16N5DVDVZGM5X).

"Шаг-промпт по определению имеет право только читать: ни ветки, ни гейта, ни пуша. Это уже
выражается разрешениями (agent_desk/allowed.py) — нужно, чтобы для этой роли оно было не настройкой
по умолчанию, а тем, что нельзя выключить."

The difference between a default and a rule is the whole idea. A default is the switch's starting
position and somebody can move it. A prompt step that could be given a worktree and a push is not a
pipeline step configured safely — it is an agent with a prompt in its briefing, which this console
already has and calls something else.
"""

from __future__ import annotations

import ast
import pathlib

import pytest
from agent_desk import allowed

pytestmark = pytest.mark.unit

HERE = pathlib.Path(__file__).resolve().parents[2]
ENGINE = HERE / "agent_desk" / "web" / "engine.py"
ROUTES = HERE / "agent_desk" / "web" / "routes.py"
CONSOLE = HERE / "agent_desk" / "web" / "static" / "console.js"


# --- what it is ------------------------------------------------------------------------------------
def test_a_prompt_step_may_read_and_nothing_else() -> None:
    assert allowed.leave_for_a_prompt() == ("read",)
    assert allowed.reads_only(allowed.leave_for_a_prompt())


def test_it_is_not_the_default_that_a_step_starts_at() -> None:
    """The default is `work` — its own copy — and it is a default precisely because somebody can
    change it. This is a different thing wearing the same word."""
    assert allowed.NATURALLY != allowed.ISOLATED


def test_it_is_not_read_from_anywhere_a_person_could_edit() -> None:
    """There would be nowhere to write it down that somebody could not then change, which is what
    "cannot be switched off" rules out."""
    tree = ast.parse((HERE / "agent_desk" / "allowed.py").read_text(encoding="utf-8"))
    fixed = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "leave_for_a_prompt"
    )

    assert not [node for node in ast.walk(fixed) if isinstance(node, ast.arg)]


def test_whether_a_card_is_a_prompt_has_one_reader() -> None:
    """Two would eventually disagree, and the direction they would disagree in is a prompt step
    running with a worktree."""
    assert allowed.is_a_prompt({"asks": "summarise it"})
    assert not allowed.is_a_prompt({"asks": "   "})
    assert not allowed.is_a_prompt({"do": "write the migration"})
    assert not allowed.is_a_prompt({})


# --- and where it is enforced -------------------------------------------------------------------------
def test_the_engine_decides_from_what_the_card_is_not_from_the_switches() -> None:
    source = ENGINE.read_text(encoding="utf-8")

    assert "allowed.leave_for_a_prompt()" in source
    assert "if allowed.is_a_prompt(card.said)" in source


def test_the_page_is_told_what_the_run_will_use() -> None:
    """Not what the switches stand at. The same function decides in both places, so the console
    cannot show a permission the run will ignore."""
    source = ROUTES.read_text(encoding="utf-8")

    assert "allowed.leave_for_a_prompt()" in source
    assert '"fixed": [' in source


def test_the_switches_are_not_offered_at_all_for_one() -> None:
    """A control that can be moved and then disregarded is a promise the console does not keep, so
    it says what the step is instead of offering a choice it will overrule."""
    source = "\n".join(
        line
        for line in CONSOLE.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("//")
    )
    start = source.index("function showLeaveMenu(")
    body = source[start : source.index("\n}\n", start)]
    offered = body.index("processSaid.allowed")
    fixed = body.index("(processSaid.fixed || []).includes(name)")

    assert fixed < offered, "the switches are built before the fixed case returns"
    assert "may only read" in body
