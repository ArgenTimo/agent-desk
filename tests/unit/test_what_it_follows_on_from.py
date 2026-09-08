"""Which card a question follows on from (01M1XA1V76JMJEBWRDXCH2QPCZ).

"В зависимости от моего следующего вопроса он крепится либо к предыдущему ответу, либо к описанию,
либо вообще имеет другую область."

Three outcomes, and the third is the one that matters. Without "this is about something else" as a
possible answer, every enquiry slides into one long branch — each question read as following the
last, because the last is always *something* — and that is the feed the workbench exists to stop
being.

A guess is allowed here, which it is not anywhere else in this program: the cost of being wrong is
one line on a diagram that can be dragged, not somebody trusting a status that was inferred.
"""

from __future__ import annotations

import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk.answer import classify
from agent_desk.store.repo import BenchCard, Store

pytestmark = pytest.mark.unit

HERE = pathlib.Path(__file__).resolve().parents[2]
CONSOLE = HERE / "agent_desk" / "web" / "static" / "console.js"
BLOCKS_HTML = HERE / "agent_desk" / "web" / "templates" / "_blocks.html"
BLOCKS_PY = HERE / "agent_desk" / "web" / "blocks.py"


@pytest.fixture
async def store(tmp_path: pathlib.Path) -> AsyncIterator[Store]:
    made = Store(tmp_path / "agent-desk.db")
    await made.open()
    yield made
    await made.close()


async def _asked(store: Store, thread_id: str, said: str) -> object:
    return await store.create_block(
        thread_id=thread_id, kind="question", input=said, thread_set_by="human"
    )


def _card(name: str, label: str, kind: str = "answer") -> BenchCard:
    return BenchCard(
        name=name,
        kind=kind,
        card_id=name.partition(":")[2],
        label=label,
        x=10,
        y=10,
        shown="hint",
        spent=False,
        ord=0,
    )


# --- reading the reply ----------------------------------------------------------------------------
def test_a_number_names_that_card() -> None:
    assert classify.read_about("2", 3) == [2]


def test_none_is_an_answer_and_not_a_failure() -> None:
    assert classify.read_about("none", 3) == []


def test_a_number_outside_the_list_chooses_nothing() -> None:
    """A model that answers 7 out of 3 has not chosen a card, and drawing a line to whichever card
    happens to be third would be inventing one."""
    assert classify.read_about("7", 3) == []


def test_a_sentence_with_a_number_in_it_chooses_nothing() -> None:
    """The same mistake `read_choice` was written to stop: "it follows on from 2 of the three" is
    not an answer, and reading a digit out of it attaches a question to a card nobody named."""
    assert classify.read_about("it follows on from 2 of the three", 3) == []


def test_a_trailing_full_stop_is_not_a_different_answer() -> None:
    assert classify.read_about("1.", 3) == [1]


# --- a question about several cards at once -------------------------------------------------------
def test_several_numbers_name_several_cards() -> None:
    """ "Я могу сразу попросить нарисовать условно 5 частей… и задавать одновременно различные
    вопросы." A question about two of the parts has two cards above it, which is what makes an
    enquiry a graph rather than a tree."""
    assert classify.read_about("1,3", 3) == [1, 3]


def test_they_come_back_in_the_order_they_were_named() -> None:
    assert classify.read_about("3,1", 3) == [3, 1]


def test_one_card_named_twice_is_one_card() -> None:
    """Two lines between the same pair is one line drawn twice."""
    assert classify.read_about("1,1,2", 3) == [1, 2]


def test_the_out_of_range_ones_are_dropped_and_the_rest_kept() -> None:
    assert classify.read_about("2,9", 3) == [2]


def test_no_more_cards_than_a_person_can_read_a_diagram_of() -> None:
    """The product here is lines on a diagram, and six lines into one card is a picture nobody
    reads — which is the thing an enquiry bench is for. The instruction says three as well; this
    is enforced because an instruction is not a guarantee."""
    assert classify.read_about("1,2,3,4,5", 5) == [1, 2, 3]
    assert classify.MOST_CARDS == 3


