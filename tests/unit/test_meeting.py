"""A meeting that already happened, read into the pool (docs/10-meeting-intake.md §1+).

A transcript is full of things that were said and not meant, so the assertions that matter are
about what it declines to write down.
"""

from __future__ import annotations

import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk.ideas import kin, meeting
from agent_desk.store.repo import Store


@pytest.fixture
async def store(tmp_path: pathlib.Path) -> AsyncIterator[Store]:
    desk = Store(tmp_path / "agent-desk.db")
    await desk.open()
    yield desk
    await desk.close()


def _answers(replies: list[str], monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Each pass gets the next reply. The prompts it was given come back for inspection."""
    asked: list[str] = []

    async def fake(prompt: str) -> AsyncIterator[str]:
        asked.append(prompt)
        yield replies[min(len(asked) - 1, len(replies) - 1)]

    monkeypatch.setattr(meeting, "stream_answer", fake)
    # The placement pass is a separate judgement and is not what this file is about.
    monkeypatch.setattr(kin, "stream_answer", fake)
    return asked


@pytest.mark.unit
def test_none_is_a_normal_answer_and_most_of_a_meeting_deserves_it() -> None:
    """The opposite default from the splitter's: there, unparsed text was something somebody
    definitely typed. Here it is a model's reading of a room, and inventing is the only failure."""
    assert meeting.read_ideas("none") == []
    assert meeting.read_ideas("None.") == []
    assert meeting.read_ideas("") == []
    assert meeting.read_ideas("- add a grid\n- fix the sort") == ["add a grid", "fix the sort"]


@pytest.mark.unit
def test_a_pass_cannot_return_a_summary_of_the_meeting() -> None:
    reply = "\n".join(f"idea {number}" for number in range(20))

    assert len(meeting.read_ideas(reply)) == meeting.MOST_PER_PASS


@pytest.mark.unit
def test_a_transcript_is_read_in_stretches_split_on_line_breaks() -> None:
    """A transcript is one speaker per line, and a stretch that ends mid-sentence reads worse."""
    transcript = "\n".join(f"someone: line {number}" * 40 for number in range(60))

    chunks = meeting.parts(transcript)

    assert len(chunks) > 1
    assert all(len(chunk) <= meeting.CHUNK_CHARS + 1000 for chunk in chunks)
    assert "".join(chunk.replace("\n", "") for chunk in chunks).startswith("someone: line 0")


@pytest.mark.unit
def test_a_transcript_pasted_twice_by_accident_cannot_run_all_night() -> None:
    huge = "x" * (meeting.CHUNK_CHARS * (meeting.MOST_PASSES + 10))

    assert len(meeting.parts(huge)) <= meeting.MOST_PASSES


@pytest.mark.unit
async def test_what_it_finds_arrives_as_an_ordinary_idea_nobody_has_decided_on(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """It proposes; it does not decide."""
    _answers(["we should cache the probes\nthe sort is broken"], monkeypatch)

    written = await meeting.read_meeting(store, "someone: I think we should cache the probes")

    assert [idea.text for idea in written] == ["we should cache the probes", "the sort is broken"]
    stored = await store.ideas()
    assert all(idea.state == "new" for idea in stored)
    # Marked as having come from a room, which is the decision docs/10-meeting-intake.md says is
    # cheap today and expensive later.
    assert all(idea.source_kind == "meeting" for idea in stored)


@pytest.mark.unit
async def test_a_meeting_that_says_nothing_new_writes_nothing(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    _answers(["none"], monkeypatch)

    assert await meeting.read_meeting(store, "someone: morning\nsomeone else: morning") == []
    assert await store.ideas() == []


@pytest.mark.unit
async def test_a_half_read_meeting_keeps_what_it_already_found(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Better than losing the part that worked."""
    calls = {"n": 0}

    async def flaky(prompt: str) -> AsyncIterator[str]:
        calls["n"] += 1
        if calls["n"] > 1:
            raise meeting.AnswerFailed("the model went away")
        yield "cache the probes"

    monkeypatch.setattr(meeting, "stream_answer", flaky)
    monkeypatch.setattr(kin, "stream_answer", flaky)
    long_enough = "\n".join("someone: talking" for _ in range(600))

    written = await meeting.read_meeting(store, long_enough)

    assert [idea.text for idea in written] == ["cache the probes"]


@pytest.mark.unit
def test_the_prompt_says_not_to_invent_before_it_says_anything_else() -> None:
    prompt = meeting.read_prompt("someone: hello")

    assert "Never invent one" in prompt
    assert prompt.index("Never invent one") < prompt.index("Not everything said is an idea")
    assert "`none`" in prompt
