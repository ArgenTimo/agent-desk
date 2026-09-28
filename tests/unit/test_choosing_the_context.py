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

import html.parser
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


def test_only_move_moves_a_card() -> None:
    """ "Вкл-выкл курсор — не перетягивает карточки, а просто их включает и выключает." A tool whose
    whole promise is that a press does one thing has to not also do the other one — and stating it
    of Move rather than of Choose is what keeps the fourth tool from having to remember it too."""
    assert "if (tool !== 'move' && pin) return;" in _code()


def test_every_tool_says_its_name_and_its_key() -> None:
    """The arrangement every drawing program has had for thirty years, and people arrive already
    knowing it. What it buys is that "what happens if I click" is answered before the click."""
    markup = BOARD.read_text(encoding="utf-8")

    for name, key in (("Move", "V"), ("Choose", "C"), ("Choose an area", "G"), ("Combine", "X")):
        assert f"{name} —" in markup, name
        assert f"({key})" in markup, key
    assert 'role="toolbar"' in markup
    assert "aria-pressed" in markup, "which tool is in use is a colour and not a fact"


def test_the_tool_can_be_reached_from_the_keyboard() -> None:
    source = _code()

    assert "TOOL_KEYS" in source
    assert "v: 'move'" in source and "c: 'choose'" in source and "g: 'area'" in source
    assert "x: 'mix'" in source


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
    """Which is what makes the gesture safe: there is no state it can be stuck in.

    Asserted where the set is decided. The names in the field and the count under the bench are one
    reading now — `cardsBeingCarried` — so the fallback is stated once and both of them get it.
    """
    picking = _body("cardsBeingCarried")

    assert "chosen.length" in picking
    assert "? chosen" in picking or "chosen\n" in picking
    assert "cardsBeingCarried()" in _body("pinnedTargets")


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


# --- the strip is furniture floating over the bench --------------------------------------------
def _tool_buttons() -> dict[str, list[tuple[str, dict[str, str]]]]:
    """Each tool button by name, and the elements inside it. Parsed rather than matched, because
    what matters is that the three buttons hold the same shape — which a substring cannot say."""

    class Read(html.parser.HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.found: dict[str, list[tuple[str, dict[str, str]]]] = {}
            self.inside: str | None = None
            self.depth = 0

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            got = {name: value or "" for name, value in attrs}
            if tag == "button" and "data-tool" in got:
                self.inside = got["data-tool"]
                self.found[self.inside] = []
                self.depth = 0
                return
            if self.inside is None:
                return
            self.depth += 1
            if self.depth == 1:
                self.found[self.inside].append((tag, got))

        def handle_endtag(self, tag: str) -> None:
            if self.inside is None:
                return
            if tag == "button" and self.depth == 0:
                self.inside = None
            else:
                self.depth -= 1

    read = Read()
    read.feed(BOARD.read_text(encoding="utf-8"))
    return read.found


def test_every_tool_icon_is_drawn_in_the_same_box() -> None:
    """Three glyphs from three Unicode blocks are three fallback fonts with three sets of metrics,
    and the column came out visibly bent. A drawn icon has one box and one baseline."""
    buttons = _tool_buttons()

    assert set(buttons) == {"move", "choose", "area", "mix"}
    boxes = set()
    for name, inside in buttons.items():
        icons = [got for tag, got in inside if tag == "svg"]
        assert len(icons) == 1, f"{name} has no drawn icon"
        boxes.add(icons[0].get("viewBox"))
    assert len(boxes) == 1, f"the icons are drawn in different boxes: {boxes}"


def test_a_tool_button_is_all_icon_and_no_padding() -> None:
    """The shared `button` rule sets 11px at the sides. With `box-sizing: border-box` a 30px button
    then had six pixels of room for a sixteen-pixel icon, and an icon does not shrink: every one of
    them sat twelve pixels from the left edge and one from the right."""
    css = CSS.read_text(encoding="utf-8")
    start = css.index(".tools button {")
    rule = css[start : css.index("}", start)]

    assert "padding: 0" in rule, "the icons are pushed off centre by the padding buttons inherit"


def test_the_strip_does_not_change_width_when_a_tool_is_pressed() -> None:
    """The name of the tool used to sit in the flow under the icons, so pressing a tool widened the
    box and every icon slid sideways — crooked exactly when somebody was looking at it."""
    css = CSS.read_text(encoding="utf-8")
    start = css.index(".tools .tool-said {")
    rule = css[start : css.index("}", start)]

    assert "position: absolute" in rule, "the name is still in the flow and still widens the strip"
    assert "width" not in css[css.index(".tools {") : css.index("}", css.index(".tools {"))], (
        "a width in pixels is what put the icons 4px from one edge and 2px from the other"
    )


def test_a_press_on_the_floating_controls_is_not_a_press_on_the_bench() -> None:
    """The bug the user hit: pressing the area tool began a band, the band's `preventDefault` ate
    the click that would have chosen a different tool, and the strip could be entered and not left.
    Three gestures asked "is this bare bench" and each had its own wrong answer; now there is one."""
    source = _code()
    listed = source[
        source.index("const FURNITURE") : source.index("\n", source.index("const FURNITURE"))
    ]

    for floating in ("#tools", "#bench-map", "#run-bar"):
        assert floating in listed, f"{floating} floats over the canvas and is not excluded"
    # The pan, the band, and the click that clears the choice.
    assert source.count("onBareBench(event.target)") == 3


def test_a_box_says_what_the_question_is_about_rather_than_adding_to_it() -> None:
    """ "Опция выбора в области не отключает активные карточки при выделении, хотя должна." A box
    that only ever adds cannot take anything back: the only way out of a wrong selection would be
    to clear it and draw again. Holding shift is how you add — the same modifier that adds one card."""
    body = _body("endBand")

    assert "if (!adds)" in body and "classList.remove('chosen')" in body
    assert "adds: event.shiftKey," in _code(), "nothing records whether the box was meant to add"