async def test_a_reading_that_could_not_be_had_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """No line drawn is a bench somebody joins up themselves; a line from a failed reading is one
    they have to notice first."""

    async def broken(_prompt: str) -> AsyncIterator[str]:
        raise classify.AnswerFailed("no engine")
        yield ""  # pragma: no cover - unreachable, and the signature needs it

    monkeypatch.setattr(classify, "stream_answer", broken)
    assert await classify.about("why", ["a card", "another"]) == []


async def test_nothing_to_choose_between_costs_no_model_call() -> None:
    """Every ordinary bench is this one. A call per question for a choice with no candidates is a
    cost nobody asked for."""
    assert await classify.about("why", []) == []


# --- what is offered ------------------------------------------------------------------------------
def test_the_reader_is_shown_what_the_person_can_see() -> None:
    """A reading made from more than is on screen is one nobody watching can follow."""
    asked = classify.about_prompt("why", ["x" * 500])
    assert "x" * classify.CARD_CHARS in asked
    assert "x" * (classify.CARD_CHARS + 1) not in asked


def test_the_instruction_spends_its_words_on_the_third_outcome() -> None:
    asked = classify.about_prompt("why", ["a card", "another"])
    assert "none" in asked
    assert "subject of its own" in asked


# --- which cards are candidates -------------------------------------------------------------------
async def test_the_candidates_are_the_enquiry_and_not_the_whole_bench(store: Store) -> None:
    """A question follows on from something that was *said*. The sessions and ideas lying beside it
    are what it is being asked *with*, which the bench already draws as its own kind of line."""
    from agent_desk.web import blocks

    thread = await store.create_thread("an enquiry")
    await store.keep_bench(
        [
            _card("step:root", "the project", kind="step"),
            _card("answer:one", "because the reader is cached"),
            _card("idea:nine", "cache the probe results", kind="idea"),
            _card("session:abc", "rewriting the registry reader", kind="session"),
        ],
        thread_id=thread.id,
    )
    await store.begin_with(thread.id, "step:root")

    offered: list[list[str]] = []

    async def watch(_text: str, cards: list[str]) -> list[int]:
        offered.append(cards)
        return []

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(blocks.classifier, "about", watch)
    try:
        block = await _asked(store, thread.id, "why is that")
        await blocks._joins_on_to(store, block)
    finally:
        monkeypatch.undo()

    assert offered == [["the project", "because the reader is cached"]]


async def test_one_candidate_is_not_a_choice(store: Store) -> None:
    """With only the beginning there, everything follows on from it and a model is being asked to
    agree with the obvious — at the price of a call per question."""
    from agent_desk.web import blocks

    thread = await store.create_thread("an enquiry")
    await store.keep_bench([_card("step:root", "the project", kind="step")], thread_id=thread.id)
    await store.begin_with(thread.id, "step:root")

    called = False

    async def watch(_text: str, _cards: list[str]) -> list[int]:
        nonlocal called
        called = True
        return [1]

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(blocks.classifier, "about", watch)
    try:
        block = await _asked(store, thread.id, "why is that")
        await blocks._joins_on_to(store, block)
    finally:
        monkeypatch.undo()

    assert not called
    again = await store.block(block.id)
    assert again is not None and again.relates_to == ""


async def test_what_was_read_is_written_down(store: Store) -> None:
    from agent_desk.web import blocks

    thread = await store.create_thread("an enquiry")
    await store.keep_bench(
        [
            _card("step:root", "the project", kind="step"),
            _card("answer:one", "because of the cache"),
        ],
        thread_id=thread.id,
    )
    await store.begin_with(thread.id, "step:root")

    async def picks_the_answer(_text: str, _cards: list[str]) -> list[int]:
        return [2]

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(blocks.classifier, "about", picks_the_answer)
    try:
        block = await _asked(store, thread.id, "why is that")
        await blocks._joins_on_to(store, block)
    finally:
        monkeypatch.undo()

    again = await store.block(block.id)
    assert again is not None and again.relates_to == "answer:one"


