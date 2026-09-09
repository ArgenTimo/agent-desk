"""Everything on the workbench, said in the input field (01M23NMJM7ZJYC309B7MWFDGF4).

«Абсолютное управление всем верстаком и любыми единицами на нём через поле ввода.»

Seven actions arranged what was there; three more finish it. Each was weighed against the same test
as the seven: a line drawn wrongly, a name typed wrongly and a role set wrongly all cost one press
of undo, because the surface an undo records is the cards, where they sit and the lines between
them. None of them starts anything or removes work.
"""

from __future__ import annotations

import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk import handling, roles, ties
from agent_desk.store.repo import Store
from agent_desk.web import blocks, routes

pytestmark = pytest.mark.unit

BENCH = ["step:one", "step:two", "idea:three"]


@pytest.fixture
async def desk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    yield store
    await store.close()


# --- what the vocabulary now covers --------------------------------------------------------------
def test_a_line_can_be_asked_for() -> None:
    asked = handling.read("join 1 2 then", BENCH)

    (line,) = asked.joined
    assert (line.from_name, line.to_name, line.kind) == ("step:one", "step:two", "then")


def test_a_line_that_wants_words_keeps_them() -> None:
    asked = handling.read("join 1 2 named what comes out of it", BENCH)

    (line,) = asked.joined
    assert (line.kind, line.says) == ("named", "what comes out of it")


def test_a_line_from_a_card_to_itself_is_not_a_line() -> None:
    """It says nothing and draws as a dot on top of the card."""
    assert handling.read("join 2 2 then", BENCH).empty


def test_a_line_with_an_end_off_the_bench_is_not_drawn() -> None:
    """One nobody can follow."""
    assert handling.read("join 1 9 then", BENCH).empty


def test_a_word_that_is_not_one_of_the_lines_is_not_an_action() -> None:
    """The vocabulary is closed, here as everywhere else on this bench."""
    assert handling.read("join 1 2 sideways", BENCH).empty


def test_a_card_can_be_named() -> None:
    asked = handling.read("name 1 read the failing logs", BENCH)

    (called,) = asked.named
    assert (called.name, called.label) == ("step:one", "read the failing logs")


def test_a_card_can_be_given_a_role() -> None:
    asked = handling.read("role 1 action", BENCH)

    (made,) = asked.given
    assert (made.name, made.role) == ("step:one", "action")


def test_a_role_that_is_not_one_of_the_five_is_not_an_action() -> None:
    assert handling.read("role 1 wizard", BENCH).empty


def test_the_instruction_teaches_exactly_what_the_reader_acts_on() -> None:
    """A shape parsed but not taught is a shape nobody tested; one taught but not parsed is one the
    model will produce and the console will drop."""
    said = handling.what_to_do(BENCH)

    assert "join 2 5 then" in said
    assert "name 3 what to call it" in said
    assert "role 3 action" in said
    for kind in ties.KINDS:
        assert kind in said
    for role in roles.ROLES:
        assert role in said


def test_all_three_survive_the_round_trip() -> None:
    """What the block stores is what the page and the store both read back."""
    asked = handling.read("join 1 2 then\nname 1 read the logs\nrole 2 result", BENCH)

    again = handling.read_json(handling.as_json(asked))

    assert again.joined == asked.joined
    assert again.named == asked.named
    assert again.given == asked.given


def test_a_block_written_before_these_existed_asks_for_none_of_them() -> None:
    """Which is what it asked for."""
    old = '{"handling": {"marked": [], "sorted": [], "folded": ["idea:a"]}}'

    again = handling.read_json(old)

    assert (again.joined, again.named, again.given) == ([], [], [])


def test_what_happened_is_readable_in_the_conversation() -> None:
    """A block whose answer is a blob of JSON says nothing to somebody scrolling back."""
    asked = handling.read("join 1 2 then\nname 1 read the logs\nrole 2 result", BENCH)

    said = handling.as_words(asked)

    assert "joined two cards: then" in said
    assert "named a card: read the logs" in said
    assert "made a card result" in said


# --- and what is written where -------------------------------------------------------------------
async def _asked(desk: Store, said: str, bench: list[str]) -> None:
    thread = await desk.create_thread("a chat")
    block = await desk.create_block(
        thread_id=thread.id, kind="handling", input="arrange it", thread_set_by="human"
    )
    await blocks._write_what_was_asked(desk, block, handling.read(said, bench))


async def test_a_line_asked_for_in_words_is_the_same_row_as_one_drawn_by_hand(
    desk: Store,
) -> None:
    """Through the same function the mouse uses, including its own refusals and the undo step it
    records."""
    await _asked(desk, "join 1 2 then", BENCH)

    (line,) = await desk.card_ties()
    assert (line.from_name, line.to_name, line.kind) == ("step:one", "step:two", "then")


async def test_a_role_asked_for_in_words_is_written_down(desk: Store) -> None:
    """It is a fact about a card, not a place on a surface: a card dragged to another bench takes
    its role with it, which a change made only on the page would not survive."""
    await _asked(desk, "role 1 action", BENCH)

    assert (await desk.card_roles()).get("step:one") == "action"


async def test_a_card_this_console_made_can_be_renamed(desk: Store) -> None:
    made = await desk.add_step_card("a step")

    await _asked(desk, "name 1 read the failing logs", [made.name])

    again = await desk.step_card(made.id)
    assert again is not None and again.label == "read the failing logs"


async def test_a_session_card_is_not_renamed(desk: Store) -> None:
    """Renaming one would be renaming somebody's session, which is a fact about their machine
    rather than about this bench."""
    await _asked(desk, "name 1 whatever I like", ["session:abc"])

    assert await desk.step_card("abc") is None


async def test_an_undo_takes_a_line_asked_for_in_words_back(desk: Store) -> None:
    """The whole reason these three are allowed in: one press.

    With the two cards on the bench, which they always are in a real request — the numbers the
    model was given are the cards on the surface, and a surface an undo records is the cards *and
    the lines between them* (041-bench-undo.sql).
    """
    from agent_desk.store.repo import BenchCard

    thread = await desk.create_thread("a chat")
    await desk.keep_bench(
        [
            BenchCard(
                name=name,
                kind="step",
                card_id=name.partition(":")[2],
                label=name,
                x=10,
                y=20 + 90 * at,
                shown="hint",
                spent=False,
                ord=at,
            )
            for at, name in enumerate(BENCH[:2])
        ],
        thread_id=thread.id,
    )
    block = await desk.create_block(
        thread_id=thread.id, kind="handling", input="arrange it", thread_set_by="human"
    )

    await blocks._write_what_was_asked(desk, block, handling.read("join 1 2 then", BENCH))
    assert len(await desk.card_ties()) == 1

    assert await desk.undo_bench(thread.id)
    assert await desk.card_ties() == []


def test_the_page_shows_the_three_without_writing_them_a_second_time() -> None:
    """The server has already written a line, a name and a role. The page reads the lines back and
    redraws what it renamed; a second writer of the same row is how two answers to one question
    appear."""
    here = pathlib.Path(__file__).resolve().parents[2]
    script = (here / "agent_desk" / "web" / "static" / "console.js").read_text(encoding="utf-8")
    code = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("//"))
    body = code[code.index("function applyArrangement") :]
    body = body[: body.index("\n}\n")]

    assert "said.joined" in body and "readLines()" in body
    assert "said.named" in body and "pin-label" in body
    assert "said.given" in body and "dataset.role" in body
    # Not drawn here: `drawLine` posts, and posting again would write the row a second time.
    assert "drawLine" not in body
