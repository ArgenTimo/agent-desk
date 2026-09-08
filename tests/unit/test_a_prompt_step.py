"""A step whose work is a prompt (01M1X8DA8REGR836D77PPV3W54).

"Строить и тестировать на верстаке разные LLM-пайплайны, условно разные промпты с разными входами
выходами развилками и прочим… Не хватает роли, у которой поля — это промпт и форма ответа, и
которая не претендует ни на репозиторий, ни на воркдир."

Not a sixth role. adr/0011 closed the five and 049 already answered this shape of question: an
Action is "something to do", asking a model is something to do, and what differs is what it does
the work with. So it is a field — and an alternative one, filled instead of the ordinary work
rather than beside it, which is what keeps the form the size it was.
"""

from __future__ import annotations

import pathlib

import pytest
from agent_desk import process, roles
from agent_desk.web import engine

pytestmark = pytest.mark.unit


def _card(**said: str) -> process.Card:
    return process.Card(name="step:1", role="action", label="ask it", said=said)


# --- the field ------------------------------------------------------------------------------------
def test_an_action_can_be_a_prompt() -> None:
    assert "asks" in {field.name for field in roles.fields_of("action")}


def test_it_is_filled_instead_of_the_work_and_not_beside_it() -> None:
    """A step is work in a repository, or a saved process, or a prompt, and no card is ever more
    than one of them."""
    instead = {field.name for field in roles.alternatives("action")}

    assert instead == {"runs", "asks"}
    assert {field.name for field in roles.asked_together("action")} == {"do", "using"}


def test_the_form_somebody_faces_is_the_size_it_was() -> None:
    """Three fields is a form somebody fills in; six is a form somebody abandons. The alternatives
    do not add to it because choosing one replaces the rest."""
    assert len(roles.asked_together("action")) <= 3


def test_a_step_is_not_incomplete_for_having_no_prompt() -> None:
    """`missing` flags what an engine would have to stop on. Not being a pipeline is not that."""
    assert "a prompt it sends" not in roles.missing("action", {"do": "write it"})


def test_there_is_no_second_box_for_the_shape_of_the_answer() -> None:
    """Anybody writing a prompt says "answer with one line" inside it, and a second box for that is
    a second place for the same sentence to be — wrong the first time they disagree."""
    assert "replies" not in {field.name for field in roles.fields_of("action")}


# --- what gets sent -------------------------------------------------------------------------------
def test_the_prompt_is_sent_as_it_was_written() -> None:
    """It is the thing being tested, and anything above it is something else being tested."""
    said = engine._asking(_card(asks="Summarise this in one line."), "", [])

    assert said.startswith("Summarise this in one line.")


def test_what_the_steps_before_it_produced_comes_after() -> None:
    """A pipeline is steps that feed each other, and a step that could not see the last answer is
    a step in a different pipeline."""
    said = engine._asking(_card(asks="Now rewrite it."), "", ["ask it: the first draft"])

    assert said.index("Now rewrite it.") < said.index("the first draft")


def test_a_step_with_no_prompt_is_not_one_of_these() -> None:
    assert engine._asking(_card(do="write the migration"), "", []) == ""


def test_a_prompt_step_is_not_given_the_briefing_about_the_diagram() -> None:
    """The briefing turns a drawn process into instructions for an agent. A pipeline step is the
    prompt somebody is testing, and wrapping it in a paragraph about the diagram tests something
    else."""
    source = (
        pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "engine.py"
    ).read_text(encoding="utf-8")

    assert "_asking(card, run.given, await _what_is_known(store, run), cards, lines)" in source


def test_a_step_that_chose_an_alternative_is_missing_nothing() -> None:
    """The alternative replaces the ordinary work rather than joining it, so asking such a step
    what work it does is asking it to be two kinds of step at once. Without this every step from
    049 and every pipeline step reads as half-drawn and `ready_to_run` refuses to start it."""
    assert roles.missing("action", {"asks": "summarise it"}) == ()
    assert roles.missing("action", {"runs": "release"}) == ()
    assert roles.missing("action", {}) == ("what to do",)
