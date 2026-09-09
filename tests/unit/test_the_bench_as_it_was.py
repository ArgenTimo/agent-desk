"""The workbench, rewound (01M1XED1CVT7J0JTV5BTWJDT4J).

«Ползунок, который показывает верстак таким, каким он был вчера в 14:00: какие карточки лежали, какие
связи были… Это чтение, а не хранение: ничего дополнительно записывать не надо.»
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk.store.repo import BenchCard, Store
from agent_desk.web import routes

pytestmark = pytest.mark.unit

HERE = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture
async def desk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
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


# --- reading, not storing --------------------------------------------------------------------------
async def test_every_change_is_a_stop_on_the_slider(desk: Store) -> None:
    """ "У каждой строки в базе уже есть время." Nothing new is written to answer this."""
    await desk.keep_bench([_card("idea:one")])
    await desk.keep_bench([_card("idea:one"), _card("idea:two", ord=1)])

    assert len(await desk.bench_moments()) == 2


async def test_a_write_that_changed_nothing_is_not_a_stop(desk: Store) -> None:
    """The page asks for the bench to be written whenever it recounts what is on it. A slider with
    a stop for each of those is one nobody can aim."""
    await desk.keep_bench([_card("idea:one")])
    await desk.keep_bench([_card("idea:one")])

    assert len(await desk.bench_moments()) == 1


async def test_it_shows_what_was_on_the_bench_then_and_not_what_is_now(desk: Store) -> None:
    await desk.keep_bench([_card("idea:one")])
    (first,) = await desk.bench_moments()
    await desk.keep_bench([_card("idea:one"), _card("idea:two", ord=1)])

    cards, _, known = await desk.bench_as_it_was(first)

    assert [one.name for one in cards] == []
    assert known


async def test_the_lines_of_that_moment_come_back_with_it(desk: Store) -> None:
    """ "Какие карточки лежали, какие связи были." A surface without its lines is half of what
    somebody was looking at."""
    await desk.tie_cards(from_name="idea:one", to_name="idea:two", kind="then", says="")
    await desk.keep_bench([_card("idea:one"), _card("idea:two", ord=1)])
    at = (await desk.bench_moments())[-1]
    await desk.keep_bench([_card("idea:one")])

    cards, lines, _ = await desk.bench_as_it_was(at + 1)

    assert {one.name for one in cards} == {"idea:one", "idea:two"}
    assert [(one.from_name, one.to_name) for one in lines] == [("idea:one", "idea:two")]


async def test_a_moment_after_the_last_change_is_the_bench_as_it_stands(desk: Store) -> None:
    """Nothing changed after it, so what it was then is what it is now."""
    await desk.keep_bench([_card("idea:one")])

    cards, _, known = await desk.bench_as_it_was(2**62)

    assert [one.name for one in cards] == ["idea:one"]
    assert known


async def test_a_moment_older_than_anything_remembered_says_so(desk: Store) -> None:
    """Fifty changes back is a real limit, and an answer that quietly meant something else would
    make the slider lie at its left end."""
    await desk.keep_bench([_card("idea:one")])
    await desk.keep_bench([_card("idea:one"), _card("idea:two", ord=1)])
    oldest = (await desk.bench_moments())[0]

    _, _, known = await desk.bench_as_it_was(oldest - 1)

    assert not known


async def test_a_line_with_one_end_off_that_surface_is_not_drawn(desk: Store) -> None:
    """The same rule the snapshot was taken under: an old bench shows what somebody was looking
    at, and a line to something not on it explains nothing."""
    await desk.keep_bench([_card("idea:one")])
    await desk.tie_cards(from_name="idea:one", to_name="idea:elsewhere", kind="then", says="")

    _, lines, _ = await desk.bench_as_it_was(2**62)

    assert lines == []


# --- and the routes --------------------------------------------------------------------------------
async def test_the_stops_are_served_to_the_slider(desk: Store) -> None:
    await desk.keep_bench([_card("idea:one")])

    back = json.loads((await routes.when_the_workbench_changed()).body)

    assert len(back["at"]) == 1


async def test_the_moment_is_drawn_the_way_the_present_is(desk: Store) -> None:
    """The same reader, so a surface an hour old and the one on screen are described in the same
    words and can be compared without translating between two pictures."""
    await desk.keep_bench([_card("idea:one", label="a thought", came="dragged in")])

    back = json.loads((await routes.the_workbench_as_it_was(at=2**62)).body)

    assert [one["label"] for one in back["cards"]] == ["a thought"]
    assert back["cards"][0]["came"] == "dragged in"
    assert "flowchart" in back["said"]
    assert back["known"]


async def test_the_route_says_when_it_does_not_remember(desk: Store) -> None:
    await desk.keep_bench([_card("idea:one")])
    await desk.keep_bench([_card("idea:one"), _card("idea:two", ord=1)])
    oldest = (await desk.bench_moments())[0]

    back = json.loads((await routes.the_workbench_as_it_was(at=oldest - 1)).body)

    assert not back["known"]


# --- and the control ---------------------------------------------------------------------------------
def test_the_console_offers_it_and_asks_for_both_halves() -> None:
    """A slider needs its stops before it can be dragged, and a stop needs a surface to show."""
    script = (HERE / "agent_desk" / "web" / "static" / "console.js").read_text(encoding="utf-8")
    board = (HERE / "agent_desk" / "web" / "templates" / "board.html").read_text(encoding="utf-8")
    code = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("//"))

    assert 'data-add="rewind"' in board
    assert "/workbench/moments" in code
    assert "/workbench/as-it-was" in code
    assert "showAsItWas" in code


def test_the_right_hand_end_of_the_slider_is_now() -> None:
    """A slider whose right-hand end was the last recorded change would have no position for the
    surface somebody is actually looking at."""
    script = (HERE / "agent_desk" / "web" / "static" / "console.js").read_text(encoding="utf-8")
    body = script[script.index("async function showAsItWas") :]
    body = body[: body.index("\n}\n")]

    assert "step >= moments.length ? Date.now()" in body
