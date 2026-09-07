"""Two holes in things that already worked (children of 01M1XC4Z1D2K…).

"Перечитаны закрытые идеи этой недели вместе с кодом, который их закрыл… Каждая из них работает;
ниже то, чего в них не хватает, чтобы ими можно было пользоваться дольше одного раза."

Both are the same shape of gap: an action that can be done and cannot be undone, or done in bulk
having been done once.
"""

from __future__ import annotations

import pathlib

import pytest

CONSOLE = (
    pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "static" / "console.js"
)


def _code() -> str:
    return "\n".join(
        line
        for line in CONSOLE.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("//")
    )


def _body(name: str) -> str:
    source = _code()
    start = source.index(f"function {name}(")
    return source[start : source.index("\n}\n", start)]


# --- every line at once (01M1XC4Z2Y4M…) ----------------------------------------------------------
@pytest.mark.unit
def test_a_card_s_lines_can_be_rubbed_out_together() -> None:
    """ "Когда карточка ошиблась ролью и обросла пятью неправильными связями, это пять нажатий и
    меню каждый раз.\" """
    assert "function rubOutLinesOf(" in _code()
    assert "rub out all ${linesOf(name).length} of its lines" in _code()


@pytest.mark.unit
def test_it_is_offered_only_when_there_is_more_than_one() -> None:
    """One line already has its own menu. A second way to do the same thing is a menu somebody has
    to choose between two identical entries in."""
    menu = _body("cardMenuFor")

    assert "linesOf(name).length > 1" in menu


@pytest.mark.unit
def test_only_the_lines_somebody_drew() -> None:
    """The ones this console works out for itself — which project a session is in, what a question
    went out with — are readings of facts, and rubbing one out would be rubbing out the fact. It
    is the rule the line's own menu already follows."""
    lines = _body("linesOf")

    assert "drawnTies" in lines
    assert "ownTies" not in lines, "the console's own readings are being offered for deletion"


@pytest.mark.unit
def test_only_the_lines_somebody_can_see() -> None:
    """A line is a statement about two cards rather than about a surface, so the same line shows on
    every bench holding both its ends — and a card here can be joined to a card on another chat's
    workbench.

    Measured in a browser: a card with two lines drawn on this bench offered to rub out three.
    Offering to remove something nobody can see is the mistake the undo had, and it is worse here
    because the count is on the button somebody is reading.
    """
    lines = _body("linesOf")

    assert "showing(line.from)" in lines and "showing(line.to)" in lines


# --- and a collection back into its cards (01M1XC4Z3697…) ----------------------------------------
@pytest.mark.unit
def test_a_collection_can_be_laid_back_out() -> None:
    """ "Группа, ушедшая в запрос, сворачивается в одну карточку — и разложить её обратно нельзя. А
    это ровно то, что захочется сделать, чтобы повторить вопрос с одной изменённой карточкой.\" """
    assert "async function layBackOut(" in _code()

    menu = _body("cardMenuFor")
    assert "classList.contains('collection')" in menu
    assert "lay it back out" in menu


@pytest.mark.unit
def test_the_collection_keeps_what_it_takes_to_put_a_card_back() -> None:
    """The row was a kind and a name, for reading. Putting a card back needs the same three things
    `pin` needs, so the list is the record *and* the way back rather than a description of one."""
    collecting = _body("collect")

    for field in ("row.dataset.kind", "row.dataset.id", "row.dataset.label"):
        assert field in collecting, f"a collected card does not record {field}"


@pytest.mark.unit
def test_a_card_already_on_the_bench_is_not_added_twice() -> None:
    """And the count says how many actually came back: "разложить обратно" over a bench that still
    has three of the five is two cards, and a message claiming five describes a different bench."""
    laying = _body("layBackOut")

    assert "if (surface.querySelector(" in laying and "continue" in laying
    assert "already on the workbench" in laying


@pytest.mark.unit
def test_the_cards_that_come_back_say_where_they_came_from() -> None:
    """045: a card on the bench answers "why is this here", and being laid back out of a group is
    one of the ways it can have got there."""
    assert "'laid back out of a group'" in _code()


# --- why the engine went that way (01M1XC4Z2F4C…) ------------------------------------------------
@pytest.mark.unit
def test_a_decision_records_what_decided_it() -> None:
    """ "Сейчас остаётся «пошёл туда-то». Не остаётся, на основании чего — а это ровно тот вопрос,
    который зададут, когда прогон пойдёт не туда.\" """
    from agent_desk.web import engine

    assert engine.read_branch("2 the tests came back red, so it cannot go out", 3) == 2
    assert engine.read_why("2 the tests came back red, so it cannot go out") == (
        "the tests came back red, so it cannot go out"
    )


@pytest.mark.unit
def test_the_number_still_has_to_come_first_and_alone() -> None:
    """Asking for a reason must not soften the reading of the branch. A process that took the
    first way out because the model said something conversational is the failure `read_branch`
    exists to refuse, and it refuses it exactly as before."""
    from agent_desk.web import engine

    assert engine.read_branch("I think option two", 3) == 0
    assert engine.read_branch("2 because", 1) == 0, "a number past the end is not a branch"


@pytest.mark.unit
def test_a_decision_with_no_reason_says_so_rather_than_inventing_one() -> None:
    """Absent is a real answer: it means the model did not give a reason, which is a different
    thing from a reason nobody wrote down. A made-up one beside a real branch would be
    indistinguishable from a real one — the worst possible place for a guess."""
    from agent_desk.web import engine

    assert engine.read_why("2") == ""
    assert engine.read_why("") == ""


@pytest.mark.unit
def test_the_reason_is_a_line_rather_than_an_essay() -> None:
    """It is read at a glance beside the branch it explains, on a card and in a run's history."""
    from agent_desk.web import engine

    assert len(engine.read_why("2 " + "x" * 500)) == engine.WHY_CHARS


@pytest.mark.unit
def test_the_prompt_asks_for_both_and_says_why_the_number_is_first() -> None:
    from agent_desk import process
    from agent_desk.web import engine

    card = process.Card(name="step:1", role="decision", label="ship it?", said={"ask": "ship?"})
    ways = [
        process.Line(from_name="step:1", to_name="step:2", kind="if", says="yes"),
        process.Line(from_name="step:1", to_name="step:3", kind="if", says="no"),
    ]

    said = engine.branch_prompt(card, ways)

    # The line wraps in the source, so the check is on the halves rather than on the join.
    assert "then a" in said and "few words saying what decided it" in said
    assert "why did it go that way" in said
