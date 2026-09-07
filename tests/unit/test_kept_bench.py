"""The workbench survives a reload, because it is a thing in the store (040-bench.sql).

Before this, `agent-desk:bench-layout` held where every card *was* and nothing held *which cards*,
so a reload restored the positions of an empty surface. These tests are about the half that was
missing and about the two ways restoring it can go wrong: writing an empty bench over a full one
before the page has drawn itself, and drawing a second copy of a card the conversation brings back
on its own.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk.store.repo import MOST_CARDS_ON_A_BENCH, BenchCard, Store
from agent_desk.web import routes

STATIC = pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "static"
TEMPLATES = pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "templates"


def _code(script: str) -> str:
    """The script with its whole-line comments taken out.

    A rule about what the code may not do, checked as a substring, trips over the comment that
    explains the rule — this file's first draft failed on its own paragraph about the key it was
    forbidding. Every comment in `console.js` that says anything is a whole line, so dropping
    those leaves the statements.
    """
    return "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("//"))


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


async def _post_json(path: str, payload: object) -> tuple[int, str]:
    """One JSON POST through the real ASGI stack, the way the page sends it."""
    from agent_desk.web.app import asgi

    body = json.dumps(payload).encode()
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"127.0.0.1:8787"),
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ],
        "client": ("127.0.0.1", 54321),
        "server": ("127.0.0.1", 8787),
    }
    sent: list[dict[str, object]] = []

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    await asgi(scope, receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    said = b"".join(bytes(m.get("body", b"")) for m in sent if m["type"] == "http.response.body")
    return int(start["status"]), said.decode()  # type: ignore[arg-type]


# --- the store ------------------------------------------------------------------------------------
@pytest.mark.unit
async def test_a_card_comes_back_where_it_was_left(desk: Store) -> None:
    await desk.keep_bench([_card("idea:one", x=140, y=260, shown="metadata", spent=True)])

    (back,) = await desk.bench_cards()
    assert (back.x, back.y) == (140, 260)
    assert back.shown == "metadata"
    assert back.spent is True


@pytest.mark.unit
async def test_the_bench_is_replaced_rather_than_added_to(desk: Store) -> None:
    """A card taken off has to actually go.

    The page sends the whole surface, so the write is a replacement. Storing it as an upsert would
    leave every card ever placed on the bench in the table, and each one would come back on the
    next reload — the exact failure this table exists to fix, running backwards.
    """
    await desk.keep_bench([_card("idea:one"), _card("idea:two")])
    await desk.keep_bench([_card("idea:two")])

    assert [card.name for card in await desk.bench_cards()] == ["idea:two"]


@pytest.mark.unit
async def test_an_emptied_bench_is_stored_as_empty(desk: Store) -> None:
    """Clearing the surface and reloading must not bring it back."""
    await desk.keep_bench([_card("idea:one")])
    await desk.keep_bench([])

    assert await desk.bench_cards() == []


@pytest.mark.unit
async def test_a_bench_past_the_cap_is_cut_rather_than_refused(desk: Store) -> None:
    """A card-making loop upstream fills a table slowly instead of filling the disk.

    Cut rather than refused, because refusing would lose the arrangement somebody does have in
    order to protest about the one they do not.
    """
    await desk.keep_bench([_card(f"idea:{n}") for n in range(MOST_CARDS_ON_A_BENCH + 50)])

    assert len(await desk.bench_cards()) == MOST_CARDS_ON_A_BENCH


@pytest.mark.unit
async def test_the_bench_comes_back_in_the_order_it_was_stacked(desk: Store) -> None:
    """The order the page sent, not the alphabet: cards overlap, and which one is on top is a fact
    about the surface somebody arranged."""
    await desk.keep_bench([_card("idea:zeta"), _card("idea:alpha")])

    assert [card.name for card in await desk.bench_cards()] == ["idea:zeta", "idea:alpha"]


# --- the route ------------------------------------------------------------------------------------
@pytest.mark.unit
async def test_the_page_can_write_the_bench_down(desk: Store) -> None:
    status, said = await _post_json(
        "/workbench/kept",
        {
            "cards": [
                {
                    "name": "idea:one",
                    "kind": "idea",
                    "id": "one",
                    "label": "a thought",
                    "at": {"x": 12, "y": 34},
                    "shown": "hint",
                    "spent": False,
                }
            ]
        },
    )

    assert status == 200
    assert '"kept": 1' in said.replace('"kept":1', '"kept": 1')
    (back,) = await desk.bench_cards()
    assert (back.name, back.card_id, back.label, back.x, back.y) == (
        "idea:one",
        "one",
        "a thought",
        12,
        34,
    )


@pytest.mark.unit
async def test_one_unreadable_card_does_not_lose_the_others(desk: Store) -> None:
    """Losing a card's position is a card in the wrong place; refusing the write is the whole
    arrangement lost, which is the failure the route exists to stop."""
    status, _ = await _post_json(
        "/workbench/kept",
        {
            "cards": [
                {"name": "idea:one", "kind": "idea", "id": "one", "at": {"x": 1, "y": 2}},
                {"name": "idea:broken", "kind": "idea", "id": "broken", "at": None},
                {"kind": "idea", "id": "nameless", "at": {"x": 3, "y": 4}},
                {"name": "idea:gone", "kind": "idea", "id": "gone", "at": {"x": 3}},
                {"name": "idea:two", "kind": "idea", "id": "two", "at": {"x": 3, "y": 4}},
            ]
        },
    )

    assert status == 200
    assert [card.name for card in await desk.bench_cards()] == ["idea:one", "idea:two"]


@pytest.mark.unit
async def test_a_body_that_is_not_a_bench_at_all_empties_nothing_it_should_not(desk: Store) -> None:
    """A malformed body clears the bench, and that is the correct reading of "here is my bench".

    It is asserted rather than left to chance because the alternative — treating nonsense as "no
    change" — would make a page that has stopped sending cards indistinguishable from one that has
    none, and the store would quietly keep a surface nobody is looking at.
    """
    await desk.keep_bench([_card("idea:one")])
    status, _ = await _post_json("/workbench/kept", ["not", "a", "bench"])

    assert status == 200
    assert await desk.bench_cards() == []


@pytest.mark.unit
async def test_the_page_carries_the_bench_it_was_left(desk: Store) -> None:
    """Rendered into the page, not fetched by it: the script writes the bench back as soon as it
    has drawn it, and a write that overtook a fetch would save an empty surface over a full one."""
    await desk.keep_bench([_card("idea:one", label="a thought worth keeping", x=99, y=7)])

    page = await routes.render_page()

    said = page[page.index('id="bench-kept"') :]
    said = said[said.index(">") + 1 : said.index("</script>")]
    (only,) = json.loads(said)
    assert only["name"] == "idea:one"
    assert only["label"] == "a thought worth keeping"
    assert (only["x"], only["y"]) == (99, 7)


@pytest.mark.unit
async def test_a_label_cannot_close_the_script_tag_it_is_written_into(desk: Store) -> None:
    """A card's label is a session title or an idea's summary — text this console did not write."""
    await desk.keep_bench([_card("idea:one", label="</script><script>alert(1)</script>")])

    page = await routes.render_page()

    assert "<script>alert(1)</script>" not in page


# --- the page ------------------------------------------------------------------------------------
@pytest.mark.unit
def test_nothing_is_written_back_before_the_surface_has_been_restored() -> None:
    """The first thing the script does after the page opens is draw the conversation, and every
    card it draws asks for the bench to be written down. Without the guard, the empty surface of
    the first millisecond is saved over the bench somebody left — and the feature deletes the data
    it exists to keep, silently, on every single load."""
    console = (STATIC / "console.js").read_text(encoding="utf-8")

    write = console[console.index("function rememberLayout(") :]
    write = write[: write.index("\n}\n")]
    assert "if (!restored) return;" in write, "the bench is written before it has been restored"

    restore = console[console.index("function restoreBench(") :]
    restore = restore[: restore.index("\n}\n")]
    assert "restored = true;" in restore, "nothing ever turns the write back on"

    assert console.index("restoreBench();") < console.index("showActiveThread();\nemptyOrNot();"), (
        "the conversation is drawn before the bench is restored, so the first card it places "
        "writes an empty surface over the stored one"
    )


@pytest.mark.unit
def test_the_conversation_is_not_drawn_twice() -> None:
    """A block card is stored for its position only. The thread brings it back by itself, and
    re-creating it from the store as well would put two of every question on the surface."""
    console = (STATIC / "console.js").read_text(encoding="utf-8")

    restore = console[console.index("function restoreBench(") :]
    restore = restore[: restore.index("\n}\n")]
    assert "one.kind === 'block'" in restore and "continue" in restore, (
        "restoring the bench re-creates the block cards the conversation already brings back"
    )


@pytest.mark.unit
def test_a_note_typed_on_the_bench_is_not_quietly_kept() -> None:
    """Its own placeholder promises it "is gone when this tab is". A promise that specific is not
    broken by a schema."""
    console = (STATIC / "console.js").read_text(encoding="utf-8")

    state = console[console.index("function benchState(") :]
    state = state[: state.index("\n}\n")]
    assert "'note'" in state, "a note is now stored, against what its own placeholder says"
    for gesture in (":not(.copy)", ":not(.collection)"):
        assert gesture in state, f"a card that is only part of a gesture ({gesture}) is stored"


@pytest.mark.unit
def test_the_layout_no_longer_lives_in_the_browser() -> None:
    """Two homes for one fact is one home that drifts. The bench is in the store; a browser that
    still held half of it would restore a layout for cards the store had never heard of."""
    console = _code((STATIC / "console.js").read_text(encoding="utf-8"))

    assert "agent-desk:bench-layout" not in console, (
        "the layout is still written to localStorage as well as to the store"
    )
    recall = console[console.index("function recallLayout(") :]
    recall = recall[: recall.index("\n}\n")]
    assert "keptBench()" in recall, "the positions no longer come from what the store was left"


@pytest.mark.unit
def test_the_bench_the_page_was_handed_is_in_the_page() -> None:
    """`tojson` rather than a string: the escaping is what stops a card's label ending the tag."""
    board = (TEMPLATES / "board.html").read_text(encoding="utf-8")

    assert 'id="bench-kept"' in board
    assert "kept | tojson" in board


@pytest.mark.unit
def test_the_page_sends_its_bench_unreshaped() -> None:
    """One shape between the page and the route, because two shapes disagreed.

    The first version of this reshaped the cards on the way out: it spread the position into the
    card *and* left the `at` it came from beside it, the route read that `at` as a clock, and every
    card in every message was thrown away for being unreadable. Nothing failed. The console saved
    an empty bench, perfectly, on every write — and only a browser found it.

    So the payload is `benchState()` verbatim, and this is the assertion that keeps it that way:
    the moment somebody maps over it on the way out there are two shapes again, and the second one
    is the one nobody tests.
    """
    console = _code((STATIC / "console.js").read_text(encoding="utf-8"))

    write = console[console.index("function rememberLayout(") :]
    write = write[: write.index("\n}\n")]
    assert "cards: benchState()" in write, (
        "the bench is reshaped between being read and being sent, which is where the two shapes "
        "that disagreed came from"
    )
