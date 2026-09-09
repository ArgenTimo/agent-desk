"""A whole workbench as one document (01M1XED1DDTFFMFZTK1XA67TGV).

"Карточки, связи, поля, разрешения — одним файлом. «Вот всё, над чем я думал» становится одной
вещью, которую можно приложить к тикету, положить в репозиторий рядом с кодом или открыть через
месяц. Это сериализация уже существующих строк. И она же — резервная копия, которой сейчас нет
вообще."
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk import carrying
from agent_desk.store.repo import BenchCard, Store
from agent_desk.web import routes

pytestmark = pytest.mark.unit

HERE = pathlib.Path(__file__).resolve().parents[2]
CONSOLE = HERE / "agent_desk" / "web" / "static" / "console.js"


@pytest.fixture
async def desk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    yield store
    await store.close()


def _a_card(name: str, **rest: object) -> BenchCard:
    fields: dict[str, object] = {
        "name": name,
        "kind": name.partition(":")[0],
        "card_id": name.partition(":")[2],
        "label": name,
        "x": 20,
        "y": 20,
        "shown": "hint",
        "spent": False,
        "ord": 0,
    }
    fields.update(rest)
    return BenchCard(**fields)  # type: ignore[arg-type]


class _Sent:
    def __init__(self, said: object) -> None:
        self._said = said

    async def json(self) -> object:
        return self._said


# --- what travels ---------------------------------------------------------------------------------
def test_the_document_carries_the_arrangement_and_not_the_contents() -> None:
    """A card's body is fetched from the store when it is opened, so carrying it would be a second
    copy that goes stale — and a file somebody attaches to a ticket is a file somebody else reads,
    which is the surface docs/07-security.md says redacts before it renders."""
    said = carrying.as_document(
        [
            carrying.Card(
                name="idea:one",
                kind="idea",
                label="a thought",
                x=10,
                y=20,
                shown="hint",
                spent=False,
                came="typed",
            )
        ],
        [],
    )

    (only,) = said["cards"]
    assert set(only) == {"name", "kind", "label", "x", "y", "shown", "spent", "came"}
    assert "text" not in only and "answer" not in only and "said" not in only


def test_a_file_from_a_version_this_does_not_know_is_refused_by_name() -> None:
    """Not for migrating old files — there are none — but for refusing new ones clearly. An
    unversioned format is half-read into a bench of nothing the first time it changes."""
    assert carrying.read_document({"agent-desk": 99, "cards": []}) is None
    assert carrying.read_document({"cards": []}) is None
    assert carrying.read_document("a string") is None
    assert carrying.read_document({"agent-desk": carrying.VERSION, "cards": "not a list"}) is None


def test_a_document_survives_the_round_trip() -> None:
    cards = [
        carrying.Card(
            name="idea:a", kind="idea", label="A", x=1, y=2, shown="hint", spent=False, came="typed"
        ),
        carrying.Card(
            name="idea:b", kind="idea", label="B", x=3, y=4, shown="full", spent=True, came=""
        ),
    ]
    lines = [carrying.Line(from_name="idea:a", to_name="idea:b", kind="then", says="")]

    again = carrying.read_document(json.loads(json.dumps(carrying.as_document(cards, lines))))

    assert again is not None
    assert [one.name for one in again.cards] == ["idea:a", "idea:b"]
    assert again.cards[1].spent is True and again.cards[1].shown == "full"
    assert [(one.from_name, one.kind) for one in again.lines] == [("idea:a", "then")]


def test_a_line_to_a_card_the_document_does_not_carry_is_not_a_line() -> None:
    """It would draw from nothing to nothing, and there would be no telling it from a line whose
    card somebody took off."""
    said = {
        "agent-desk": carrying.VERSION,
        "cards": [{"name": "idea:a", "label": "A", "x": 0, "y": 0}],
        "lines": [{"from": "idea:a", "to": "idea:gone", "kind": "with", "says": ""}],
    }

    again = carrying.read_document(said)

    assert again is not None and again.lines == []


# --- and the console at both ends -----------------------------------------------------------------
async def test_the_file_holds_what_is_on_this_chat_s_bench(desk: Store) -> None:
    idea = await desk.create_idea(text_="a thought", summary="a thought", source_kind="typed")
    await desk.keep_bench(
        [_a_card(f"idea:{idea.id}", label="a thought", came="typed it")], thread_id="a"
    )

    said = json.loads((await routes.the_whole_workbench(thread="a")).body)

    assert said["agent-desk"] == carrying.VERSION
    assert [one["name"] for one in said["cards"]] == [f"idea:{idea.id}"]
    assert said["cards"][0]["came"] == "typed it"


async def test_a_line_between_two_cards_on_the_bench_travels(desk: Store) -> None:
    first = await desk.create_idea(text_="one", summary="one", source_kind="typed")
    second = await desk.create_idea(text_="two", summary="two", source_kind="typed")
    await desk.keep_bench(
        [_a_card(f"idea:{first.id}"), _a_card(f"idea:{second.id}", ord=1)], thread_id="a"
    )
    await desk.tie_cards(
        from_name=f"idea:{first.id}", to_name=f"idea:{second.id}", kind="then", thread_id="a"
    )

    said = json.loads((await routes.the_whole_workbench(thread="a")).body)

    assert len(said["lines"]) == 1
    assert said["lines"][0]["kind"] == "then"


async def test_opening_one_says_what_it_could_not_find(desk: Store) -> None:
    """A bench that quietly came back with one of two cards would be the fifth rule in a file
    format, so the number is the answer rather than a detail."""
    here = await desk.create_idea(text_="here", summary="here", source_kind="typed")
    said = {
        "agent-desk": carrying.VERSION,
        "into": "a",
        "cards": [
            {"name": f"idea:{here.id}", "label": "here", "x": 5, "y": 6},
            {"name": "idea:01M1NOTHERE", "label": "gone", "x": 7, "y": 8},
        ],
        "lines": [],
    }

    back = json.loads((await routes.open_a_workbench(_Sent(said))).body)

    assert back["opened"] == 1
    assert back["missing"] == ["idea:01M1NOTHERE"]
    (only,) = await desk.bench_cards("a")
    assert (only.x, only.y) == (5, 6)
    assert only.came == "opened from a file"


async def test_a_card_opened_from_a_file_counts_as_placed_by_hand(desk: Store) -> None:
    """Somebody arranged this bench once. A layout that ran on the next paint and swept it away
    would make opening a file useless (042)."""
    idea = await desk.create_idea(text_="a thought", summary="a thought", source_kind="typed")
    said = {
        "agent-desk": carrying.VERSION,
        "into": "a",
        "cards": [{"name": f"idea:{idea.id}", "label": "a", "x": 90, "y": 90}],
        "lines": [],
    }

    await routes.open_a_workbench(_Sent(said))

    (only,) = await desk.bench_cards("a")
    assert only.by_hand is True


async def test_a_file_that_is_not_one_opens_nothing(desk: Store) -> None:
    """Refused whole rather than read as far as it goes: a file half-opened onto somebody's
    workbench is worse than one that would not open."""
    answer = await routes.open_a_workbench(_Sent({"cards": [{"name": "idea:x"}]}))

    assert answer.status_code == 422
    assert await desk.bench_cards("a") == []


def test_the_browser_saves_the_file_and_not_the_console() -> None:
    """`config.py` names `data_dir` as the only tree this program writes to, and it is not
    somebody's Downloads folder."""
    source = CONSOLE.read_text(encoding="utf-8")
    start = source.index("async function saveTheBench(")
    body = source[start : source.index("\n}\n", start)]

    assert "URL.createObjectURL" in body and "link.download" in body
    assert "open(" not in body.replace("createObjectURL", "")


