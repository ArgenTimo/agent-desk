"""A card that goes and finds out, and comes back with cards (01M1XDAD3DEH5N655TSKJJK18X).

«Карточка-исполнитель, которая сама пойдёт в интернет, разузнает всё что попросили и вернётся с
новыми карточками, основанными на полученных данных.»

An answer card is a paragraph, read whole or not at all. A finding on a card is taken when it is
wanted and left when it is not.
"""

from __future__ import annotations

import pathlib
import urllib.parse
from collections.abc import AsyncIterator
from typing import ClassVar

import pytest
from agent_desk import finding
from agent_desk.store.repo import Store
from agent_desk.web import blocks, routes

pytestmark = pytest.mark.unit

HERE = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture
async def desk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    yield store
    await store.close()


def _a_form(fields: dict[str, str]) -> object:
    body = urllib.parse.urlencode(fields).encode()

    class Filled:
        async def body(self) -> bytes:
            return body

        headers: ClassVar[dict[str, str]] = {
            "content-type": "application/x-www-form-urlencoded",
            "hx-request": "true",
        }

    return Filled()


# --- what comes back is read as findings ---------------------------------------------------------
def test_a_finding_a_line() -> None:
    said = "- the reader trusts the pid\n- the tail is read twice a tick\n"

    assert finding.read_findings(said) == [
        "the reader trusts the pid",
        "the tail is read twice a tick",
    ]


def test_bullets_however_they_were_written() -> None:
    assert len(finding.read_findings("* one thing\n• another thing\n- a third")) == 3


def test_a_reply_in_no_shape_at_all_is_no_findings() -> None:
    """Not one long finding: the answer is on its own card either way, and a bench that grew a card
    holding somebody's whole reply is the paragraph this exists to break up."""
    assert finding.read_findings("Here is what I found. It is quite involved.") == []


def test_only_so_many_come_back() -> None:
    """A bench is something a person arranges, and twenty cards at once is not an arrangement."""
    said = "\n".join(f"- finding number {n}" for n in range(40))

    assert len(finding.read_findings(said)) == finding.MOST


def test_the_request_says_what_shape_the_answer_has_to_be_in() -> None:
    """Added by the console rather than written into every button: a shape somebody has to
    remember to append is a shape half the buttons will be missing."""
    asked = finding.what_to_ask("what has changed in that library")

    assert asked.startswith("what has changed in that library")
    assert "one per line" in asked


# --- and it becomes cards on the bench it was pressed from ------------------------------------------
async def _an_answered_button(desk: Store, answer: str, brings_back: bool = True) -> object:
    thread = await desk.create_thread("a chat")
    block = await desk.create_block(
        thread_id=thread.id, kind="question", input="find out about it", thread_set_by="human"
    )
    await desk.sent_by_a_button(block.id, brings_back=brings_back)
    await desk.finish_block(block.id, answer)
    return await desk.block(block.id)


async def test_each_finding_becomes_a_card_on_that_bench(desk: Store) -> None:
    block = await _an_answered_button(
        desk, "- the library dropped python 3.9\n- its parser is now strict about tabs"
    )

    made = await blocks.bring_findings_back(desk, block)  # type: ignore[arg-type]

    assert len(made) == 2
    on_it = await desk.bench_cards(block.thread_id)  # type: ignore[union-attr]
    assert [one.label for one in on_it] == [
        "the library dropped python 3.9",
        "its parser is now strict about tabs",
    ]
    assert all("found by" in one.came for one in on_it)


async def test_a_finding_is_an_idea_so_it_outlives_the_chat(desk: Store) -> None:
    """Which is what the pool is for."""
    block = await _an_answered_button(desk, "- the library dropped python 3.9")

    await blocks.bring_findings_back(desk, block)  # type: ignore[arg-type]

    (one,) = await desk.ideas()
    assert one.text == "the library dropped python 3.9"
    assert one.author == "desk"


