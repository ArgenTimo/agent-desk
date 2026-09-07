"""A request that changes the cards in front of somebody (01M1XA7Q9QEP… and its children).

"Отличие от всего предыдущего в одном: результат запроса — это не новая карточка и не текст, а
**изменение того, что уже лежит**."

The branch is deliberately the cheapest one in the pool — nothing is started, nothing is written
into anybody's repository, nothing costs more than one model call — and it stays cheap by not being
able to do the expensive things. That is why guessing is allowed here where it is not elsewhere: an
arrangement nobody wanted is one press of undo away.
"""

from __future__ import annotations

import pathlib

import pytest
from agent_desk import handling
from agent_desk.answer import classify

BENCH = ["idea:a", "idea:b", "idea:c", "idea:d"]
CONSOLE = (
    pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "static" / "console.js"
)


# --- a fixed list of actions ---------------------------------------------------------------------
@pytest.mark.unit
def test_the_actions_are_a_closed_list() -> None:
    """ "Свободная формулировка «расположи покрасивее» не исполнима, и разбор её ответа превратится
    в угадайку." The same argument that gives roles five names and lines five."""
    said = handling.what_to_do(BENCH)

    assert "mark" in said and "sort" in said and "clear" in said
    assert handling.SIDES == ("left", "middle", "right")


@pytest.mark.unit
def test_nothing_here_can_take_a_card_off_or_start_anything() -> None:
    """What keeps this the cheap branch. An arrangement somebody did not want is one press of undo
    away; a card somebody did not want removed is not, and a run somebody did not want started
    costs money and a worktree."""
    said = handling.what_to_do(BENCH).lower()

    for dangerous in ("remove", "delete", "run ", "start", "join", "send"):
        assert dangerous not in said, f"the actions offered include {dangerous!r}"


# --- reading the answer --------------------------------------------------------------------------
@pytest.mark.unit
def test_marks_carry_their_reason_onto_every_card_in_the_group() -> None:
    """ "Модель… выносит суждение. По правилам этого проекта суждение показывается как суждение и
    рядом с основанием." The answer is "these two, because X", and each of the two has to say X."""
    said = handling.read("mark 1,3 — both could be sold on their own", BENCH)

    assert [(one.name, one.why) for one in said.marked] == [
        ("idea:a", "both could be sold on their own"),
        ("idea:c", "both could be sold on their own"),
    ]


@pytest.mark.unit
def test_the_whole_list_of_numbers_is_read_and_not_just_the_first() -> None:
    """Written lazily, the first digit satisfied the pattern and "mark 1,3 because…" was read as
    card 1 with the reason ",3 because…" — one card marked out of two, and a reason that begins
    with a comma."""
    said = handling.read("mark 1, 2, 4 all three of these", BENCH)

    assert [one.name for one in said.marked] == ["idea:a", "idea:b", "idea:d"]


@pytest.mark.unit
def test_a_sort_names_a_side_and_what_the_cards_there_have_in_common() -> None:
    """ "Колонкам нужны заголовки, иначе через минуту непонятно, что слева, а что справа.\" """
    said = handling.read("sort left 2,3 the developer-facing ones", BENCH)

    (side,) = said.sorted_
    assert (side.side, side.names, side.what) == (
        "left",
        ["idea:b", "idea:c"],
        "the developer-facing ones",
    )


@pytest.mark.unit
def test_the_punctuation_between_the_numbers_and_the_words_is_not_load_bearing() -> None:
    """A model writes a dash, a colon, or neither, and refusing the reason over the punctuation in
    front of it would throw away the half that matters."""
    for said in ("mark 1 — why", "mark 1: why", "mark 1 why", "mark 1 - why"):
        assert handling.read(said, BENCH).marked[0].why == "why", said


@pytest.mark.unit
def test_a_paragraph_about_the_cards_rearranges_nothing() -> None:
    """A model asked for actions will sometimes answer with a paragraph about the actions, and a
    reader that accepted anything would rearrange a bench from a sentence nobody meant as an
    instruction. The same rule `telling.read_shape` follows."""
    assert handling.read("I think cards 1 and 2 are the most promising here.", BENCH).empty


@pytest.mark.unit
def test_a_number_that_is_not_a_card_is_dropped_rather_than_raised_on() -> None:
    """A model that counted past the end has named nothing; losing that number beats losing the
    line it was in."""
    said = handling.read("mark 2,9 one of these exists", BENCH)

    assert [one.name for one in said.marked] == ["idea:b"]
    assert handling.read("mark 9 nothing there", BENCH).empty


