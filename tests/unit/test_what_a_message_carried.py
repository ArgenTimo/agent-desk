"""What a block says it carried, and whether that can be trusted (docs/stories/02).

docs/04-threads-and-blocks.md: *a block that cannot say what it carried is a block whose answer
cannot be explained afterwards.* A block that says the wrong thing is worse than one that says
nothing, because somebody will reason from it — and the largest message in the author's own store
records that it carried ninety-six things, of which twenty-two are distinct.

The cause was not a missing de-duplication. It was that "what does this message carry" had three
answers: the count beside the field, the lines the block recorded, and `on_the_bench`, which is the
only one that reaches a model and the only one nobody can see.
"""

from __future__ import annotations

import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk import telling
from agent_desk.store.repo import Store
from agent_desk.web import blocks

pytestmark = pytest.mark.unit

CONSOLE = (
    pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "static" / "console.js"
)
TEMPLATES = pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "templates"


@pytest.fixture
async def desk(tmp_path: pathlib.Path) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    yield store
    await store.close()


async def _an_idea(desk: Store, summary: str) -> str:
    idea = await desk.create_idea(
        text_=summary, summary=summary, source_kind="typed", author="human"
    )
    return idea.id


# --- the record is the reading the prompt was built from ------------------------------------------
async def test_a_card_named_twice_is_carried_once_and_recorded_once(desk: Store) -> None:
    """The two readings disagreed for exactly this input: four lines recorded, two cards asked
    with. Whatever put a name in the list twice, the record has to say what went."""
    one = await _an_idea(desk, "the first thought")
    two = await _an_idea(desk, "the second thought")
    targets = [f"idea:{one}", f"idea:{two}", f"idea:{one}", f"idea:{one}"]

    bench = await blocks.carried_from_the_bench(desk, [], targets)
    said = await blocks._context_lines(desk, [], targets, [], carried=bench.on_bench)

    assert len(bench.on_bench) == 2
    assert said == ["idea · the first thought", "idea · the second thought"]


async def test_the_record_does_not_list_what_the_prompt_left_out(desk: Store) -> None:
    """A block card and an answer card are the two halves of one exchange, already in the prompt as
    the thread's history; `on_the_bench` drops them for that reason. The record listed them anyway
    — and on a real console it listed them as `block · no longer on the board`, which reads like
    something went wrong rather than like a rule being followed."""
    one = await _an_idea(desk, "the only card that went")
    targets = [f"idea:{one}", "block:some-block", "answer:some-answer"]

    bench = await blocks.carried_from_the_bench(desk, [], targets)
    said = await blocks._context_lines(desk, [], targets, [], carried=bench.on_bench)

    assert "idea · the only card that went" in said
    assert not [line for line in said if line.startswith(("block ·", "answer ·"))]


async def test_the_record_is_in_the_order_the_prompt_numbered_them(desk: Store) -> None:
    """The digest numbers its cards and an answer says "3". A record in the browser's order rather
    than the prompt's is a record whose third line is not the model's third card."""
    first = await _an_idea(desk, "alpha")
    second = await _an_idea(desk, "beta")
    third = await _an_idea(desk, "gamma")
    targets = [f"idea:{third}", f"idea:{first}", f"idea:{second}"]

    bench = await blocks.carried_from_the_bench(desk, [], targets)
    said = await blocks._context_lines(desk, [], targets, [], carried=bench.on_bench)

    named = {first: "alpha", second: "beta", third: "gamma"}
    # Line by line against the names the digest numbered, in the order it numbered them.
    assert said == [f"idea · {named[name.split(':', 1)[1]]}" for name in bench.on_bench]
    # And that order is the one the targets arrived in, which is the bench's, not the store's.
    assert said == ["idea · gamma", "idea · alpha", "idea · beta"]


