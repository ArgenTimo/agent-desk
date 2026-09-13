"""Where each card on the workbench came from (045), and the bug found while showing it (046).

"Когда карточки начнут появляться из соединения, из раскрытия, из схемы, из ответа модели и из
карантина — вопрос «откуда это здесь» станет постоянным… Это ровно то же требование, которое в этом
проекте уже применено к статусам: показывать, на основании чего сказано."

There are ten ways a card gets onto the bench and no way to tell them apart was a surface where
"why is this here" had no answer.
"""

from __future__ import annotations

import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk.store.repo import BenchCard, Store

CONSOLE = (
    pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "static" / "console.js"
)


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


def _code() -> str:
    return "\n".join(
        line
        for line in CONSOLE.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("//")
    )


# --- the same card on two benches (046) ----------------------------------------------------------
@pytest.mark.unit
async def test_the_same_card_can_be_on_two_workbenches(desk: Store) -> None:
    """044 gave each chat a bench and left the primary key on `name` alone, so the second chat to
    hold a card failed on a uniqueness constraint.

    The page sends the whole surface, so that was not one card refused — the entire bench stopped
    saving, for as long as two chats both held it. And the write is fire-and-forget by design, so
    from the page a 500 here looks exactly like a console that is working.
    """
    await desk.keep_bench([_card("idea:same", came="dropped on the workbench")], thread_id="a")
    await desk.keep_bench([_card("idea:same", came="found with Ctrl+K")], thread_id="b")

    assert [(c.name, c.came) for c in await desk.bench_cards("a")] == [
        ("idea:same", "dropped on the workbench")
    ]
    assert [(c.name, c.came) for c in await desk.bench_cards("b")] == [
        ("idea:same", "found with Ctrl+K")
    ]


@pytest.mark.unit
async def test_taking_it_off_one_bench_leaves_it_on_the_other(desk: Store) -> None:
    await desk.keep_bench([_card("idea:same")], thread_id="a")
    await desk.keep_bench([_card("idea:same")], thread_id="b")

    await desk.keep_bench([], thread_id="a")

    assert await desk.bench_cards("a") == []
    assert [c.name for c in await desk.bench_cards("b")] == ["idea:same"]


@pytest.mark.unit
async def test_which_bench_is_half_of_which_card(desk: Store) -> None:
    """The key is the pair, asserted against the schema rather than against the behaviour above —
    that one would still pass with a unique index bolted on somewhere else."""
    from sqlalchemy import text

    async with desk.engine.connect() as conn:
        made = str(
            (
                await conn.execute(text("SELECT sql FROM sqlite_master WHERE name = 'bench_card'"))
            ).scalar()
        )

    assert "PRIMARY KEY (thread_id, name)" in made
    assert "name      TEXT    NOT NULL," in made, "name is a primary key of its own again"


# --- and where it came from ----------------------------------------------------------------------
@pytest.mark.unit
async def test_a_card_remembers_how_it_got_here(desk: Store) -> None:
    await desk.keep_bench(
        [_card("idea:one", came="written down by an answer", came_at=1_700_000)], thread_id="a"
    )

    (back,) = await desk.bench_cards("a")
    assert back.came == "written down by an answer"
    assert back.came_at == 1_700_000


@pytest.mark.unit
async def test_a_card_that_did_not_say_invents_nothing(desk: Store) -> None:
    """Absent is a real answer. A way of making a card that forgets to say leaves the line off
    rather than having one made up for it — the same argument the card descriptions ship under."""
    await desk.keep_bench([_card("idea:one")], thread_id="a")

    (back,) = await desk.bench_cards("a")
    assert back.came == ""
    assert back.came_at == 0


@pytest.mark.unit
async def test_it_survives_an_undo(desk: Store) -> None:
    """How a card got onto the bench is a fact about the card, so going back a step must not
    rewrite it."""
    await desk.keep_bench([_card("idea:one", came="picked from the overview")], thread_id="a")
    await desk.keep_bench(
        [_card("idea:one", came="picked from the overview", x=900)], thread_id="a", moved=True
    )

    await desk.undo_bench("a")

    (back,) = await desk.bench_cards("a")
    assert (back.came, back.x) == ("picked from the overview", 10)


# --- every way of making a card says which one it is ---------------------------------------------
@pytest.mark.unit
def test_every_way_of_putting_a_card_on_the_bench_says_which_one_it_was() -> None:
    """The phrase is written where the card is made, because that is the only place that knows.

    Counted rather than listed: the number is here so that adding a way onto the bench is a
    decision somebody makes on purpose — they have to come and change this line — rather than a
    card that quietly arrives with no answer to "why is this here". The count going up in the same
    commit as a new way in is the test working, not the test being in the way."""
    console = _code()

    said = console.count("came: '") + console.count("came: `")
    assert said == 20, (
        f"{said} places name where a card came from, and there are twenty ways in. A new one "
        "renders a card that cannot say why it is on the bench"
    )


@pytest.mark.unit
def test_the_words_are_the_ones_a_person_would_use() -> None:
    """docs/06-console.md: this window is often for somebody who does not read code. "kin:project"
    is the thing they were trying to avoid opening a terminal for."""
    console = _code()

    for words in (
        "dropped on the workbench",
        "picked from the overview",
        "written down by an answer",
        "found with Ctrl+K",
        "drawn from a description",
        "drawn as a step",
        "typed in as a folder",
    ):
        assert words in console, f"nothing says {words!r}"


