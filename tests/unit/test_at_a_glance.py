"""A proposal the desk wrote has to be readable without opening the card.

The idea this serves: "Предложенная идея должна быть написана так, чтобы её понимали с первого
взгляда." If understanding a proposal means expanding it and reading a paragraph, the work of
getting into its context has been moved onto the person — and that work is what the proposal was
supposed to do for them.
"""

from __future__ import annotations

import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk.ideas import inbox
from agent_desk.store.repo import Store
from agent_desk.web import blocks

pytestmark = pytest.mark.unit

GOOD = "the folder cards could name the files they were read from"


@pytest.fixture
async def store(tmp_path: pathlib.Path) -> AsyncIterator[Store]:
    made = Store(tmp_path / "agent-desk.db")
    await made.open()
    yield made
    await made.close()


def test_a_line_that_says_what_and_why_passes() -> None:
    assert inbox.unclear(GOOD) == ""


def test_a_subject_with_nothing_said_about_it_is_not_a_proposal() -> None:
    # A heading. The reader knows the topic and not the suggestion.
    why = inbox.unclear("LLM pipelines")
    assert "names a subject" in why


def test_a_line_the_card_would_clip_is_refused() -> None:
    # The card is one line with an ellipsis, and the end of a sentence is where the reason lives.
    why = inbox.unclear("x" * (inbox.SUMMARY_CHARS + 1))
    assert str(inbox.SUMMARY_CHARS) in why


def test_the_longest_line_the_card_shows_whole_is_allowed() -> None:
    # The boundary belongs to the side that fits: it is the length the card renders, not the first
    # length it cannot.
    line = ("word " * 40)[: inbox.SUMMARY_CHARS].strip() + " end"
    assert len(line[: inbox.SUMMARY_CHARS]) == inbox.SUMMARY_CHARS
    assert inbox.unclear(line[: inbox.SUMMARY_CHARS]) == ""


@pytest.mark.parametrize("tail", [":", "…", "...", ",", "—"])
def test_a_line_that_hands_the_sentence_to_the_body_is_refused(tail: str) -> None:
    assert "trails off" in inbox.unclear(f"three things worth doing about the pool{tail}")


def test_a_line_pointing_at_the_body_is_refused() -> None:
    assert "points at the body" in inbox.unclear("rework the idea pool, details below")


def test_a_truncated_first_line_cannot_reach_the_pool() -> None:
    # Not a hypothetical: `fallback_summary` is what puts the ellipsis there, so any desk proposal
    # whose first line runs past SUMMARY_CHARS arrives already cut.
    long_first_line = "the console could " + "keep going and " * 20 + "stop"
    assert inbox.fallback_summary(long_first_line).endswith("…")


async def test_the_desk_cannot_record_a_proposal_nobody_can_read(store: Store) -> None:
    with pytest.raises(ValueError, match="at a glance"):
        await inbox.capture(store, "a proposal", author="desk")


async def test_a_readable_proposal_is_recorded(store: Store) -> None:
    idea = await inbox.capture(store, GOOD, author="desk")
    assert idea.author == "desk"
    assert idea.summary == GOOD


async def test_a_human_writes_what_they_like(store: Store) -> None:
    # The rule is about a proposal arriving with nobody who holds its context. A person's own note
    # arrives with the person, and "билд" on their own card costs nobody anything.
    idea = await inbox.capture(store, "билд")
    assert idea.summary == "билд"


async def test_a_generated_line_cannot_undo_the_check(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Held at capture and nowhere else, the rule would be true of the row only until a summary
    run finished — which is a race, not a promise."""
    idea = await inbox.capture(store, GOOD, author="desk")

    async def heading(_prompt: str) -> AsyncIterator[str]:
        yield "Folder cards"

    monkeypatch.setattr(blocks.session, "stream_answer", heading)
    await blocks._summarise(store, idea)

    kept = await store.idea(idea.id)
    assert kept is not None
    assert kept.summary == GOOD, "a heading replaced the line the desk was held to"


async def test_a_generated_line_that_reads_at_a_glance_is_taken(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    better = "a folder card could name the files it was read from"

    async def line(_prompt: str) -> AsyncIterator[str]:
        yield better

    monkeypatch.setattr(blocks.session, "stream_answer", line)
    idea = await inbox.capture(store, GOOD, author="desk")
    await blocks._summarise(store, idea)

    kept = await store.idea(idea.id)
    assert kept is not None
    assert kept.summary == better


async def test_a_proposal_with_no_first_line_is_refused(store: Store) -> None:
    # `fallback_summary` of whitespace is the empty string, so this is the card with nothing on it.
    with pytest.raises(ValueError, match="no line to read"):
        await inbox.capture(store, "   \n\n  ", author="desk")