async def test_a_button_that_does_not_bring_back_makes_no_cards(desk: Store) -> None:
    """The button that was here before: it asks, and one answer card arrives."""
    block = await _an_answered_button(desk, "- a finding", brings_back=False)

    assert await blocks.bring_findings_back(desk, block) == []  # type: ignore[arg-type]
    assert await desk.bench_cards(block.thread_id) == []  # type: ignore[union-attr]


async def test_an_answer_that_never_arrived_makes_nothing(desk: Store) -> None:
    thread = await desk.create_thread("a chat")
    block = await desk.create_block(
        thread_id=thread.id, kind="question", input="find out", thread_set_by="human"
    )
    await desk.sent_by_a_button(block.id, brings_back=True)
    await desk.fail_block(block.id, "the engine was not there")

    said = await desk.block(block.id)
    assert await blocks.bring_findings_back(desk, said) == []  # type: ignore[arg-type]


async def test_a_finding_the_inbox_cannot_read_is_left_out_rather_than_written_unreadably(
    desk: Store,
) -> None:
    """The answer itself is still on its own card either way."""
    block = await _an_answered_button(desk, "- ...\n- the library dropped python 3.9")

    made = await blocks.bring_findings_back(desk, block)  # type: ignore[arg-type]

    assert len(made) == 1


async def test_what_was_already_on_the_bench_is_left_where_it_is(desk: Store) -> None:
    """A workbench somebody arranged is not rearranged by an answer arriving."""
    from agent_desk.store.repo import BenchCard

    block = await _an_answered_button(desk, "- the library dropped python 3.9")
    theirs = BenchCard(
        name="idea:mine",
        kind="idea",
        card_id="mine",
        label="mine",
        x=300,
        y=200,
        shown="open",
        spent=False,
        ord=0,
        by_hand=True,
    )
    await desk.keep_bench([theirs], thread_id=block.thread_id)  # type: ignore[union-attr]

    await blocks.bring_findings_back(desk, block)  # type: ignore[arg-type]

    first, second = await desk.bench_cards(block.thread_id)  # type: ignore[union-attr]
    assert (first.x, first.y, first.by_hand) == (300, 200, True)
    assert second.y > first.y


# --- the flag belongs to the block, not to the button it came from ---------------------------------
async def test_the_button_records_it_and_the_block_keeps_its_own_copy(desk: Store) -> None:
    """A button edited or deleted between the press and the answer must not change what happens to
    work already going — the same reason a run freezes the cards it was started with."""
    made = await desk.add_button_card("find out", "what changed in that library")
    await desk.set_button_card(made.id, label="find out", prompt="what changed", brings_back=True)

    kept = await desk.button_card(made.id)
    assert kept is not None and kept.brings_back

    thread = await desk.create_thread("a chat")
    block = await desk.create_block(
        thread_id=thread.id, kind="question", input="what changed", thread_set_by="human"
    )
    await desk.sent_by_a_button(block.id, brings_back=True)
    await desk.set_button_card(made.id, label="find out", prompt="what changed", brings_back=False)

    running = await desk.block(block.id)
    assert running is not None and running.brings_back


async def test_the_card_offers_it_and_says_what_it_does(desk: Store) -> None:
    made = await desk.add_button_card("find out", "what changed")

    said = (await routes.card(kind="button", id=made.id)).body.decode()

    assert 'name="brings_back"' in said
    assert "come back with cards" in said


def test_nothing_here_claims_to_browse() -> None:
    """Whether the engine behind an answer can reach the internet is the CLI's business and changes
    with its configuration. Naming Google Drive as a connector kind does not make this program able
    to read a Drive, and the same rule holds here."""
    card = (HERE / "agent_desk" / "web" / "templates" / "_card_button.html").read_text(
        encoding="utf-8"
    )
    on_screen = card[card.index('<label class="brings-back">') :]
    on_screen = on_screen[: on_screen.index("</label>")]

    for boast in ("internet", "browse", "web", "search the"):
        assert boast not in on_screen.lower()
