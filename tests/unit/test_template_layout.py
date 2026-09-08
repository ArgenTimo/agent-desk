"""A saved drawing remembers where its cards were (01M1XC4Z2MG9…).

"Использованный шаблон высыпает карточки кучей, и каждый раз их раскладывают заново. Позиции —
часть того, что человек собрал, и терять их не нужно."

038 saved a template as a *shape*, and that argument still holds for everything it covers: a
template makes new cards, so it cannot save the ones it was drawn from. But where those cards sat
is not a fact about the cards — it is a fact about the drawing, arranged by hand, which is exactly
the kind of work 042 exists to stop the console throwing away.
"""

from __future__ import annotations

import json
import pathlib
import tempfile
from collections.abc import AsyncIterator

import pytest
from agent_desk.store.repo import BenchCard, Store, TemplateStep
from agent_desk.web import routes

from tests.unit.test_kept_bench import _post_form

CONSOLE = (
    pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "static" / "console.js"
)


@pytest.fixture
async def desk() -> AsyncIterator[Store]:
    with tempfile.TemporaryDirectory() as where:
        store = Store(pathlib.Path(where) / "agent-desk.db")
        await store.open()
        old, routes.store = routes.store, store
        try:
            yield store
        finally:
            routes.store = old
            await store.close()


def _card(name: str, x: int, y: int) -> BenchCard:
    kind, _, card_id = name.partition(":")
    return BenchCard(
        name=name,
        kind=kind,
        card_id=card_id,
        label=name,
        x=x,
        y=y,
        shown="hint",
        spent=False,
        ord=0,
    )


@pytest.mark.unit
async def test_a_template_keeps_where_its_cards_sat(desk: Store) -> None:
    one = await desk.add_step_card("first")
    two = await desk.add_step_card("second")
    await desk.keep_bench([_card(one.name, 300, 100), _card(two.name, 300, 400)], thread_id="a")

    _, body = await _post_form(
        "/workbench/template",
        {"name": "a release", "cards": f"{one.name},{two.name}", "thread": "a"},
    )
    assert json.loads(body)["kept"] is True

    (made,) = await desk.templates()
    assert [(step.dx, step.dy) for step in made.steps] == [(0, 0), (0, 300)]


@pytest.mark.unit
async def test_the_offsets_are_from_the_drawing_rather_than_from_the_bench(desk: Store) -> None:
    """A template put down on a bench that already has cards must not land on top of them, and a
    drawing whose shape survives being placed anywhere is a drawing rather than a screenshot."""
    one = await desk.add_step_card("first")
    two = await desk.add_step_card("second")
    await desk.keep_bench([_card(one.name, 900, 700), _card(two.name, 1100, 700)], thread_id="a")

    await _post_form(
        "/workbench/template",
        {"name": "a release", "cards": f"{one.name},{two.name}", "thread": "a"},
    )

    (made,) = await desk.templates()
    assert [(step.dx, step.dy) for step in made.steps] == [(0, 0), (200, 0)]


@pytest.mark.unit
async def test_using_it_hands_back_the_shape(desk: Store) -> None:
    await desk.keep_template(
        name="a release",
        steps=[
            TemplateStep(ord=1, role="action", label="first", dx=0, dy=0),
            TemplateStep(ord=2, role="action", label="second", dx=0, dy=300),
        ],
        lines=[],
    )

    _, body = await _post_form("/workbench/template/use", {"name": "a release"})

    said = json.loads(body)
    assert [(one["dx"], one["dy"]) for one in said["cards"]] == [(0, 0), (0, 300)]


@pytest.mark.unit
async def test_a_template_saved_before_this_says_nothing_rather_than_the_origin(
    desk: Store,
) -> None:
    """Inventing an answer would put somebody's older drawing into a grid it never had. Absent
    means "lay it out the way you always did", which is what those templates already do."""
    await desk.keep_template(
        name="an old one",
        steps=[TemplateStep(ord=1, role="action", label="first")],
        lines=[],
    )

    (made,) = await desk.templates()
    assert made.steps[0].dx is None and made.steps[0].dy is None

    _, body = await _post_form("/workbench/template/use", {"name": "an old one"})
    assert json.loads(body)["cards"][0]["dx"] is None


@pytest.mark.unit
def test_the_page_lays_it_out_the_old_way_only_when_there_is_nothing_to_remember() -> None:
    console = CONSOLE.read_text(encoding="utf-8")
    using = console[console.index("async function useTemplate(") :]
    using = using[: using.index("\n}\n")]

    assert "Number.isInteger(one.dx)" in using
    assert "if (!remembers) tidyUp();" in using, "a remembered shape is swept into the grid anyway"


@pytest.mark.unit
def test_the_cards_a_template_places_count_as_placed() -> None:
    """Otherwise the first card to grow to fit its body sweeps the shape away — the console's own
    layout only leaves alone what somebody put somewhere (042-placed-by-hand.sql)."""
    console = CONSOLE.read_text(encoding="utf-8")
    using = console[console.index("async function useTemplate(") :]
    using = using[: using.index("\n}\n")]

    assert "dataset.moved = 'yes'" in using
    assert "moveWasDeliberate()" in using, "putting a whole drawing down cannot be undone"
