"""Draw what the project actually is (docs/stories/12).

«Нарисуй мне схему базы данных текущего проекта», «создай мне матрицу фич и что они закрывают в
текущем проекте» — «не делай фичи именно под эти 2 примера, а реализуй гораздо гибче».

So the two examples are tests of a general thing, and one test says the general thing does not
know about either of them.
"""

from __future__ import annotations

import pathlib
from collections.abc import AsyncIterator
from typing import Any

import pytest
from agent_desk import roles, telling
from agent_desk.answer import classify
from agent_desk.store.repo import Store
from agent_desk.web import blocks, routes

pytestmark = pytest.mark.unit

HERE = pathlib.Path(__file__).resolve().parents[2]

SCHEMA = """card 1 | table | users | db/schema.sql
- id uuid primary key
- email text unique
card 2 | table | orders | db/schema.sql
- id uuid primary key
- user_id uuid references users
- total numeric
2 -> 1 : belongs to
"""

MATRIX = """card 1 | feature | the shared view | agent_desk/web/shared.py
- a teammate reads the ideas
- a teammate adds one
card 2 | risk | a token on a page | docs/07-security.md
- redaction at the store boundary
card 3 | test | nothing a viewer opens renders a secret | tests/unit/test_shared.py
1 -> 2 : is exposed to
3 -> 1 : covers
"""


@pytest.fixture
async def desk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    yield store
    await store.close()


# --- reading a map, whatever it is a map of --------------------------------------------------------
@pytest.mark.parametrize("reply", [SCHEMA, MATRIX])
def test_any_map_is_read_the_same_way(reply: str) -> None:
    drawn = telling.read_map(reply)

    assert drawn.cards and drawn.lines
    assert all(one.kind and one.label for one in drawn.cards)
    assert all(one.read_from for one in drawn.cards)


def test_a_thing_carries_its_detail_and_where_it_was_read() -> None:
    drawn = telling.read_map(SCHEMA)

    orders = next(one for one in drawn.cards if one.label == "orders")
    assert orders.kind == "table"
    assert orders.lines == ("id uuid primary key", "user_id uuid references users", "total numeric")
    assert orders.read_from == "db/schema.sql"
    assert [(one.from_number, one.to_number, one.says) for one in drawn.lines] == [
        (2, 1, "belongs to")
    ]


def test_a_relation_to_something_not_drawn_is_dropped_and_so_is_one_to_itself() -> None:
    drawn = telling.read_map("card 1 | a | a\ncard 2 | b | b\n1 -> 9 : nowhere\n1 -> 1 : itself")

    assert drawn.lines == ()


def test_prose_is_not_a_map() -> None:
    assert telling.read_map("Here is your schema! It has a users table.\n- a stray line").empty


def test_a_drawing_bigger_than_the_bound_says_how_much_it_left_out() -> None:
    """A drawing that quietly stopped at sixty looks exactly like a project with sixty things."""
    reply = "\n".join(f"card {n} | module | m{n}" for n in range(1, telling.MOST_MAP_CARDS + 20))

    drawn = telling.read_map(reply)

    assert len(drawn.cards) == telling.MOST_MAP_CARDS
    assert drawn.left_out == 19
    assert "19 more" in telling.as_mapped(drawn, "a project")


def test_one_thing_cannot_become_a_file() -> None:
    reply = "card 1 | table | wide\n" + "\n".join(f"- column {n}" for n in range(100))

    assert len(telling.read_map(reply).cards[0].lines) == telling.MOST_CARD_LINES


# --- asking for one ---------------------------------------------------------------------------------
def test_the_prompt_names_the_project_and_forbids_memory() -> None:
    asked = telling.map_prompt("draw the database", "/home/dev/shop")

    assert "/home/dev/shop" in asked
    assert "you may not change anything" in asked
    assert "Never draw from memory" in asked
    assert "cannot: <what you looked for and did not find>" in asked
    assert "<where you read it>" in asked


