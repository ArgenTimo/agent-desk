"""Laying out an enquiry that has stopped being a tree (01M1XA1V7GWKW26M1A52X3NXAE).

"2 разные изначально темы могут начать переплетаться далее… Наши линии-локти рисуются от карточки
к карточке и с этим справятся; чего нет — раскладки, которая не рвёт длинную ветку на куски, когда
та начинает ветвиться вширь."

A column per kind is right for a pile of sessions and ideas and wrong for an enquiry: every answer
in one column and every question in another tears a branch in half the moment it is longer than two
steps, and the thing somebody is trying to read — this followed from that, which followed from
those two — is the one thing that arrangement cannot show.
"""

from __future__ import annotations

import json
import pathlib

import pytest
from agent_desk.branching import GAP, Card, lay_out

pytestmark = pytest.mark.unit

CONSOLE = (
    pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "static" / "console.js"
)
WIDE, TALL = 300, 120


def _cards(*names: str) -> list[Card]:
    return [Card(name=name, width=WIDE, height=TALL) for name in names]


def _line(one: str, other: str) -> dict[str, str]:
    return {"from": one, "to": other, "says": "follows on from"}


def _middle(spots: dict[str, object], name: str) -> float:
    return spots[name].x + WIDE / 2  # type: ignore[attr-defined]


# --- a branch stays a branch ----------------------------------------------------------------------
def test_a_long_chain_is_one_column() -> None:
    """The whole complaint. Four cards, one after another, must read as one thing going down."""
    spots = lay_out(_cards("a", "b", "c", "d"), [_line("a", "b"), _line("b", "c"), _line("c", "d")])

    assert len({spot.x for spot in spots.values()}) == 1
    assert [spots[name].y for name in "abcd"] == sorted(spots[name].y for name in "abcd")


def test_a_chain_stays_together_when_something_beside_it_fans_out() -> None:
    """The case the idea names: a branch that grows wide next door must not push a long branch into
    pieces."""
    spots = lay_out(
        _cards("root", "long1", "long2", "wide1", "wide2", "wide3"),
        [
            _line("root", "long1"),
            _line("long1", "long2"),
            _line("root", "wide1"),
            _line("wide1", "wide2"),
            _line("wide1", "wide3"),
        ],
    )

    assert spots["long1"].x == spots["long2"].x, "the long branch was torn sideways"


def test_children_hang_below_the_card_they_came_from() -> None:
    spots = lay_out(_cards("a", "b"), [_line("a", "b")])

    assert spots["b"].y > spots["a"].y


def test_two_children_are_side_by_side_and_do_not_touch() -> None:
    """The lines run through the space between them, and two cards touching leave nowhere for a
    line to be seen."""
    spots = lay_out(_cards("a", "b", "c"), [_line("a", "b"), _line("a", "c")])

    assert spots["b"].y == spots["c"].y
    assert abs(spots["b"].x - spots["c"].x) >= WIDE + GAP


# --- and a graph is a graph ------------------------------------------------------------------------
def test_a_card_that_follows_two_branches_sits_between_them() -> None:
    """The picture of a merge. Under one of its parents it reads as belonging to that branch, with
    a long line arriving from somewhere else."""
    spots = lay_out(
        _cards("a", "b", "c", "d"),
        [_line("a", "b"), _line("a", "c"), _line("b", "d"), _line("c", "d")],
    )

    assert _middle(spots, "d") == pytest.approx(
        (_middle(spots, "b") + _middle(spots, "c")) / 2, abs=1
    )


def test_a_merge_lands_below_the_deeper_of_its_parents() -> None:
    """Longest way down rather than shortest. Taking the shortest would draw a line upwards from
    the other parent, and an arrow that goes back up a diagram is read as a loop."""
    spots = lay_out(
        _cards("root", "near", "far1", "far2", "join"),
        [
            _line("root", "near"),
            _line("root", "far1"),
            _line("far1", "far2"),
            _line("near", "join"),
            _line("far2", "join"),
        ],
    )

    assert spots["join"].y > spots["far2"].y
    assert spots["join"].y > spots["near"].y


