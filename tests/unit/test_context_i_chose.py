"""Three things a card can be, said three different ways (01M1X8DA6BPQ… and its children).

"Щёлкать мышкой по карточкам подключая их к контексту… после чего мои запросы обрабатываются
только с тем контекстом что я выбрал."

"Я хочу чтобы те блоки что сейчас выполняются как-то явно подсвечивались на верстаке и были отличны
от блоков которые подсвечиваются как участвующие в контексте запросов… Нужны две непохожие формы, а
не два оттенка одного."

A card can be going into the next message, left out of it because somebody chose others, or being
worked on right now. Two of those looked identical and one was invisible.
"""

from __future__ import annotations

import pathlib

import pytest

STATIC = pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "static"


def _css() -> str:
    return (STATIC / "console.css").read_text(encoding="utf-8")


def _code() -> str:
    return "\n".join(
        line
        for line in (STATIC / "console.js").read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("//")
    )


# --- only these ----------------------------------------------------------------------------------
@pytest.mark.unit
def test_choosing_some_cards_sends_only_those() -> None:
    """ "Сейчас чтобы отправить запрос про три карточки, надо потушить двадцать семь." The
    mechanism: when anything is chosen, it is what travels."""
    code = _code()
    # Where the set is decided, rather than where it is spelled out as targets: one reading answers
    # both "what will be sent" and "how many", and a rule asserted against the speller would go
    # unchecked the moment a second caller appeared.
    carried = code[code.index("function cardsBeingCarried(") :]
    carried = carried[: carried.index("\n}\n")]
    targets = code[code.index("function pinnedTargets(") :]
    targets = targets[: targets.index("\n}\n")]

    assert "chosenCards()" in carried
    assert "chosen.length" in carried, "a choice no longer decides what is carried"
    assert "cardsBeingCarried()" in targets


@pytest.mark.unit
def test_and_the_ones_left_out_look_left_out() -> None:
    """The half that was missing: thirty cards looked identical whether three were chosen or
    none were, so "only these" was true and invisible."""
    code = _code()
    syncing = code[code.index("function syncTargets(") :]
    syncing = syncing[: syncing.index("\n}\n")]

    assert "'left-out'" in syncing
    assert "picked > 0 && !pin.classList.contains('chosen')" in syncing
    assert ".pin.left-out" in _css()


@pytest.mark.unit
def test_nothing_is_left_out_when_nothing_is_chosen() -> None:
    """Otherwise a bench with no choice on it would render as a bench where everything is
    excluded, which is the opposite of what it means."""
    code = _code()
    syncing = code[code.index("function syncTargets(") :]
    syncing = syncing[: syncing.index("\n}\n")]

    assert "picked > 0 &&" in syncing, "the mark does not depend on anything being chosen"


# --- and what is running is not what is carried --------------------------------------------------
@pytest.mark.unit
def test_where_a_run_is_and_what_is_chosen_are_not_the_same_colour() -> None:
    """The one thing this pair was still getting wrong.

    "Нужны две непохожие формы, а не два оттенка одного" was already answered for *working*: a card
    an agent is on is filled with moving stripes and a card in the message has a dot, which
    `test_static.py` has asserted for weeks. Adding a second answer broke the first one.

    What was not answered is `at-now` — where the run has reached. It was `--focus`, which is also
    what a chosen card is outlined in, so a run arriving at a card somebody had chosen drew two
    marks of the same colour in the same place.
    """
    css = _css()

    at_now = css[css.index(".pin.at-now {") :]
    at_now = at_now[: at_now.index("}")]
    assert "var(--attention)" in at_now
    assert "var(--focus)" not in at_now

    chosen = css[css.index(".pin.chosen { outline") :]
    chosen = chosen[: chosen.index("}")]
    assert "var(--focus)" in chosen


# --- and what the console decided it was (01M1X8DA8C6C…) -----------------------------------------
@pytest.mark.unit
def test_a_message_says_what_it_was_taken_as() -> None:
    """ "Если консоль решила, что это «сделай проект», человек должен это увидеть и успеть сказать
    «нет, это был вопрос»."

    The decision was recorded before anything expensive started — `set_block_kind` runs before
    `_start_work` — and nobody was told, because a block carried its kind as a class on its
    article, which is a fact about the markup rather than a sentence for a person.
    """
    from agent_desk import telling

    assert telling.taken_as("master") == "taken as a job for this console itself"
    assert telling.taken_as("instruction") == "taken as an instruction for an agent"
    assert telling.taken_as("handling") == "taken as a change to the workbench"


@pytest.mark.unit
def test_nothing_is_said_about_an_ordinary_question() -> None:
    """It is what an unread line is taken to be and what most lines are. A sentence printed on
    every message is one people learn to skip — and this one earns its place only by appearing
    when something less obvious was decided."""
    from agent_desk import telling

    assert telling.taken_as("question") == ""
    assert telling.taken_as("") == ""


@pytest.mark.unit
def test_it_is_shown_beside_what_was_typed_and_above_the_answer() -> None:
    """Read before the result rather than after it, which is the whole of "успеть сказать нет"."""
    said = (
        pathlib.Path(__file__).resolve().parents[2]
        / "agent_desk"
        / "web"
        / "templates"
        / "_blocks.html"
    ).read_text(encoding="utf-8")

    assert 'class="taken-as"' in said
    assert said.index('class="taken-as"') < said.index('class="answer'), (
        "what it was taken as is shown after the answer, which is too late to correct"
    )


@pytest.mark.unit
def test_the_corrections_are_still_there_to_reach_for() -> None:
    """The sentence is only worth printing because there is something to do about it."""
    said = (
        pathlib.Path(__file__).resolve().parents[2]
        / "agent_desk"
        / "web"
        / "templates"
        / "_blocks.html"
    ).read_text(encoding="utf-8")

    assert "record as an idea" in said
    assert "answer it instead" in said