def test_nothing_that_draws_a_map_knows_what_a_database_or_a_feature_matrix_is() -> None:
    """«Не делай фичи именно под эти 2 примера.» The vocabulary is general, and this is the test that
    says so: the words of the two examples appear in none of the code that draws a map — the prompt,
    the reader, the words said about a drawing, and the three functions that turn one into cards.

    The process prompt that predates this names a foreign key as an example of a relation, which is
    an example in a prompt and not a branch in the code; it is not what this is about.
    """
    telling_source = (HERE / "agent_desk" / "telling.py").read_text(encoding="utf-8")
    mapping = telling_source[telling_source.index("# --- a map of what a project is") :]
    mapping = (
        mapping[: mapping.index("\ndef as_mapped(")] + mapping[mapping.index("\ndef as_mapped(") :]
    )
    blocks_source = (HERE / "agent_desk" / "web" / "blocks.py").read_text(encoding="utf-8")
    drawing = "".join(
        blocks_source[blocks_source.index(f"async def {name}(") :].split("\n\n\nasync def ", 1)[0]
        for name in ("checkout_for", "cards_from_map", "_map_it")
    )
    for code in (mapping, drawing):
        executable = "\n".join(
            line
            for line in code.splitlines()
            if not line.strip().startswith(("#", '"""')) and "«" not in line
        ).lower()
        for word in ("database", "feature matrix", "foreign key", "column", "table"):
            assert f'"{word}' not in executable and f"'{word}" not in executable, (
                f"the map code carries a special case for {word!r}"
            )


def test_the_classifier_knows_a_map_is_a_drawing() -> None:
    said = classify.kind_prompt("нарисуй как устроен этот проект")

    assert "describing a *process*" in said
    assert "a *map* of what a project actually has" in said


# --- which project, and whether it can be read --------------------------------------------------------
async def test_with_nothing_chosen_the_drawing_reads_this_console(desk: Store) -> None:
    where, called = await blocks.checkout_for(desk, [])

    assert where == blocks.own_checkout()
    assert called == "agent-desk"


async def test_a_project_that_is_only_an_address_has_nothing_to_read(desk: Store) -> None:
    where, called = await blocks.checkout_for(desk, [], "origin:someone/far-away")

    assert where is None
    assert called == "someone/far-away"


async def test_a_project_seen_before_is_read_where_it_was_last_seen(
    desk: Store, tmp_path: pathlib.Path
) -> None:
    checkout = tmp_path / "shop"
    checkout.mkdir()
    await desk.note_project("origin:acme/shop", "acme/shop", str(checkout))

    where, called = await blocks.checkout_for(desk, [], "origin:acme/shop")

    assert where == checkout
    assert called == "acme/shop"


# --- drawing it -------------------------------------------------------------------------------------
def _answering(reply: str, asked: list[dict[str, Any]]) -> Any:
    async def fake(prompt: str, **how: Any) -> Any:
        asked.append({"prompt": prompt, **how})
        yield reply

    return fake


async def _block(desk: Store, text: str) -> Any:
    thread = await desk.create_thread("a subject")
    return await desk.create_block(
        thread_id=thread.id, kind="question", input=text, thread_set_by="human"
    )