@pytest.mark.unit
def test_restoring_a_bench_keeps_the_origin_rather_than_claiming_one() -> None:
    """Reloading a page is not a way of making a card, and "restored" as an answer to "why is this
    here" would be true of everything and useful for nothing."""
    console = _code()

    laying = console[console.index("function layOut(") :]
    laying = laying[: laying.index("\n}\n")]

    assert "came: one.came" in laying and "cameAt: one.came_at" in laying


@pytest.mark.unit
def test_what_it_was_made_from_is_not_stored_twice() -> None:
    """It is the line drawn to the card. Bringing an idea's project in draws a line from the
    project, an answer that writes an idea down joins the two — a second copy as text would
    disagree with the first the moment somebody rubbed a line out."""
    from agent_desk.store.repo import BenchCard as Card

    assert not [field for field in Card.model_fields if field.startswith("came_from")]


@pytest.mark.unit
def test_the_line_is_not_shown_on_a_folded_card() -> None:
    """A folded card is a title, and this is not the title."""
    css = (
        pathlib.Path(__file__).resolve().parents[2]
        / "agent_desk"
        / "web"
        / "static"
        / "console.css"
    ).read_text(encoding="utf-8")

    assert '.pin[data-view="hint"] .pin-came { display: none; }' in css


# --- and when it last changed (078, 01M25VH7AXXJ1AT09AHE77J2W4) ------------------------------------
def _function(console: str, head: str) -> str:
    body = console[console.index(head) :]
    return body[: body.index("\n}\n")]


@pytest.mark.unit
async def test_a_card_remembers_when_it_last_changed_and_it_survives_an_undo(desk: Store) -> None:
    """Story 5 asked for what arrived *or changed*. `came_at` never moves, so without a second time
    "changed" had nothing to be read from."""
    await desk.keep_bench([_card("idea:one", came_at=1_000, changed_at=5_000)], thread_id="a")
    await desk.keep_bench(
        [_card("idea:one", came_at=1_000, changed_at=5_000, x=900)], thread_id="a", moved=True
    )

    await desk.undo_bench("a")

    (back,) = await desk.bench_cards("a")
    assert (back.came_at, back.changed_at, back.x) == (1_000, 5_000, 10)


@pytest.mark.unit
async def test_a_card_that_never_changed_says_zero_rather_than_when_it_arrived(desk: Store) -> None:
    """Copying the arrival in would mark every restored card as changed the first time anybody
    looked away — a mark on most of the bench, which says nothing."""
    await desk.keep_bench([_card("idea:one", came_at=1_000)], thread_id="a")

    (back,) = await desk.bench_cards("a")
    assert back.changed_at == 0


@pytest.mark.unit
async def test_the_page_s_save_carries_when_a_card_changed() -> None:
    """The route builds the row field by field, so a field the page sends and the route forgets is
    dropped silently on every save."""
    from unittest.mock import AsyncMock, patch

    from agent_desk.web import routes

    class _Asked:
        async def json(self) -> dict[str, object]:
            return {
                "thread": "a",
                "cards": [
                    {
                        "name": "idea:one",
                        "kind": "idea",
                        "id": "one",
                        "at": {"x": 1, "y": 2},
                        "came_at": 1_000,
                        "changed_at": 5_000,
                    }
                ],
            }

    kept = AsyncMock()
    with patch.object(routes.store, "keep_bench", kept):
        await routes.keep_bench(_Asked())  # type: ignore[arg-type]

    (cards,) = kept.call_args.args
    assert cards[0].changed_at == 5_000


@pytest.mark.unit
def test_the_page_writes_it_down_and_reads_it_back() -> None:
    console = _code()

    assert "changed_at: Number(pin.dataset.changedAt) || 0" in _function(
        console, "function benchState("
    )
    assert "changedAt: one.changed_at" in _function(console, "function layOut(")


@pytest.mark.unit
def test_a_card_is_marked_changed_only_where_its_content_is_replaced() -> None:
    """One writer, called from the three places a card that was already here is rewritten. Drawing,
    moving, folding and restoring are not the card changing, and a stamp there would put the mark on
    everything."""
    console = _code()

    assert console.count("changed(") - console.count("function changed(") == 3
    assert console.count("dataset.changedAt = ") == 2, "a second writer besides `pin` and `changed`"
    assert "changed(holder)" in _function(console, "async function runTheCheck(")
    for untouched in ("function setView(", "function layOut(", "function nameItProperly("):
        assert "changed(" not in _function(console, untouched), untouched


@pytest.mark.unit
def test_a_step_is_a_change_only_when_it_moves_from_a_state_already_drawn() -> None:
    """The first paint after a load finds every step with no previous state. Counting that as a
    change would stamp every step card on every reload."""
    console = _code()

    assert "if (stepWas !== undefined && stepWas !== pin.dataset.step) changed(pin);" in console


@pytest.mark.unit
def test_the_chip_says_arrived_and_changed_apart_and_counts_a_card_once() -> None:
    marking = _function(_code(), "function markWhatArrivedSince(")

    assert "const isChanged = !isNew &&" in marking
    assert "`${fresh} arrived`" in marking and "`${moved} changed`" in marking
    assert "'changed-since'" in _function(_code(), "function forgetWhatArrived(")


@pytest.mark.unit
def test_how_long_ago_is_worked_out_when_somebody_looks() -> None:
    """Written when the card is made and read when the card is opened. A tab left open for an hour
    would otherwise still say "just now", which is the one thing a line about where something came
    from must not do."""
    console = _code()

    view = console[console.index("function setView(") :]
    view = view[: view.index("\n}\n")]

    assert "writeCame(holder)" in view
