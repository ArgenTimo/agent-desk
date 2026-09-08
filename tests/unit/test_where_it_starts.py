"""The card an enquiry starts from (01M1XA1V6WT0F68ZEA40GQENYY).

"Создаётся карточка начала, например — описание проекта."

A question relates to something, and the first one relates to nothing that has been said yet.
Without a card to start from, the only thing a first question can hang off is the question before
it — which is a feed, and a feed is what scenario 9 exists to stop being.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import AsyncIterator
from urllib.parse import urlencode

import pytest
from agent_desk.store.repo import Store
from agent_desk.web import routes

pytestmark = pytest.mark.unit

HERE = pathlib.Path(__file__).resolve().parents[2]
CONSOLE = HERE / "agent_desk" / "web" / "static" / "console.js"
BOARD = HERE / "agent_desk" / "web" / "templates" / "board.html"


@pytest.fixture
async def store(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    made = Store(tmp_path / "agent-desk.db")
    await made.open()
    monkeypatch.setattr(routes, "store", made)
    yield made
    await made.close()


async def _through_the_stack(
    method: str, path: str, body: bytes = b"", content_type: bytes = b""
) -> tuple[int, str]:
    """One request through the real ASGI stack, the way the page sends it."""
    from agent_desk.web.app import asgi

    route, _, query = path.partition("?")
    headers = [(b"host", b"127.0.0.1:8787")]
    if body:
        headers += [(b"content-type", content_type), (b"content-length", str(len(body)).encode())]
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": route,
        "raw_path": route.encode(),
        "query_string": query.encode(),
        "root_path": "",
        "headers": headers,
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


async def _say_it_starts_here(name: str, thread: str = "a-chat") -> tuple[int, str]:
    body = urlencode({"name": name, "thread": thread}).encode()
    return await _through_the_stack(
        "POST", "/workbench/start", body, b"application/x-www-form-urlencoded"
    )


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


async def test_nobody_has_said_is_a_real_answer(store: Store) -> None:
    assert await store.began("a-chat") == ""


async def test_what_this_is_about_is_remembered(store: Store) -> None:
    await store.begin_with("a-chat", "step:1")
    assert await store.began("a-chat") == "step:1"


async def test_pointing_somewhere_else_replaces_it(store: Store) -> None:
    """One beginning per chat, and it is the primary key that says so rather than a rule somebody
    has to remember on the way past."""
    await store.begin_with("a-chat", "step:1")
    await store.begin_with("a-chat", "step:2")
    assert await store.began("a-chat") == "step:2"


async def test_each_chat_begins_where_it_begins(store: Store) -> None:
    """The same reason a bench belongs to a chat (044): two enquiries side by side are two
    enquiries, and one beginning between them is neither of theirs."""
    await store.begin_with("one", "step:1")
    await store.begin_with("two", "step:2")
    assert await store.began("one") == "step:1"
    assert await store.began("two") == "step:2"


async def test_a_beginning_survives_the_card_leaving_the_bench(store: Store) -> None:
    """Taking a card off and putting it back writes a new bench row for the same card. A foreign
    key would have deleted the beginning in the middle of a rearrangement nobody thought was
    destructive; the name outlives the arrangement it was made in."""
    await store.begin_with("a-chat", "step:1")
    await store.keep_bench([], thread_id="a-chat")
    assert await store.began("a-chat") == "step:1"


def test_the_beginning_is_written_down_before_it_is_marked() -> None:
    """A branch hangs off this card for a long time. A mark that lives only on the page is one
    somebody loses by reloading."""
    marking = _body("beginFrom")
    assert marking.index("fetch('/workbench/start'") < marking.index("markBeginning(name)")


def test_only_one_card_wears_the_mark() -> None:
    """Pointing at another card takes it off the first, without a second call to do it."""
    assert "classList.toggle('beginning', cardName(card) === name)" in _body("markBeginning")


def test_a_typed_beginning_is_an_object_holding_its_own_description() -> None:
    """The label is a name and names are short. What this is about is a description, and the role
    already has the field for it — inventing a sixth role for it is what adr/0011 closed."""
    making = _body("beginWith")
    assert "role: 'object'" in making
    assert "field: 'what'" in making
    assert "label: what.slice(0, 60)" in making


def test_a_card_already_on_the_bench_can_be_the_beginning() -> None:
    """A project dragged in is exactly the "описание проекта" of the example, and making a second
    card to say so would be two cards for one thing."""
    making = _body("beginWith")
    assert "chosen.length === 1 ? cardName(chosen[0]) : ''" in making


def test_the_mark_comes_back_with_the_bench() -> None:
    assert "markBeginning(beganWith())" in _body("restoreBench")
    assert "markBeginning(said.start" in _body("benchOfThisChat")
    assert 'id="bench-began"' in BOARD.read_text(encoding="utf-8")


# --- the routes -----------------------------------------------------------------------------------
async def test_the_page_can_say_where_this_starts(store: Store) -> None:
    status, said = await _say_it_starts_here("step:1")

    assert status == 200
    assert json.loads(said) == {"start": "step:1"}
    assert await store.began("a-chat") == "step:1"


async def test_the_bench_of_a_chat_comes_back_with_its_beginning(store: Store) -> None:
    """The mark travels with the surface it belongs to. Fetched separately it would arrive after
    the cards it goes on, and the card would flash unmarked on every chat switch."""
    await _say_it_starts_here("step:1")

    status, said = await _through_the_stack("GET", "/workbench/kept?thread=a-chat")

    assert status == 200
    assert json.loads(said)["start"] == "step:1"


async def test_a_request_with_no_card_in_it_marks_nothing(store: Store) -> None:
    """An empty name is a bug in the caller, not a way of clearing the beginning: writing it would
    put a row in that points at no card and reads, to anyone looking, like a beginning."""
    await _say_it_starts_here("step:1")

    status, said = await _say_it_starts_here("   ")

    assert status == 200
    assert json.loads(said) == {"start": "step:1"}
