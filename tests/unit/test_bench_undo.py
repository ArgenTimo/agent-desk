"""One undo for the workbench, and one for all of it (041-bench-undo.sql).

"Каждое из этого меняет поверхность целиком, и без отмены никто не станет пробовать. Одна отмена на
всё, а не своя у каждой фичи — иначе через полгода их будет восемь и все с разным поведением."

Two of these matter more than the rest, because they are the ways this control fails while looking
as though it worked: a step recorded for something nobody did, and a restore that records a step of
its own. Both produce a press that changes nothing visible — the one outcome forbidden to a button
whose entire job is to make somebody confident that trying things is safe.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk.store.repo import MOST_UNDO_STEPS, BenchCard, Store
from sqlalchemy import text


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


async def _steps(store: Store) -> int:
    async with store.engine.connect() as conn:
        return int((await conn.execute(text("SELECT count(*) FROM bench_was"))).scalar() or 0)


# --- it goes back --------------------------------------------------------------------------------
@pytest.mark.unit
async def test_a_card_taken_off_comes_back(desk: Store) -> None:
    await desk.keep_bench([_card("idea:one"), _card("idea:two")])
    await desk.keep_bench([_card("idea:one")])

    assert await desk.undo_bench() is True
    assert [card.name for card in await desk.bench_cards()] == ["idea:one", "idea:two"]


@pytest.mark.unit
async def test_a_card_somebody_dragged_goes_back_to_where_it_was(desk: Store) -> None:
    await desk.keep_bench([_card("idea:one", x=10, y=20)])
    await desk.keep_bench([_card("idea:one", x=800, y=900)], moved=True)

    await desk.undo_bench()

    (back,) = await desk.bench_cards()
    assert (back.x, back.y) == (10, 20)


@pytest.mark.unit
async def test_a_card_the_console_shuffled_is_not_a_step(desk: Store) -> None:
    """The measurement that produced this rule: a card is placed before its body arrives and grows
    when it does, so the console lays its neighbours out again — three times and across twenty
    cards on one ordinary page load.

    Recorded, those made *opening the page* undoable, and the first three presses of undo walked
    back through the console tidying up after itself while appearing to do nothing at all.
    """
    await desk.keep_bench([_card("idea:one", x=10, y=20)])
    before = await _steps(desk)

    await desk.keep_bench([_card("idea:one", x=800, y=900)])

    assert await _steps(desk) == before
    assert (await desk.bench_cards())[0].x == 800, "the move was not saved either"


@pytest.mark.unit
async def test_a_card_appearing_needs_no_flag_at_all(desk: Store) -> None:
    """Which cards are on the bench is something only a person changes, so the store can tell on
    its own — and a gesture that adds a card cannot forget to make itself undoable."""
    await desk.keep_bench([_card("idea:one")])
    before = await _steps(desk)

    await desk.keep_bench([_card("idea:one"), _card("idea:two")])

    assert await _steps(desk) == before + 1


@pytest.mark.unit
async def test_an_answer_arriving_is_not_something_to_undo(desk: Store) -> None:
    """A block card is a question and its answer, put on the bench by the conversation and taken
    off by it. Pressing undo should not make an answer disappear."""
    await desk.keep_bench([_card("idea:one")])
    before = await _steps(desk)

    await desk.keep_bench([_card("idea:one"), _card("block:01M1X")])

    assert await _steps(desk) == before


@pytest.mark.unit
async def test_joining_two_cards_is_undone_by_the_same_control(desk: Store) -> None:
    """The point of the whole design: a line is not a card, and it did not have to know this
    exists. A second undo for lines is how you get eight of them by next year."""
    await desk.keep_bench([_card("idea:one"), _card("idea:two")])
    await desk.tie_cards(from_name="idea:one", to_name="idea:two", kind="then", says="then")

    assert await desk.undo_bench() is True
    assert await desk.card_ties() == []
    assert len(await desk.bench_cards()) == 2, "undoing a line took the cards with it"


@pytest.mark.unit
async def test_rubbing_a_line_out_is_undone_too(desk: Store) -> None:
    await desk.keep_bench([_card("idea:one"), _card("idea:two")])
    await desk.tie_cards(from_name="idea:one", to_name="idea:two", kind="then", says="then")
    (tie,) = await desk.card_ties()
    await desk.untie_cards(tie.id)

    await desk.undo_bench()

    assert [(one.from_name, one.to_name) for one in await desk.card_ties()] == [
        ("idea:one", "idea:two")
    ]


@pytest.mark.unit
async def test_undoing_twice_goes_back_twice(desk: Store) -> None:
    """A restore that recorded a step of its own would make the second press undo the first, and
    the control would toggle between two states for ever."""
    await desk.keep_bench([_card("idea:one")])
    await desk.keep_bench([_card("idea:one"), _card("idea:two")])
    await desk.keep_bench([_card("idea:one"), _card("idea:two"), _card("idea:three")])

    await desk.undo_bench()
    await desk.undo_bench()

    assert [card.name for card in await desk.bench_cards()] == ["idea:one"]


@pytest.mark.unit
async def test_the_start_is_a_place_you_can_get_back_to(desk: Store) -> None:
    """The first card put on the bench is a change like any other, so the empty bench is a state
    the undo can reach — otherwise "put a project on and take it back off" is not undoable."""
    await desk.keep_bench([_card("idea:one")])

    assert await desk.undo_bench() is True
    assert await desk.bench_cards() == []


@pytest.mark.unit
async def test_nothing_to_go_back_to_says_so(desk: Store) -> None:
    """False rather than an exception and rather than a silent success: the page renders the
    difference, and a press that quietly did nothing is what this is all trying to avoid."""
    assert await desk.can_undo_bench() is False
    assert await desk.undo_bench() is False


# --- and it does not record what nobody did -------------------------------------------------------
@pytest.mark.unit
async def test_writing_the_same_bench_again_is_not_a_step(desk: Store) -> None:
    """The page asks for the bench to be written whenever it recounts what is on it, which happens
    on plenty of things that change nothing."""
    await desk.keep_bench([_card("idea:one")])
    before = await _steps(desk)
    await desk.keep_bench([_card("idea:one")])
    await desk.keep_bench([_card("idea:one")])

    assert await _steps(desk) == before


@pytest.mark.unit
async def test_restacking_and_relabelling_are_not_steps(desk: Store) -> None:
    """Neither is something a person did. The stacking order is rebuilt from the document every
    time the page draws itself, and a card's real name arrives a moment after the card does, when
    its body has been fetched — so both change on their own, on every single load.

    Recorded, they made *opening the page* an undoable action, which means the first press of undo
    goes back to the state you are already in.
    """
    await desk.keep_bench([_card("idea:one", ord=0), _card("idea:two", ord=1)])
    before = await _steps(desk)

    await desk.keep_bench(
        [_card("idea:two", ord=0, label="what it is really called"), _card("idea:one", ord=1)]
    )

    assert await _steps(desk) == before


@pytest.mark.unit
async def test_the_page_redrawing_after_an_undo_does_not_undo_the_undo(desk: Store) -> None:
    """The whole round trip. The page is handed the restored surface, draws it, and writes it back
    — and that write must be recognised as the state the store is already in."""
    await desk.keep_bench([_card("idea:one")])
    await desk.keep_bench([_card("idea:one"), _card("idea:two")])
    await desk.undo_bench()

    restored = await desk.bench_cards()
    await desk.keep_bench(restored)

    assert await desk.undo_bench() is True
    assert await desk.bench_cards() == [], "the page's redraw was recorded as a change"


@pytest.mark.unit
async def test_folding_a_card_and_leaving_one_out_are_things_you_can_take_back(desk: Store) -> None:
    """Both are things somebody did on purpose to the surface, unlike the three above."""
    await desk.keep_bench([_card("idea:one", shown="hint", spent=False)])
    await desk.keep_bench([_card("idea:one", shown="full", spent=True)])

    await desk.undo_bench()

    (back,) = await desk.bench_cards()
    assert (back.shown, back.spent) == ("hint", False)


# --- and it stays a bounded amount of disk --------------------------------------------------------
@pytest.mark.unit
async def test_the_history_stops_at_the_cap(desk: Store) -> None:
    """Every step is the whole surface, and a surface is written every time somebody drags a card.

    Cut from the far end: what is thrown away is the oldest state, which is the one nobody is
    heading back to — cutting the newest would make the most recent press the one that fails.
    """
    for x in range(MOST_UNDO_STEPS + 12):
        await desk.keep_bench([_card("idea:one", x=x)], moved=True)

    assert await _steps(desk) == MOST_UNDO_STEPS

    async with desk.engine.connect() as conn:
        rows = await conn.execute(text("SELECT surface FROM bench_was ORDER BY at DESC LIMIT 1"))
        newest = json.loads(str(rows.scalar()))
    assert newest["cards"][0]["x"] == MOST_UNDO_STEPS + 10, "the newest step was the one dropped"


# --- the route and the page ----------------------------------------------------------------------
@pytest.mark.unit
async def test_the_restored_surface_comes_back_with_the_answer(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fetched afterwards instead, the page would read a bench it is about to overwrite with the
    state it just undid — the same race, one step further along."""
    from agent_desk.web import routes

    from tests.unit.test_kept_bench import _post_form

    monkeypatch.setattr(routes, "store", desk)
    await desk.keep_bench([_card("idea:one")])
    await desk.keep_bench([_card("idea:one"), _card("idea:two")])

    _, body = await _post_form("/workbench/undo", {})
    said = json.loads(body)

    assert said["undone"] is True
    assert [card["name"] for card in said["cards"]] == ["idea:one"]