async def test_a_map_is_drawn_from_the_project_it_is_about(
    desk: Store, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = tmp_path / "shop"
    checkout.mkdir()
    await desk.note_project("origin:acme/shop", "acme/shop", str(checkout))
    asked: list[dict[str, Any]] = []
    monkeypatch.setattr(blocks.session, "stream_answer", _answering(SCHEMA, asked))
    block = await _block(desk, "нарисуй схему базы данных текущего проекта")

    await blocks._draw_it(desk, block, project="origin:acme/shop")

    assert asked[0]["add_dirs"] == [checkout], "the run was not given the project to read"
    assert str(checkout) in asked[0]["prompt"]
    said, names = telling.read_drawn((await desk.block(block.id)).answer or "")
    assert len(names) == 2 and all(one.startswith("sketch:") for one in names)
    assert "Drew 2 things from acme/shop" in said
    first = await desk.sketch_card(names[0].split(":", 1)[1])
    assert first is not None and first.kind == "table"
    ties = [(one.kind, one.says) for one in await desk.card_ties()]
    assert ("named", "belongs to") in ties
    chosen = await desk.card_roles()
    assert all(roles.role_of("sketch", chosen.get(n, "")).name == "object" for n in names)


async def test_a_project_with_no_checkout_here_draws_a_process_or_nothing_it_cannot_see(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No directory, so no map is asked for; the process vocabulary still gets its turn, and its own
    refusal still stands for anything it cannot see."""
    asked: list[dict[str, Any]] = []
    monkeypatch.setattr(
        blocks.session, "stream_answer", _answering("cannot: the project is not here", asked)
    )
    block = await _block(desk, "draw the services")

    await blocks._draw_it(desk, block, project="origin:someone/far-away")

    assert "add_dirs" not in asked[0] or not asked[0]["add_dirs"]
    assert "I can only draw what is in front of me" in ((await desk.block(block.id)).answer or "")


async def test_a_map_the_project_cannot_answer_says_what_was_looked_for(
    desk: Store, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = tmp_path / "shop"
    checkout.mkdir()
    await desk.note_project("origin:acme/shop", "acme/shop", str(checkout))
    monkeypatch.setattr(
        blocks.session, "stream_answer", _answering("cannot: no migrations or models found", [])
    )
    block = await _block(desk, "draw the database")

    await blocks._draw_it(desk, block, project="origin:acme/shop")

    answer = (await desk.block(block.id)).answer or ""
    assert "I read acme/shop" in answer
    assert "no migrations or models found" in answer
    assert await desk.card_ties() == []


async def test_a_process_is_still_drawn_as_steps_when_that_is_what_came_back(
    desk: Store, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The map prompt offers the process form as its alternative, so a process described with a
    project chosen comes back as steps from the same call — which is how "draw the release process"
    keeps working, and keeps costing one model call."""
    checkout = tmp_path / "shop"
    checkout.mkdir()
    await desk.note_project("origin:acme/shop", "acme/shop", str(checkout))
    asked: list[dict[str, Any]] = []
    monkeypatch.setattr(
        blocks.session,
        "stream_answer",
        _answering(
            "action | test | run the tests\naction | fix | fix what failed\n1 -> 2 : then : red",
            asked,
        ),
    )
    block = await _block(desk, "нарисуй процесс релиза")

    await blocks._draw_it(desk, block, project="origin:acme/shop")

    assert len(asked) == 1, "a process reply was asked for a second time instead of read"
    _, names = telling.read_drawn((await desk.block(block.id)).answer or "")
    assert names and all(one.startswith("step:") for one in names)


# --- on the bench -----------------------------------------------------------------------------------
async def test_a_drawn_thing_shows_its_kind_detail_and_source_on_the_card(desk: Store) -> None:
    card = await desk.add_sketch_card(
        kind="table", label="orders", lines="id uuid\ntotal numeric", read_from="db/schema.sql"
    )

    page = (await routes.card("sketch", card.id)).body.decode()

    assert "table" in page and "orders" in page
    assert "<li>id uuid</li>" in page and "<li>total numeric</li>" in page
    assert "db/schema.sql" in page


async def test_a_question_asked_with_the_map_in_front_of_it_sees_the_detail(desk: Store) -> None:
    card = await desk.add_sketch_card(kind="table", label="orders", lines="id uuid\ntotal numeric")

    look = await blocks.on_the_bench(desk, [], [f"sketch:{card.id}"])

    (seen,) = look.cards
    assert seen.label == "orders"
    assert "table" in seen.said and "total numeric" in seen.said


def test_a_drawn_thing_is_a_thing_that_exists() -> None:
    assert roles.role_of("sketch").name == "object"


def test_a_map_arrives_joined_to_its_answer_once_and_laid_out_by_its_lines() -> None:
    """Every drawn card used to get its own `wrote` line from the answer: a map of sixty things is a
    fan of sixty lines hiding the relations the drawing exists to show."""
    console = (HERE / "agent_desk" / "web" / "static" / "console.js").read_text(encoding="utf-8")

    assert "drawn.length === 1" in console
    assert "function layOutDrawn(" in console
    body = console[console.index("function layOutDrawn(") :]
    body = body[: body.index("\n}\n")]
    assert "/workbench/arrange" in body
    assert ":not([data-moved])" in body, "a card somebody already moved is swept into the layout"
