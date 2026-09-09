"""A CV, a job description, some nuances, and a plan (01M1XBY9GFPJQMHFPVGF004390).

«Похожий сценарий на алхимию — добавляю своё резюме, добавляю карточку с описанием вакансии мечты,
добавляю различные нюансы тоже в карточках, прошу составить план трудоустройства.»

The scenario is a walk through machinery that already exists, and this is the test that says so end
to end: three things somebody wrote on the bench, one question, and everything they wrote in front
of it. Written as a scenario rather than as three unit tests because the failure it guards against
is not in any one part — it is one of the three quietly not travelling.
"""

from __future__ import annotations

import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk.answer import session
from agent_desk.store.repo import Store
from agent_desk.web import blocks, routes

pytestmark = pytest.mark.unit

HERE = pathlib.Path(__file__).resolve().parents[2]

# What somebody puts on the bench, in the order they put it there. Three cards, and the console
# joins them the way the page does — one field per card, sent together.
CV = "Eight years of Python. Two of them on a payments team. I do not want to manage people."
JOB = "Staff engineer, remote, a product with users, somewhere that writes things down."
NUANCE = "I can start in March, not before. I will not relocate."
WROTE = "\n\n---\n\n".join([CV, JOB, NUANCE])


@pytest.fixture
async def desk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    # Nothing is asked of a model here: what this walks is what the console carries, and a run
    # would make the test about an engine that is not installed on a machine running the suite.
    monkeypatch.setattr(blocks.runs, "start", lambda *a, **k: None)
    yield store
    await store.close()


async def test_everything_written_on_the_bench_reaches_the_question(desk: Store) -> None:
    """The whole scenario. A plan built from two of the three is a plan that is wrong in a way
    nobody reading it can see."""
    thread = await desk.create_thread("a chat")

    made = await blocks.submit(
        desk,
        "Draw me up a plan for getting hired.",
        [],
        thread_id=thread.id,
        notes_=WROTE,
    )

    block = await desk.block(made.id)
    assert block is not None
    for said in (CV, JOB, NUANCE):
        assert said in (block.context or "")


async def test_what_they_wrote_is_named_as_theirs(desk: Store) -> None:
    """A card this console read and a paragraph a person typed are different evidence, and the
    prompt says which is which."""
    thread = await desk.create_thread("a chat")

    made = await blocks.submit(desk, "a plan, please", [], thread_id=thread.id, notes_=WROTE)

    block = await desk.block(made.id)
    assert block is not None
    assert "what they wrote on the workbench:" in (block.context or "")


def test_it_arrives_in_the_prompt_under_a_heading_that_says_whose_it_is() -> None:
    """ "Ideas the person carried into this question" — they are not evidence of anything an agent
    did, and the prompt says so (agent_desk/answer/session.py)."""
    prompt = session.build_prompt(
        "Draw me up a plan for getting hired.", board=[], history=[], notes=[WROTE]
    )

    assert "Ideas the person carried into this question" in prompt
    for said in (CV, JOB, NUANCE):
        assert said in prompt


async def test_a_bench_with_nothing_written_on_it_carries_nothing(desk: Store) -> None:
    """A heading over nothing is a heading the model reasons about."""
    thread = await desk.create_thread("a chat")

    made = await blocks.submit(desk, "a plan, please", [], thread_id=thread.id, notes_="   ")

    block = await desk.block(made.id)
    assert block is not None
    assert "what they wrote on the workbench" not in (block.context or "")


def test_the_bench_has_a_way_to_write_one_of_these_cards() -> None:
    """ "Добавляю карточку" — a card somebody writes themselves, not one this console read from
    somewhere. Three of them are three cards, and what is typed into each travels."""
    board = (HERE / "agent_desk" / "web" / "templates" / "board.html").read_text(encoding="utf-8")
    script = (HERE / "agent_desk" / "web" / "static" / "console.js").read_text(encoding="utf-8")
    code = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("//"))
    body = code[code.index("function ownBlockText()") :]
    body = body[: body.index("\n}\n")]

    assert 'data-add="note"' in board
    # Every unspent note on the bench, not the one that has focus.
    assert "querySelectorAll" in body
    assert "join" in body
