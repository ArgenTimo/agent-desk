"""Laying the bench out by what a card is, rather than by when it arrived (01M1YQGZK7RK…).

"Раскладка, которая не превращается в кашу на сотне элементов. Тридцать девять карточек уже сделали
верстак нечитаемым — это видели своими глазами."

It was three columns filled in the order the cards happened to arrive, so a project card, the answer
about it and an idea from last week ended up side by side, and a hundred cards were a column twenty
screens long with nothing to navigate by.
"""

from __future__ import annotations

import json
import pathlib

import pytest
from agent_desk.ideas import bench

CONSOLE = (
    pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "static" / "console.js"
)
BOARD = (
    pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "templates" / "board.html"
)


def _body(name: str) -> str:
    source = "\n".join(
        line
        for line in CONSOLE.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("//")
    )
    start = source.index(f"function {name}(")
    return source[start : source.index("\n}\n", start)]


# --- one order, in one place ---------------------------------------------------------------------
@pytest.mark.unit
def test_the_page_is_handed_the_order_rather_than_keeping_a_copy() -> None:
    """The same argument the line vocabulary and the roles are already served under: a second list
    is a second place to be wrong, silently — and this one would be wrong in a way that looks like
    a layout preference rather than a bug."""
    assert 'id="bench-columns"' in BOARD.read_text(encoding="utf-8")

    laying = _body("tidyUp")
    for kind in bench.COLUMN:
        assert f"'{kind}'" not in laying, f"{kind} is named in the script as well as in bench.py"


@pytest.mark.unit
async def test_what_is_served_is_what_the_diagram_uses() -> None:
    """The workbench diagram and "lay it out again" put a card in the same column, because they
    are given the same list. Two orders would mean a card moved when you tidied up."""
    from agent_desk.web import routes

    await routes.store.open()
    try:
        page = await routes.render_page()
    finally:
        await routes.store.close()

    said = page[page.index('id="bench-columns"') :]
    served = json.loads(said[said.index(">") + 1 : said.index("</script>")])

    assert served["of"] == bench.COLUMN
    assert served["beside"] == bench.BESIDE


@pytest.mark.unit
def test_a_kind_nobody_has_placed_gets_a_column_of_its_own() -> None:
    """One past the last of them, so a card kind added next year appears beside the work rather
    than landing on top of the ideas."""
    assert bench.BESIDE == max(bench.COLUMN.values()) + 1
    assert bench.BESIDE not in bench.COLUMN.values()


@pytest.mark.unit
def test_the_order_reads_left_to_right_as_things_containing_things() -> None:
    """A project holds a checkout holds a session; the conversation is about those, an idea comes
    out of the conversation, and a step is drawn after the idea. That is the order, and it is what
    makes where a card sits say what it is before you read a word of it."""
    order = [bench.COLUMN[k] for k in ("project", "instance", "session", "block", "idea", "step")]

    assert order == sorted(order), f"the columns no longer read outside-in: {order}"
    assert bench.COLUMN["agent"] == bench.COLUMN["session"], "an agent is a session, in a column"


# --- and the laying out itself -------------------------------------------------------------------
@pytest.mark.unit
def test_a_card_is_placed_by_what_it_is_and_not_by_when_it_arrived() -> None:
    laying = _body("tidyUp")

    assert "columnOf(pin.dataset.kind)" in laying
    assert "index % 3" not in laying, "the three columns filled in arrival order are still there"


@pytest.mark.unit
def test_the_positions_are_worked_out_rather_than_swept_into() -> None:
    """Collision avoidance gives up after forty steps down and starts a column of its own, which on
    a hundred cards in one column is exactly the porridge this replaces."""
    laying = _body("tidyUp")

    assert "{ avoid: false }" in laying


@pytest.mark.unit
def test_every_height_is_read_before_any_card_is_moved() -> None:
    """Placing one card changes the layout the next measurement would be answered from — the same
    mistake that cost a pan 20ms a frame, one function over."""
    from tests.unit.test_bench_speed import _reads_after_writing

    assert not _reads_after_writing(_body("tidyUp"))


@pytest.mark.unit
def test_a_bench_with_no_order_served_still_lays_out() -> None:
    """Everything in one column is a worse layout, not a broken one — and a console whose page was
    served before this existed should still tidy up."""
    fallback = CONSOLE.read_text(encoding="utf-8")

    assert "column = { of: {}, beside: 0 }" in fallback
    assert "column.of[kind] ?? column.beside" in _body("columnOf")


@pytest.mark.unit
def test_a_card_somebody_placed_is_still_left_alone() -> None:
    """The rule from 042 has to survive the layout being rewritten under it."""
    laying = _body("tidyUp")

    assert "'.pin:not([data-moved])'" in laying
