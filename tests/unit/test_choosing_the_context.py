"""What the next question is about: everything, or exactly what you clicked.

"Вот есть карточки на верстаке — по умолчанию они все участвуют в контексте вопроса. Если я один
раз кликаю на карточку ЛКМ, она начинает светиться и только она будет участвовать в следующем
запросе; повторный клик убирает её из запроса. Кликать можно на сколько угодно карточек. На
миникарте так же отображаются выбранные элементы. Нужен инструмент, с помощью которого можно
выделить сразу область."

The default matters as much as the gesture. A card is on the bench because somebody put it there,
and making them confirm each one would be asking twice — so everything is carried until something
is chosen, and choosing nothing is back to everything. The gesture has no state to get stuck in.
"""

from __future__ import annotations

import pathlib

import pytest

pytestmark = pytest.mark.unit

HERE = pathlib.Path(__file__).resolve().parents[2]
CONSOLE = HERE / "agent_desk" / "web" / "static" / "console.js"
CSS = HERE / "agent_desk" / "web" / "static" / "console.css"
BOARD = HERE / "agent_desk" / "web" / "templates" / "board.html"


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


# --- the gesture ------------------------------------------------------------------------------------
def test_a_click_under_the_choose_tool_chooses_the_card() -> None:
    """Under Choose and not under Move. A click that sometimes opens a card and sometimes changes
    what the next question is about is a click nobody can predict; the tool strip is what makes the
    difference visible before the press rather than after it."""
    source = _code()
    start = source.index("document.addEventListener('click', (event) => {\n  const holder")
    body = source[start : source.index("\n});", start)]

    assert "if (tool !== 'choose') return;" in body
    assert "holder.classList.toggle('chosen')" in body
    assert "showChosen()" in body


def test_the_choose_tool_does_not_drag_a_card() -> None:
    """ "Вкл-выкл курсор — не перетягивает карточки, а просто их включает и выключает." A tool whose
    whole promise is that a press does one thing has to not also do the other one."""
    assert "if (tool === 'choose' && pin) return;" in _code()


def test_there_are_three_tools_and_each_says_its_name_and_its_key() -> None:
    """The arrangement every drawing program has had for thirty years, and people arrive already
    knowing it. What it buys is that "what happens if I click" is answered before the click."""
    markup = BOARD.read_text(encoding="utf-8")

    for name, key in (("Move", "V"), ("Choose", "C"), ("Choose an area", "G")):
        assert f"{name} —" in markup, name
        assert f"({key})" in markup, key
    assert 'role="toolbar"' in markup
    assert "aria-pressed" in markup, "which tool is in use is a colour and not a fact"


def test_the_tool_can_be_reached_from_the_keyboard() -> None:
    source = _code()

    assert "TOOL_KEYS" in source
    assert "v: 'move'" in source and "c: 'choose'" in source and "g: 'area'" in source


def test_escape_goes_back_to_move() -> None:
    """The way out somebody reaches for without being told."""
    assert "useTool('move')" in _code()


def test_a_press_that_will_draw_a_box_does_not_also_pan() -> None:
    """Both handlers are on the canvas and both used to run: the surface slid away under the band
    while it was being drawn, so the box was measured against one frame and the cards against
    another, and it caught nothing."""
    assert "!(event.shiftKey || tool === 'area')" in _code()


def test_clicking_again_takes_it_back_out() -> None:
    """`toggle` is the whole of it, and it is worth asserting because the alternative — add on
    click, remove on some other gesture — is what makes a selection something people fight."""
    source = _code()
    start = source.index("document.addEventListener('click', (event) => {\n  const holder")
    body = source[start : source.index("\n});", start)]

    assert "classList.add('chosen')" not in body


def test_choosing_nothing_is_back_to_everything() -> None:
    """Which is what makes the gesture safe: there is no state it can be stuck in."""
    picking = _body("pinnedTargets")

    assert "chosen.length" in picking
    assert "? chosen" in picking or "chosen\n" in picking


def test_a_drag_is_not_a_click() -> None:
    """Moving cards about is what somebody does all day here, and before this a drag by the head
    also toggled the card."""
    source = _code()

    assert "justDragged = true" in source
    start = source.index("document.addEventListener('click', (event) => {\n  const holder")
    body = source[start : source.index("\n});", start)]
    assert "if (justDragged) {" in body


def test_leaving_one_card_out_is_a_different_control() -> None:
    """The other direction — everything except this one — is still wanted, and two sentences on one
    gesture is what makes a control ambiguous. It is the dot on the head, which already said so in
    its title and is now big enough to read as a control."""
    source = _code()
    start = source.index("document.addEventListener('click', (event) => {\n  const holder")
    body = source[start : source.index("\n});", start)]

    assert "event.target.closest('.pin-live')" in body
    assert "classList.toggle('spent')" in body


# --- and what it looks like ---------------------------------------------------------------------------
def test_the_map_is_redrawn_when_the_choice_changes() -> None:
    """On a bench too big for its window the map is where "what is chosen" is answerable at all,
    and the selection changes far more often than the view does."""
    assert "drawMap()" in _body("showChosen")


def test_the_state_is_said_three_ways_and_none_of_them_is_only_colour() -> None:
    css = CSS.read_text(encoding="utf-8")
    source = _code()

    assert ".pin.chosen .pin-kind::before" in css, "a chosen card does not say so in words"
    assert ".pin.left-out" in css, "the ones being left out are not dimmed"
    assert "asking about" in source, "the strip does not say what is being carried"


def test_the_chosen_are_marked_on_the_map() -> None:
    css = CSS.read_text(encoding="utf-8")
    source = _code()

    assert ".map-dot.chosen" in css
    assert "classList.contains('chosen') ? ' chosen'" in source


# --- the area tool -------------------------------------------------------------------------------------
def test_there_is_a_control_for_it_and_not_only_a_modifier() -> None:
    """A gesture with no control is a gesture only the person who wrote it knows about."""
    assert 'data-tool="area"' in BOARD.read_text(encoding="utf-8")
    assert "function useTool(" in _code()


def test_shift_and_drag_still_works() -> None:
    """Taking away a gesture somebody already has in their hands to add a button would be a bad
    trade."""
    assert "event.shiftKey || tool === 'area'" in _code()


def test_a_plain_drag_still_pans() -> None:
    assert "!(event.shiftKey || tool === 'area')) return;" in _code()


def test_the_tool_stays_chosen_until_another_is() -> None:
    """A tool that put itself down after one use would be a tool nobody could use twice, and every
    drawing program works the other way."""
    assert "armTheBand" not in _code()


def test_touching_a_card_is_enough_to_choose_it() -> None:
    """A band you have to draw right around a card is a band you draw twice."""
    assert "spot.x < at.right" in _body("endBand")


# --- and the control that was lying ----------------------------------------------------------------------
def test_carry_nothing_stops_carrying_rather_than_emptying_the_workbench() -> None:
    """It called `clearBench`, which takes every card off. A person who wanted to ask one question
    without the bench attached lost the bench — two controls doing the same destructive thing, one
    of them labelled as if it were about the message."""
    source = _code()
    start = source.index("document.getElementById('clear-context')")
    body = source[start : source.index("\n});", start)]

    assert "clearBench" not in body
    assert "classList.add('spent')" in body
    assert "chooseNone()" in body


def test_taking_everything_off_is_still_offered_where_it_says_so() -> None:
    assert 'data-add="clear"' in BOARD.read_text(encoding="utf-8")
    assert "Take everything off" in BOARD.read_text(encoding="utf-8")
