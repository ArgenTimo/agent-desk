"""Understood, shown, then answered (01M1XA1V7BP9GFX0E6YQKYAYGK).

"Как только система поймёт, к чему относится вопрос, он центрируется на этот блок, подсвечивает
его, рисует связь к карточке вопроса и готовит ответ."

The order in that sentence is its content. A person who can see which card their question was
taken to be about has time to say "no, not that one" before an answer to the wrong question
arrives; after it, the same information is a post-mortem.
"""

from __future__ import annotations

import pathlib

import pytest

pytestmark = pytest.mark.unit

HERE = pathlib.Path(__file__).resolve().parents[2]
CONSOLE = HERE / "agent_desk" / "web" / "static" / "console.js"
CSS = HERE / "agent_desk" / "web" / "static" / "console.css"


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


def test_it_lights_the_card_and_brings_it_into_view() -> None:
    saying = _body("sayWhatItIsAbout")
    assert "classList.add('about-this')" in saying
    assert "bringIntoView(pin)" in saying


def test_a_card_already_on_the_screen_is_not_chased() -> None:
    """Somebody who has panned to a corner on purpose is looking at something, and a console that
    drags the surface out from under them every time it works something out is one they stop
    asking questions on."""
    assert "if (!onTheScreen(pin)) bringIntoView(pin)" in _body("sayWhatItIsAbout")


def test_the_understanding_is_shown_before_the_line_is_drawn() -> None:
    """Both are ahead of the answer, and between the two the card comes first: the line explains
    the card, and a line to a card nobody has looked at yet explains nothing."""
    syncing = _body("syncBlocks")
    assert syncing.index("sayWhatItIsAbout(onto)") < syncing.index("says: 'follows on from'")


def test_a_settled_question_is_neither_lit_nor_chased() -> None:
    """A conversation the page is seeing for the first time — a reload, a chat switched back to —
    is all settled blocks, and lighting each in turn would drag the surface across a dozen old
    answers before coming to rest."""
    syncing = _body("syncBlocks")
    assert "if (!article.hasAttribute('data-settled')) sayWhatItIsAbout(onto)" in syncing


def test_the_light_goes_out_when_the_answer_arrives() -> None:
    """A card still lit under a finished answer says the console is still working out what the
    question was about."""
    syncing = _body("syncBlocks")
    assert "article.hasAttribute('data-settled')) onto.classList.remove('about-this')" in syncing


def test_the_line_is_still_drawn_for_a_question_that_is_already_answered() -> None:
    """The highlight is about a moment; the line is a fact about the enquiry and outlives it."""
    syncing = _body("syncBlocks")
    tie = syncing.index("says: 'follows on from'")
    guard = syncing.index("if (!article.hasAttribute('data-settled')) sayWhatItIsAbout(onto)")
    # The guard covers one statement, and the line is pushed after it rather than inside it.
    assert guard < tie
    assert "sayWhatItIsAbout(onto);\n      ownTies.push(" in syncing


def test_being_on_the_screen_is_worked_out_and_not_measured() -> None:
    """`markOffEdge` cost 19ms a frame on 35 cards until it stopped asking the browser. A second
    reader of the same question must not put that back."""
    looking = _body("onTheScreen")
    assert "getBoundingClientRect" not in looking.replace("canvas?.getBoundingClientRect()", ""), (
        "the frame is one measurement; a card's place is arithmetic"
    )
    assert "view.x + at.x * view.scale" in looking


def test_there_is_one_copy_of_the_centring_arithmetic() -> None:
    """The dots that reach a card off the edge and the console saying what it understood are two
    callers of one sum. Two copies is a second place to be wrong, silently."""
    assert _code().count("frame.width / 2 - (at.x + CARD_WIDTH / 2) * view.scale") == 1
    assert "dot.addEventListener('click', () => bringIntoView(one.pin))" in _code()


def test_the_mark_is_not_the_same_as_being_chosen_or_being_the_beginning() -> None:
    """Three marks that mean three different things — somebody picked this, this is where it all
    started, this is what the console understood — and states that look alike are states nobody can
    tell apart."""
    css = CSS.read_text(encoding="utf-8")
    assert ".pin.about-this {" in css
    assert ".pin.about-this .pin-kind::after" in css
    assert ".pin.beginning .pin-kind::before" in css