async def test_nothing_read_leaves_no_line(store: Store) -> None:
    from agent_desk.web import blocks

    thread = await store.create_thread("an enquiry")
    await store.keep_bench(
        [
            _card("step:root", "the project", kind="step"),
            _card("answer:one", "because of the cache"),
        ],
        thread_id=thread.id,
    )
    await store.begin_with(thread.id, "step:root")

    async def picks_nothing(_text: str, _cards: list[str]) -> list[int]:
        return []

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(blocks.classifier, "about", picks_nothing)
    try:
        block = await _asked(store, thread.id, "a different subject")
        await blocks._joins_on_to(store, block)
    finally:
        monkeypatch.undo()

    again = await store.block(block.id)
    assert again is not None and again.relates_to == ""


# --- when it happens, and what the page does with it -----------------------------------------------
def test_it_is_read_before_the_answer_is_asked_for() -> None:
    """ "Как только система поймёт, к чему относится вопрос, он центрируется на этот блок… и готовит
    ответ." The order is the content of that sentence: somebody who can see what the question was
    taken to be about has time to disagree before an answer to the wrong question arrives."""
    source = BLOCKS_PY.read_text(encoding="utf-8")
    answering = source.index("async def _classify_and_answer")
    body = source[answering : source.index("\nasync def _joins_on_to", answering)]
    assert body.index("_joins_on_to(store, block)") < body.index("_run(store, block, prompt")


def test_the_line_is_drawn_once() -> None:
    """`syncBlocks` runs on every push, and a line pushed each time is the same line drawn forty
    deep by the end of a conversation."""
    source = "\n".join(
        line
        for line in CONSOLE.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("//")
    )
    start = source.index("function syncBlocks(")
    body = source[start : source.index("\n}\n", start)]
    assert "!joined.has(id)" in body
    assert "joined.add(id)" in body
    assert "says: 'follows on from'" in body


def test_no_line_is_drawn_to_a_card_that_is_not_here() -> None:
    """A name read from the store is a name, not a card: the card it meant may have been taken off
    the bench since. Every named card is looked for and the ones that are not there fall out."""
    source = CONSOLE.read_text(encoding="utf-8")
    assert (
        '.map((name) => surface.querySelector(`.pin[data-name="${CSS.escape(name)}"]`))' in source
    )
    assert ".filter(Boolean);" in source


def test_a_cleared_bench_forgets_that_it_drew_them() -> None:
    """Otherwise a conversation put back on a cleared bench comes back with no lines between its
    cards."""
    source = CONSOLE.read_text(encoding="utf-8")
    start = source.index("function clearBench(")
    assert "joined.clear()" in source[start : source.index("\n}\n", start)]


def test_the_reading_reaches_the_page_on_the_block() -> None:
    assert 'data-relates="{{ block.relates_to }}"' in BLOCKS_HTML.read_text(encoding="utf-8")


async def test_a_question_about_two_cards_is_joined_to_both(store: Store) -> None:
    """The whole of what makes this a graph. A tree would have had to pick one of them and say
    nothing about the other, which is the answer being wrong rather than being partial."""
    from agent_desk.web import blocks

    thread = await store.create_thread("an enquiry")
    await store.keep_bench(
        [
            _card("step:root", "the project", kind="step"),
            _card("answer:one", "the reader is cached"),
            _card("answer:two", "the writer is not"),
        ],
        thread_id=thread.id,
    )
    await store.begin_with(thread.id, "step:root")

    async def picks_both(_text: str, _cards: list[str]) -> list[int]:
        return [2, 3]

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(blocks.classifier, "about", picks_both)
    try:
        block = await _asked(store, thread.id, "how do those two fit together")
        await blocks._joins_on_to(store, block)
    finally:
        monkeypatch.undo()

    again = await store.block(block.id)
    assert again is not None and again.relates_to == "answer:one,answer:two"


def test_the_page_draws_a_line_from_each_of_them() -> None:
    source = "\n".join(
        line
        for line in CONSOLE.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("//")
    )
    start = source.index("function syncBlocks(")
    body = source[start : source.index("\n}\n", start)]
    assert "for (const card of onto) {" in body
    assert "from: cardName(card), to: `block:${id}`" in body