async def test_the_lines_come_back_too(desk: Store) -> None:
    """A workbench without its lines is a pile of cards. Only between two cards the file put back:
    a line to something that is not here would draw from nothing to nothing."""
    first = await desk.create_idea(text_="one", summary="one", source_kind="typed")
    second = await desk.create_idea(text_="two", summary="two", source_kind="typed")
    said = {
        "agent-desk": carrying.VERSION,
        "into": "a",
        "cards": [
            {"name": f"idea:{first.id}", "label": "one", "x": 0, "y": 0},
            {"name": f"idea:{second.id}", "label": "two", "x": 300, "y": 0},
        ],
        "lines": [
            {"from": f"idea:{first.id}", "to": f"idea:{second.id}", "kind": "then", "says": "next"}
        ],
    }

    await routes.open_a_workbench(_Sent(said))

    (only,) = [one for one in await desk.card_ties() if one.from_name == f"idea:{first.id}"]
    assert (only.kind, only.says) == ("then", "next")


async def test_every_kind_this_console_owns_a_row_for_is_looked_up(desk: Store) -> None:
    """A card whose row is gone must not come back as a card that opens into nothing. The kinds
    named by what they are rather than by a row — a session, a folder — come back as named, which
    is what the board already does for them."""
    button = await desk.add_button_card("run", "do it")
    check = await desk.add_check_card("clean", "is JSON")
    thread = await desk.create_thread("a chat")
    block = await desk.create_block(
        thread_id=thread.id, kind="question", input="x", thread_set_by="human"
    )
    said = {
        "agent-desk": carrying.VERSION,
        "into": "a",
        "cards": [
            {"name": button.name, "label": "run", "x": 0, "y": 0},
            {"name": check.name, "label": "clean", "x": 0, "y": 0},
            {"name": f"block:{block.id}", "label": "x", "x": 0, "y": 0},
            {"name": f"answer:{block.id}", "label": "x", "x": 0, "y": 0},
            {"name": "session:whatever", "label": "a session", "x": 0, "y": 0},
            {"name": "button:01M1NOTHERE", "label": "gone", "x": 0, "y": 0},
            {"name": "check:01M1NOTHERE", "label": "gone", "x": 0, "y": 0},
            {"name": "block:01M1NOTHERE", "label": "gone", "x": 0, "y": 0},
        ],
        "lines": [],
    }

    back = json.loads((await routes.open_a_workbench(_Sent(said))).body)

    assert back["opened"] == 5, "a session is named by what it is and comes back as named"
    assert sorted(back["missing"]) == [
        "block:01M1NOTHERE",
        "button:01M1NOTHERE",
        "check:01M1NOTHERE",
    ]


def test_a_row_that_is_not_a_card_is_skipped_rather_than_guessed_at() -> None:
    """A file somebody edited by hand, or one from a program that got the shape nearly right."""
    said = {
        "agent-desk": carrying.VERSION,
        "cards": [
            "not a card",
            {"no": "name"},
            {"name": "   "},
            {"name": "idea:a", "label": "A", "x": 0, "y": 0},
        ],
        "lines": ["not a line"],
    }

    again = carrying.read_document(said)

    assert again is not None
    assert [one.name for one in again.cards] == ["idea:a"]
    assert again.lines == []
