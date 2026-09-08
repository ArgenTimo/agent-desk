"""A card opens out into its parts (01M1X8DA5RSWKYPVFFVN0R1CRN).

"Помещая проект на экран я хочу видеть карточки связанных инстансов, сессий, агентов + карточки
коннекторов."

`bringItsKin` brought a little family along when a card arrived, and only for ideas. What was
missing is the deliberate act: press a card and get what it is made of, as cards of its own with
lines to it.

"Раскрытие ленивое: проект с пятью инстансами и сорока сессиями, раскрытый целиком и сразу, это
сорок карточек, которые никто не просил."
"""

from __future__ import annotations

import pathlib

import pytest

pytestmark = pytest.mark.unit

HERE = pathlib.Path(__file__).resolve().parents[2]
CONSOLE = HERE / "agent_desk" / "web" / "static" / "console.js"
BOARD = HERE / "agent_desk" / "web" / "templates" / "_board.html"


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


def test_the_parts_are_read_from_the_board_rather_than_asked_for() -> None:
    """The board is already this tree. A second source is a second thing to keep in step, and the
    day they disagree is the day a card opens out into something that is not on the board."""
    finding = _body("partsOf")

    assert "boardCard(name)" in finding
    assert "fetch(" not in finding


def test_the_parts_of_a_card_are_the_nearest_cards_under_it() -> None:
    """One rule rather than one per kind, so a card kind added to the board later opens out
    without anybody coming back here. And it is what makes the expansion lazy: the sessions under a
    checkout are not parts of the project, they are parts of the checkout."""
    assert "one.parentElement.closest('[data-kind][data-id]') === holder" in _body("partsOf")


def test_the_board_really_is_that_tree() -> None:
    """Asserted here because the rule above depends on it: a project's markup contains its
    checkouts, which contain their sessions, which contain their agents."""
    markup = BOARD.read_text(encoding="utf-8")
    project = markup.index('data-kind="project"')
    instance = markup.index('data-kind="instance"', project)
    session = markup.index('data-kind="session"', instance)
    assert markup.index('data-kind="agent"', session) > session


def test_one_level_per_press() -> None:
    """A project with five checkouts and forty sessions, opened out at once, is forty cards nobody
    asked for. The way down is to press the card that arrived."""
    opening = _body("openItsParts")
    inside = opening[opening.index("{") :]

    assert "partsOf(name)" in inside
    assert "openItsParts" not in inside, (
        "it opens its parts' parts too, which is every card at once"
    )
    assert "depth" not in inside, "there is no depth to walk — there is one level and a press"


def test_a_part_already_on_the_bench_is_not_pinned_twice() -> None:
    assert '`.pin[data-name="${CSS.escape(under)}"]`' in _body("openItsParts")


def test_pressing_twice_does_not_draw_the_lines_twice() -> None:
    opening = _body("openItsParts")

    assert "openedOut.has(" in opening
    assert "openedOut.add(" in opening


def test_each_part_says_it_was_opened_out_of_something() -> None:
    """ "Why is this here" has to have an answer for a card that arrived by a press as much as for
    one somebody dragged."""
    assert "came: `opened out of the ${what}`" in _body("openItsParts")


def test_the_line_says_what_the_relation_is() -> None:
    assert "says: 'part of'" in _body("openItsParts")


def test_the_control_is_hidden_rather_than_dead() -> None:
    """A control that does nothing when pressed is worse than no control: the first press teaches
    somebody it is broken, and they stop pressing the ones that work."""
    showing = _body("showParts")

    assert "button.hidden = partsOf(cardName(holder)).length === 0" in showing


def test_the_control_is_reconsidered_when_the_board_moves() -> None:
    """A session that has started its first subagent has parts it did not have a moment ago."""
    source = _code()
    start = source.index("stream.addEventListener('board'")
    handler = source[start : source.index("\n});\n", start)]

    assert "showParts(card)" in handler


def test_pressing_it_opens_the_card_out() -> None:
    source = _code()

    assert "event.target.classList.contains('pin-parts')" in source
    assert "openItsParts(event.target.closest('.pin'))" in source