@pytest.mark.unit
def test_the_same_card_twice_in_one_action_is_one_card() -> None:
    assert len(handling.read("mark 1,1,1 said three times", BENCH).marked) == 1


@pytest.mark.unit
def test_a_reason_is_a_line_rather_than_a_paragraph() -> None:
    """It sits on a card under its label. A judgement nobody can read at a glance is a judgement
    nobody checks."""
    said = handling.read(f"mark 1 {'x' * 400}", BENCH)

    assert len(said.marked[0].why) == handling.WHY_CHARS


# --- what the block keeps ------------------------------------------------------------------------
@pytest.mark.unit
def test_the_actions_survive_the_round_trip_through_the_block() -> None:
    """Stored as names rather than as the numbers the model wrote: the numbers only mean anything
    beside the digest that produced them, and a bench that has changed since would apply them to
    the wrong cards. A name that is no longer there is simply not found."""
    said = handling.read("mark 1,2 both\nsort right 4 the other one\nclear", BENCH)

    back = handling.read_json(handling.as_json(said))

    assert [one.name for one in back.marked] == ["idea:a", "idea:b"]
    assert back.sorted_[0].names == ["idea:d"]
    assert back.clear is True


@pytest.mark.unit
def test_a_block_that_stored_something_else_reads_as_nothing() -> None:
    """An older block, a failed run, a hand-edited row: none of them rearrange anything."""
    for said in ("", "an ordinary answer", "{}", "[1, 2]", '{"handling": null}'):
        assert handling.read_json(said).empty, said


@pytest.mark.unit
def test_what_was_done_is_also_said_in_words() -> None:
    """A block whose answer is a blob says nothing to somebody scrolling back through what they
    asked. One line per reason, not per card — the answer is "these two, because X", and a bench
    reciting X twice is what somebody then has to read twice."""
    said = handling.read("mark 1,2 both could be sold\nsort left 3 the developer one", BENCH)

    words = handling.as_words(said)

    assert "2 cards: both could be sold" in words
    assert "left: 1 card — the developer one" in words


# --- and only when that is what was asked for ----------------------------------------------------
@pytest.mark.unit
def test_arranging_is_its_own_kind_of_request() -> None:
    """ "«Подсвети те из них…» — это действие над верстаком. «Что из этого принесёт доход?» — это
    вопрос, и на него надо отвечать текстом.\" """
    assert classify.read_kind("arrange") == "handling"
    assert classify.read_kind("question") == "question"


@pytest.mark.unit
def test_the_classifier_is_told_the_difference_and_told_it_needs_cards() -> None:
    """With an empty workbench the same words are a question: there is nothing to arrange."""
    said = classify.kind_prompt("подсвети те, которые принесут доход", pointed_at=3)

    assert "arrange" in said
    assert "only when there are cards on the workbench" in said


@pytest.mark.unit
def test_a_rearrangement_is_applied_once() -> None:
    """`syncBlocks` runs on every push. Applied again every two seconds, a rearrangement would drag
    a card back from wherever somebody moved it to afterwards."""
    console = CONSOLE.read_text(encoding="utf-8")

    assert "const arranged = new Set();" in console
    assert "arranged.has(id)" in console and "arranged.add(id)" in console


@pytest.mark.unit
def test_a_card_an_answer_moved_counts_as_placed() -> None:
    """Somebody asked for that arrangement, so the console's own layout must not sweep it away the
    moment a card grows to fit its body (042-placed-by-hand.sql)."""
    console = CONSOLE.read_text(encoding="utf-8")
    applying = console[console.index("function applyArrangement(") :]
    applying = applying[: applying.index("\n}\n")]

    assert "dataset.moved = 'yes'" in applying
    assert "moveWasDeliberate()" in applying, "the arrangement cannot be undone in one press"


@pytest.mark.unit
def test_the_mark_is_not_one_of_the_two_a_card_already_has() -> None:
    """ "Отметка эта — третья по счёту (есть «в контексте» и «выполняется сейчас»), и она обязана
    отличаться от обеих: это ответ на вопрос, а не состояние карточки.\" """
    css = (
        pathlib.Path(__file__).resolve().parents[2]
        / "agent_desk"
        / "web"
        / "static"
        / "console.css"
    ).read_text(encoding="utf-8")

    assert ".pin.marked" in css and ".pin-why" in css
    assert ".pin.spent" in css, "the two it has to differ from are gone, so this test proves less"