async def test_what_was_left_out_is_recorded_and_the_two_reasons_are_kept_apart(
    desk: Store,
) -> None:
    """ "Why did it not know about X" is the other half of "why did it say that", and a record that
    answered only one of them left the other to guesswork.

    A budget and a rule are not the same reason: reporting them as one number would tell somebody
    the digest was full when nothing had been cut."""
    one = await _an_idea(desk, "the card that went")
    targets = [f"idea:{one}", "block:b1", "answer:a1"]

    bench = await blocks.carried_from_the_bench(desk, [], targets)
    said = await blocks._context_lines(desk, [], targets, [], carried=bench.on_bench, left_out=4)

    assert (
        "not listed · 2 cards of this conversation, which travel as the thread's own history"
        in (said)
    )
    assert "not listed · 4 more cards that did not fit the digest" in said


async def test_a_record_with_nothing_missing_says_nothing_about_it(desk: Store) -> None:
    """A line printed on every message is a line people learn to skip."""
    one = await _an_idea(desk, "the only card")

    bench = await blocks.carried_from_the_bench(desk, [], [f"idea:{one}"])
    said = await blocks._context_lines(desk, [], [f"idea:{one}"], [], carried=bench.on_bench)

    assert said == ["idea · the only card"]


# --- and the count under the bench ----------------------------------------------------------------
def test_the_count_and_the_targets_come_from_one_place() -> None:
    """`carrying 37 cards` was counted from a selector that kept `.own` and did not require
    `[data-kind]`, while the field the message is built from used neither. A number beside a Send
    button that is not the number being sent is the shape of mistake this console exists to not
    make."""
    console = CONSOLE.read_text(encoding="utf-8")

    assert "function cardsBeingCarried(" in console
    targets = console[console.index("function pinnedTargets(") :]
    targets = targets[: targets.index("\n}\n")]
    assert "cardsBeingCarried()" in targets
    assert "querySelectorAll" not in targets, "the targets are gathered a second way"

    sync = console[console.index("function syncTargets(") :]
    sync = sync[: sync.index("\n}\n")]
    assert "cardsBeingCarried().length" in sync
    assert ".pin:not(.answer-card)" not in sync, (
        "the count is measured by a selector of its own again"
    )


# --- a long record shows its shape first ----------------------------------------------------------
def test_a_record_is_grouped_by_the_word_the_console_wrote() -> None:
    """Two dozen flat lines answer "what exactly"; the question somebody opening a record a week
    later has is "what was this about"."""
    said = "\n".join(
        [
            "idea · one",
            "idea · two",
            "session · a project (2 sessions)",
            "earlier · what was asked before",
            "not listed · 2 cards of this conversation",
        ]
    )

    assert telling.carried_by_kind(said) == [
        ("idea", ["one", "two"]),
        ("session", ["a project (2 sessions)"]),
        ("earlier", ["what was asked before"]),
        ("not listed", ["2 cards of this conversation"]),
    ]
    assert telling.carried_shape(said) == "idea 2 · session 1 · earlier 1 · not listed 1"


def test_a_line_that_is_a_sentence_keeps_its_place_and_gets_no_heading() -> None:
    """`pasted.as_lines` and the note somebody typed on the workbench are sentences rather than
    cards, and filing them under a heading they do not have would make them something they are
    not."""
    said = "\n".join(["idea · one", "what they wrote on the workbench:", "a paragraph they typed"])

    assert telling.carried_by_kind(said) == [
        ("idea", ["one"]),
        ("", ["what they wrote on the workbench:", "a paragraph they typed"]),
    ]
    # And the shape names only the kinds, because "" is not one.
    assert telling.carried_shape(said) == "idea 1"


def test_nothing_carried_is_no_shape_at_all() -> None:
    assert telling.carried_by_kind("") == []
    assert telling.carried_shape("") == ""


def test_the_record_on_the_page_shows_the_shape_and_the_groups() -> None:
    said = (TEMPLATES / "_blocks.html").read_text(encoding="utf-8")

    assert "| shape_of" in said, "a record of two dozen things opens as two dozen flat lines"
    assert "| by_kind" in said
    assert "carried-kind" in said
