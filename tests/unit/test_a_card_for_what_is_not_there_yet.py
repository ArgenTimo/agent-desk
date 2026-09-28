"""A card standing where a thing is going to be (01M1X8DA7SPGJS4WWN3TCYB977).

"На верстаке появляются блоки что уже готово, а также неактивные/бледные блоки что сейчас в
процессе, возможно заштрихованные с шестерёнками."

The half of that which already existed is the ring a group turns while its work runs. The half that
did not is a card standing where a thing is *going to be*, and the whole difficulty is that it must
not be mistaken for a card standing where a thing is: a console that draws what is not there yet
the way it draws what is there reports an inference as a fact (CLAUDE.md, rule five).
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


def _rules(selector: str) -> str:
    css = "\n".join(
        line
        for line in CSS.read_text(encoding="utf-8").splitlines()
        if not line.strip().startswith("/*")
    )
    return "\n".join(one for one in css.split("\n\n") if selector in one)


# --- it cannot be mistaken for a fact ---------------------------------------------------------------
def test_it_says_it_is_a_promise_where_every_other_card_says_what_it_is() -> None:
    """Colour alone is not a distinction: it is invisible to a screen reader, to a person who is
    colour-blind, and in a screenshot pasted into a chat."""
    assert '<span class="pin-kind">promised</span>' in _body("promiseFor")


def test_it_says_in_words_that_nothing_is_there() -> None:
    assert "Nothing is here yet." in _body("promiseFor")


def test_it_is_drawn_differently_and_not_only_more_faintly() -> None:
    rules = _rules(".pin.promise")

    assert "border-style: dashed" in rules
    assert "repeating-linear-gradient" in rules


def test_the_turning_thing_stops_for_somebody_who_asked_for_that() -> None:
    """The dashed border and the word carry the meaning; the spin never did."""
    css = CSS.read_text(encoding="utf-8")

    assert "prefers-reduced-motion: reduce" in css
    assert ".pin.promise .pin-kind::after { animation: none; }" in css


# --- and it is not a thing --------------------------------------------------------------------------
def test_it_carries_nothing_into_the_next_message() -> None:
    """There is nothing to carry. A card that said it was being sent, about a thing that does not
    exist, would be the console lying twice.

    Asserted where the set is gathered rather than where it is spelled out as targets: the count
    under the bench and the names in the field are one reading now, so the rule is stated once and
    both of them get it.
    """
    assert ":not(.promise)" in _body("cardsBeingCarried")
    assert "cardsBeingCarried()" in _body("pinnedTargets")


def test_it_is_not_counted_among_the_cards_being_carried() -> None:
    """The same one reading. A promise excluded from the message and counted in the sentence under
    it would be the console contradicting itself in two adjacent elements."""
    assert "cardsBeingCarried()" in _body("syncTargets")


def test_it_is_never_written_down() -> None:
    """Written down, it would come back on the next load as a card about nothing, over a run that
    finished hours ago."""
    assert "pin.dataset.kind !== 'promise'" in _body("benchState")


# --- when it appears, and when it goes ---------------------------------------------------------------
def test_only_the_kinds_that_make_cards_promise_anything() -> None:
    """A question makes an answer, and the answer card already says it is coming. A promise beside
    it would be two cards for one thing."""
    source = _code()
    start = source.index("const PROMISES = {")
    listed = source[start : source.index("};", start)]

    assert "drawing:" in listed
    assert "showing:" in listed
    assert "question:" not in listed
    assert "handling:" not in listed


def test_it_appears_while_the_run_is_going() -> None:
    syncing = _body("syncBlocks")

    assert (
        "if (promising && !article.hasAttribute('data-settled')) promiseFor(id, promising)"
        in syncing
    )


def test_it_goes_when_the_run_settles_however_it_settled() -> None:
    """A promise left standing over a failed run is the console saying a thing is coming that is
    not."""
    syncing = _body("syncBlocks")

    assert "else keptThePromise(id)" in syncing
    assert "settled" in _body("keptThePromise") or "remove()" in _body("keptThePromise")


def test_one_promise_per_message() -> None:
    assert '`.pin[data-name="${CSS.escape(name)}"]`' in _body("promiseFor")


def test_it_stands_under_the_message_that_is_making_it() -> None:
    assert "spotUnder([`block:${id}`])" in _body("promiseFor")
