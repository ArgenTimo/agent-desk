"""A card somebody put somewhere stays where they put it (042-placed-by-hand.sql).

"Сценарий 11 раскладывает карточки по смыслу, человек двигает их сам, а «tidy up» сметает и то и
другое в сетку."

The page has always known which cards somebody placed — it is why the console's own settling steps
around a card you dragged — and it has always forgotten it on reload. So the complaint is one layer
below the button: it is not that "tidy up" is too eager, it is that by the next morning there was
nothing on the bench it knew to be careful with.
"""

from __future__ import annotations

import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk.store.repo import BenchCard, Store

STATIC = pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "static"


@pytest.fixture
async def desk(tmp_path: pathlib.Path) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    yield store
    await store.close()


def _card(name: str, **over: object) -> BenchCard:
    kind, _, card_id = name.partition(":")
    fields: dict[str, object] = {
        "name": name,
        "kind": kind,
        "card_id": card_id,
        "label": name,
        "x": 10,
        "y": 20,
        "shown": "hint",
        "spent": False,
        "ord": 0,
    }
    return BenchCard(**{**fields, **over})  # type: ignore[arg-type]


def _code(script: str) -> str:
    return "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("//"))


@pytest.mark.unit
async def test_a_card_somebody_placed_is_still_placed_after_a_reload(desk: Store) -> None:
    """The whole point. Held only in the page, this fact died with the tab — and the first layout
    of the next morning swept an arrangement somebody had made the night before."""
    await desk.keep_bench([_card("idea:mine", by_hand=True), _card("idea:landed")])

    back = {card.name: card.by_hand for card in await desk.bench_cards()}

    assert back == {"idea:mine": True, "idea:landed": False}


@pytest.mark.unit
async def test_a_card_nobody_placed_says_so_rather_than_nothing(desk: Store) -> None:
    """The default has to be false: a card the console dropped somewhere is not an arrangement, and
    a default of true would make every automatic layout a no-op on its first run."""
    assert _card("idea:one").by_hand is False


@pytest.mark.unit
async def test_being_placed_survives_an_undo(desk: Store) -> None:
    """Going back a step restores a surface, and a surface includes which of it was arranged."""
    await desk.keep_bench([_card("idea:one", by_hand=True)])
    await desk.keep_bench([_card("idea:one", by_hand=True), _card("idea:two")])

    await desk.undo_bench()

    assert [card.by_hand for card in await desk.bench_cards()] == [True]


@pytest.mark.unit
def test_the_page_sends_whether_somebody_placed_each_card() -> None:
    console = _code((STATIC / "console.js").read_text(encoding="utf-8"))

    state = console[console.index("function benchState(") :]
    state = state[: state.index("\n}\n")]
    assert "by_hand: pin.dataset.moved === 'yes'" in state


@pytest.mark.unit
def test_restoring_a_bench_puts_the_mark_back_on_the_cards_that_had_it() -> None:
    """Stored and not restored is worse than not stored: the console would keep a fact it never
    acts on, and the arrangement would still be swept.

    Asserted on `layOut` because that is now the one place cards go back onto a surface — the page
    opening, switching to another chat, and undoing all go through it. Three copies of that loop
    were three places for the next card property to be forgotten in, which is exactly what this
    property was.
    """
    console = _code((STATIC / "console.js").read_text(encoding="utf-8"))

    block = console[console.index("function layOut(") :]
    block = block[: block.index("\n}\n")]
    assert "one.by_hand" in block and "dataset.moved = 'yes'" in block, (
        "cards are put back on the surface without which of them somebody chose"
    )
    for goes_through in (
        "function restoreBench(",
        "async function undoBench(",
        "async function benchOfThisChat(",
    ):
        where = console[console.index(goes_through) :]
        where = where[: where.index("\n}\n")]
        assert "layOut(" in where, f"{goes_through.strip()} lays cards out its own way again"


# The two layouts behind one button: cards in columns, and an enquiry followed down its lines. Both
# are what "lay it out again" does, so the rules below hold of both — one that only the older one
# keeps is a rule somebody meets or does not depending on whether their chat has a beginning.
LAYOUTS = ("layOutInColumns", "layOutTheEnquiry")


def _laying(name: str) -> str:
    console = _code((STATIC / "console.js").read_text(encoding="utf-8"))
    body = console[console.index(f"function {name}(") :]
    return body[: body.index("\n}\n")]


@pytest.mark.unit
@pytest.mark.parametrize("which", LAYOUTS)
def test_tidying_up_moves_only_what_nobody_placed(which: str) -> None:
    """It used to empty the whole layout and lay every card out in a grid, so a set of cards put on
    the left because they belonged on the left went into column two."""
    laying = _laying(which)

    assert "'.pin:not([data-moved])'" in laying, "it still lays out every card on the bench"
    assert "placed = new Map()" not in laying, (
        "it still forgets every position, which takes the placed cards' spots with it"
    )


@pytest.mark.unit
@pytest.mark.parametrize("which", LAYOUTS)
def test_tidying_up_says_when_it_left_things_alone(which: str) -> None:
    """A button that did less than everything and did not mention it is a button somebody presses
    twice, and then a third time, before deciding it is broken. Both cases are covered — some laid
    out and some left, and nothing to lay out at all — rather than counted, because what matters is
    that neither silence happens."""
    laying = _laying(which)

    assert "you placed all ${kept} of these yourself" in laying
    assert "stayed where they were" in laying


@pytest.mark.unit
def test_the_console_s_own_settling_already_steps_around_a_placed_card() -> None:
    """Asserted rather than assumed, because this is the behaviour the whole column exists to make
    survive a reload — if the settle stopped respecting it, storing it would protect nothing."""
    console = _code((STATIC / "console.js").read_text(encoding="utf-8"))

    settle = console[console.index("function settleOverlaps(") :]
    settle = settle[: settle.index("\n}\n")]

    assert "'.pin:not([data-moved])'" in settle