def test_two_enquiries_side_by_side_each_start_at_the_top() -> None:
    spots = lay_out(_cards("a", "b", "c", "d"), [_line("a", "b"), _line("c", "d")])

    assert spots["a"].y == spots["c"].y
    assert spots["a"].x != spots["c"].x


# --- what it refuses to fall over on ----------------------------------------------------------------
def test_a_line_to_a_card_that_is_not_here_changes_nothing() -> None:
    """An answer somebody took off the bench, or a card belonging to another chat. Not an error."""
    here = lay_out(_cards("a", "b"), [_line("a", "b")])
    with_ghost = lay_out(_cards("a", "b"), [_line("a", "b"), _line("b", "gone"), _line("x", "a")])

    assert here == with_ghost


def test_two_cards_pointing_at_each_other_still_lay_out() -> None:
    """A person can draw both lines, and a layout that hangs on it is worse than one that picks an
    order and moves on."""
    spots = lay_out(_cards("a", "b"), [_line("a", "b"), _line("b", "a")])

    assert set(spots) == {"a", "b"}
    assert spots["a"].y != spots["b"].y


def test_a_card_joined_to_nothing_is_still_placed() -> None:
    spots = lay_out(_cards("a", "b"), [])

    assert spots["a"].y == spots["b"].y
    assert set(spots) == {"a", "b"}


def test_an_empty_bench_lays_out_to_nothing() -> None:
    assert lay_out([], []) == {}


def test_the_same_bench_lays_out_the_same_way_twice() -> None:
    """An arrangement that moved every time somebody pressed the button would be a button nobody
    trusts."""
    cards, lines = _cards("a", "b", "c"), [_line("a", "b"), _line("a", "c")]

    assert lay_out(cards, lines) == lay_out(cards, lines)


# --- which layout runs, and what the page sends ----------------------------------------------------
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


def test_the_enquiry_layout_runs_when_the_chat_has_said_what_it_is_about() -> None:
    """A thing somebody set, rather than a guess from the shape of the bench — where "there are
    some lines" is true of almost every bench."""
    choosing = _body("tidyUp")
    assert "surface?.querySelector('.pin.beginning')" in choosing
    assert "layOutTheEnquiry()" in choosing
    assert "layOutInColumns()" in choosing


def test_the_page_sends_the_sizes_it_measured() -> None:
    """Nothing on the server can work out how tall a card has drawn itself, and a layout computed
    against a guessed height overlaps the moment a card says two lines instead of one."""
    laying = _body("layOutTheEnquiry")
    assert "width: pin.offsetWidth || CARD_WIDTH" in laying
    assert "height: pin.offsetHeight || 120" in laying


def test_the_page_sends_its_own_lines_too() -> None:
    """Half of them were never written down: an answer joined to its question and a question to
    what it follows on from are the page's, not the store's."""
    assert "lines: everyTie()" in _body("layOutTheEnquiry")


def test_a_layout_that_could_not_be_had_leaves_the_bench_alone() -> None:
    laying = _body("layOutTheEnquiry")
    assert "return say('Could not work out a layout for this one.')" in laying


async def test_a_body_that_is_not_a_bench_arranges_nothing() -> None:
    """Refusing the layout is the surface somebody already has, which is the safe outcome."""
    from tests.unit.test_kept_bench import _post_json

    status, said = await _post_json("/workbench/arrange", {"cards": [{"name": "a"}]})

    assert status == 200
    assert json.loads(said) == {"spots": {}}


async def test_the_route_hands_back_a_place_for_each_card() -> None:
    from tests.unit.test_kept_bench import _post_json

    status, said = await _post_json(
        "/workbench/arrange",
        {
            "cards": [
                {"name": "a", "width": WIDE, "height": TALL},
                {"name": "b", "width": WIDE, "height": TALL},
            ],
            "lines": [_line("a", "b")],
        },
    )

    spots = json.loads(said)["spots"]
    assert status == 200
    assert set(spots) == {"a", "b"}
    assert spots["b"]["y"] > spots["a"]["y"]
