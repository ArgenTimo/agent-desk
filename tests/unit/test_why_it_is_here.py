"""Why a card is where it is, as a chain of facts (01M1XED1D8YAJYEYFY0FS74ND7).

"Тыкнуть в блокер, в статус, в предложенную ветку, в подсвеченную карточку — и получить не текст,
а цепочку… Это ровно то, чего требует пятое правило проекта, доведённое до конца: не просто «не
выдавать догадку за факт», а «на любое утверждение уметь показать, из чего оно следует»."

Half of it was already computed and thrown away. Nothing here works anything out.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk import because
from agent_desk.store.repo import Store
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


def _code() -> str:
    return "\n".join(
        line
        for line in CONSOLE.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("//")
    )


# --- every step says where it can be checked ------------------------------------------------------
def test_a_step_carries_the_column_it_was_read_out_of() -> None:
    """A chain whose steps are only sentences is a paragraph with line breaks, and somebody who
    does not believe one still has to take the console's word for it."""
    (only,) = because.on_the_bench("dropped it on the workbench")

    assert "dropped it on the workbench" in only.said
    assert only.from_ == "bench_card.came"


def test_the_way_a_card_arrived_is_dropped_in_whole() -> None:
    """The nineteen ways onto a bench are not all the same part of speech. "written down by an
    answer" does not survive "because somebody …", which is what the first version said and what
    the browser showed."""
    for came in (
        "dropped it on the workbench",
        "written down by an answer",
        "taken from the tools",
    ):
        (only,) = because.on_the_bench(came)

        assert only.said.endswith(f"— {came}.")


def test_a_reading_is_labelled_as_one() -> None:
    """`relates_to` is a short run's guess (051). A chain that presented it as a fact would be the
    thing this whole file is against."""
    steps = because.about_a_question(kind="question", relates_to=("idea:one",))

    assert "a reading, not a fact" in steps[-1].said


def test_a_long_sentence_is_shortened_rather_than_carried_whole() -> None:
    """Eight steps of transcript is not a chain."""
    (only,) = because.about_an_answer(asked="x" * 400)

    assert len(only.said) < 200
    assert only.said.endswith("”.") or "…" in only.said


def test_nothing_known_is_no_steps_rather_than_an_invented_one() -> None:
    assert because.about_an_answer(asked="a question") == [
        because.Step(said="It answers “a question”.", from_="block.input")
    ]


# --- and the chain the console assembles ----------------------------------------------------------
async def test_an_idea_says_how_it_was_written_down_and_what_it_is_part_of(desk: Store) -> None:
    whole = await desk.create_idea(
        text_="rework the console", summary="rework the console", source_kind="typed"
    )
    part = await desk.create_idea(text_="and a grid", summary="and a grid", source_kind="typed")
    await desk.set_idea_parent(part.id, whole.id)

    said = json.loads((await routes.why_it_is_here(name=f"idea:{part.id}")).body)["steps"]

    assert any("and a grid" in one["said"] for one in said)
    assert any("part of “rework the console”" in one["said"] for one in said)
    assert {one["from"] for one in said} <= {
        "idea.summary, idea.source_kind",
        "idea.parent_id",
        "idea.state",
        "block.input",
        "filing",
    }


async def test_an_idea_that_went_out_says_where(desk: Store) -> None:
    idea = await desk.create_idea(text_="a thought", summary="a thought", source_kind="typed")
    await desk.record_filing(
        idea_id=idea.id, tracker="git", issue_key="abc1234", url="https://example/abc1234"
    )

    said = json.loads((await routes.why_it_is_here(name=f"idea:{idea.id}")).body)["steps"]

    assert any("git abc1234" in one["said"] for one in said)


async def test_an_answer_names_the_two_cards_it_was_made_out_of(desk: Store) -> None:
    """Which was written down when somebody dragged them together (060), and thrown away until
    now."""
    thread = await desk.create_thread("a chat")
    block = await desk.create_block(
        thread_id=thread.id, kind="question", input="make one of these", thread_set_by="human"
    )
    await desk.made_out_of(block.id, ["idea:a", "idea:b"])

    said = json.loads((await routes.why_it_is_here(name=f"answer:{block.id}")).body)["steps"]

    assert any("made out of “idea:a” and “idea:b”" in one["said"] for one in said)


async def test_how_it_got_onto_the_bench_is_true_of_every_kind(desk: Store) -> None:
    """The line people actually want when they ask "why is this here"."""
    idea = await desk.create_idea(text_="a thought", summary="a thought", source_kind="typed")
    await desk.keep_bench(
        [
            routes.BenchCard(
                name=f"idea:{idea.id}",
                kind="idea",
                card_id=idea.id,
                label="a thought",
                x=10,
                y=10,
                shown="hint",
                spent=False,
                ord=0,
                came="picked it from the overview",
            )
        ],
        thread_id="a",
    )

    said = json.loads((await routes.why_it_is_here(name=f"idea:{idea.id}", thread="a")).body)[
        "steps"
    ]

    assert any(one["from"] == "bench_card.came" for one in said)


async def test_a_card_nobody_can_say_anything_about_gets_no_steps(desk: Store) -> None:
    """ "It does not say" is an answer. An invented reason is the failure the fifth rule names."""
    said = json.loads((await routes.why_it_is_here(name="session:nothing")).body)["steps"]

    assert said == []
    assert "Nothing here says why" in _code()


def test_it_is_offered_on_every_card() -> None:
    """Not only on the ones with a story: the answer "nothing says" is worth being able to ask
    for."""
    source = _code()

    assert "{ what: 'why is this here?', act: () => whyItIsHere(pin) }," in source
    assert "function whyItIsHere(" in source