@pytest.mark.unit
async def test_the_route_says_when_there_is_nothing_to_undo(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent_desk.web import routes

    from tests.unit.test_kept_bench import _post_form

    monkeypatch.setattr(routes, "store", desk)

    _, body = await _post_form("/workbench/undo", {})

    assert json.loads(body) == {"undone": False, "cards": []}


@pytest.mark.unit
async def test_one_chat_s_undo_does_not_reach_into_another(desk: Store) -> None:
    """Each chat has its own workbench and its own way back through it (044). Sharing a history
    would make a press here change a surface somebody was looking at over there."""
    await desk.keep_bench([_card("idea:one")], thread_id="a")
    await desk.keep_bench([_card("idea:one"), _card("idea:two")], thread_id="a")
    await desk.keep_bench([_card("idea:three")], thread_id="b")

    assert await desk.undo_bench("a") is True

    assert [card.name for card in await desk.bench_cards("a")] == ["idea:one"]
    assert [card.name for card in await desk.bench_cards("b")] == ["idea:three"]


@pytest.mark.unit
async def test_a_chat_with_nothing_behind_it_has_nothing_to_undo(desk: Store) -> None:
    await desk.keep_bench([_card("idea:one")], thread_id="a")

    assert await desk.can_undo_bench("b") is False
    assert await desk.undo_bench("b") is False
    assert [card.name for card in await desk.bench_cards("a")] == ["idea:one"]


@pytest.mark.unit
async def test_a_line_on_another_chat_s_bench_is_left_where_it_is(desk: Store) -> None:
    """A line is a statement about two cards rather than about a surface, so the same line shows on
    every bench holding both its ends. An undo still has to put back only what somebody was looking
    at — otherwise a press here makes a line reappear over there."""
    await desk.keep_bench([_card("idea:one"), _card("idea:two")], thread_id="a")
    await desk.keep_bench([_card("idea:three"), _card("idea:four")], thread_id="b")
    await desk.tie_cards(
        from_name="idea:three", to_name="idea:four", kind="then", says="then", thread_id="b"
    )
    await desk.tie_cards(
        from_name="idea:one", to_name="idea:two", kind="then", says="then", thread_id="a"
    )

    await desk.undo_bench("a")

    assert [(one.from_name, one.to_name) for one in await desk.card_ties()] == [
        ("idea:three", "idea:four")
    ]


def _code(script: str) -> str:
    """The script with its whole-line comments taken out — a rule checked as a substring otherwise
    trips over the paragraph that explains it."""
    return "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("//"))


@pytest.mark.unit
def test_the_page_cancels_its_pending_write_before_undoing() -> None:
    """A drag half a second ago has a write waiting. Landing after the undo, it puts back exactly
    the state the undo took away — and the press looks as though it did nothing."""
    static = pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "static"
    console = _code((static / "console.js").read_text(encoding="utf-8"))

    undo = console[console.index("async function undoBench(") :]
    undo = undo[: undo.index("\n}\n")]
    assert "clearTimeout(writing)" in undo, "the write waiting from the last drag still lands"
    assert undo.index("clearTimeout(writing)") < undo.index("fetch("), (
        "the write is cancelled after the undo has already been asked for"
    )


@pytest.mark.unit
def test_the_page_writes_nothing_while_it_rebuilds_the_surface() -> None:
    """`clearBench` and every `pin` ask for the bench to be written down, and the surface is not
    the restored one until the last of them has run — so an undo that left writing switched on
    saves an empty bench over the thing it just restored."""
    static = pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "static"
    console = _code((static / "console.js").read_text(encoding="utf-8"))

    undo = console[console.index("async function undoBench(") :]
    undo = undo[: undo.index("\n}\n")]
    assert "restored = false;" in undo and "restored = true;" in undo
    assert (
        undo.index("restored = false;")
        < undo.index("clearBench()")
        < undo.index("restored = true;")
    ), "the surface is rebuilt outside the window in which writing is switched off"


@pytest.mark.unit
def test_only_a_deliberate_gesture_calls_a_move_deliberate() -> None:
    """Three gestures move a card because somebody said so — a drag, the arrow keys, and laying
    the bench out again. Everything else that moves one is the console fitting cards around each
    other as their bodies arrive.

    Asserted by counting the callers rather than by naming them, so that a fourth gesture is a
    decision somebody makes on purpose rather than a line that slips in: the failure this rule
    exists to stop was invisible from the outside, and it will be invisible again.
    """
    static = pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "static"
    console = _code((static / "console.js").read_text(encoding="utf-8"))

    assert console.count("moveWasDeliberate()") == 4, (
        "the gestures that count as somebody moving a card have changed; there is the definition "
        "and three callers — a drag, the arrow keys and tidying up"
    )
    settle = console[console.index("function settleOverlaps(") :]
    settle = settle[: settle.index("\n}\n")]
    assert "moveWasDeliberate" not in settle, (
        "the console laying cards out around each other counts as somebody moving them again, "
        "which is what made opening the page undoable"
    )


@pytest.mark.unit
def test_undo_is_on_the_key_everybody_presses_and_not_while_typing() -> None:
    """In a field Ctrl+Z has to undo the typing. A shortcut that ate a paragraph in order to move
    a card back would be worse than not having one."""
    static = pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "static"
    console = _code((static / "console.js").read_text(encoding="utf-8"))

    assert "'z' && (event.ctrlKey || event.metaKey) && !typing" in console

    templates = pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "templates"
    assert "data-undo" in (templates / "board.html").read_text(encoding="utf-8"), (
        "there is no control for it, so it exists only for people who already know it is there"
    )
