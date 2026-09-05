"""What a background pass may say about an idea, and the three things it may not do.

The pass exists because a list of sixty thoughts is unreadable when every row looks like every
other. What makes it safe is that it writes two columns of its own and never the one a person
sets — so most of these assert what it left alone.
"""

from __future__ import annotations

import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk.ideas import appraise
from agent_desk.store.repo import Store


@pytest.fixture
async def store(tmp_path: pathlib.Path) -> AsyncIterator[Store]:
    desk = Store(tmp_path / "agent-desk.db")
    await desk.open()
    yield desk
    await desk.close()


def _answers(reply: str, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(prompt: str) -> AsyncIterator[str]:
        yield reply

    monkeypatch.setattr(appraise, "stream_answer", fake)


@pytest.mark.unit
def test_the_two_words_and_the_safe_pair_for_everything_else() -> None:
    """`medium ready` is the reading that changes nothing about how a card looks, which is what
    an unparsable answer should do."""
    assert appraise.read_appraisal("small ready") == ("small", "ready")
    assert appraise.read_appraisal("LARGE decide") == ("large", "decide")
    assert appraise.read_appraisal("medium built.") == ("medium", "built")

    for unusable in ("", "it depends", "small", "huge ready", "small maybe", "1 2"):
        assert appraise.read_appraisal(unusable) == ("medium", "ready"), unusable


@pytest.mark.unit
async def test_a_sweep_reads_the_ideas_nobody_has_read(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    idea = await store.create_idea(text_="add a grid", summary="a grid", source_kind="typed")
    _answers("small ready", monkeypatch)

    assert await appraise.sweep(store) == 1

    read = await store.idea(idea.id)
    assert read is not None
    assert (read.size, read.shape) == ("small", "ready")
    assert read.appraised_at is not None
    # And only once: the second sweep has nothing left to read.
    assert await appraise.sweep(store) == 0


@pytest.mark.unit
async def test_it_never_writes_the_column_a_person_sets(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`state` is what somebody decided. This pass writes two columns next to it and no more —
    the guarantee is structural, so it is asserted against the source."""
    kept = await store.create_idea(text_="a thought", summary="a thought", source_kind="typed")
    await store.set_idea_state(kept.id, "kept")
    _answers("large built", monkeypatch)

    await appraise.sweep(store)

    read = await store.idea(kept.id)
    assert read is not None
    assert read.state == "kept", "the human's column is untouched"
    assert read.shape == "built"

    source = pathlib.Path(appraise.__file__).read_text()
    assert "set_idea_state" not in source
    assert "delete_idea" not in source


@pytest.mark.unit
async def test_an_unread_idea_looks_unread_rather_than_guessed_at(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A default that reads like a judgement is the guessed status CLAUDE.md's fifth rule is
    about, so an unavailable model leaves the columns null."""
    idea = await store.create_idea(text_="a thought", summary="a thought", source_kind="typed")

    async def broken(prompt: str) -> AsyncIterator[str]:
        raise appraise.AnswerFailed("no model here")
        yield ""  # pragma: no cover

    monkeypatch.setattr(appraise, "stream_answer", broken)

    assert await appraise.sweep(store) == 0

    read = await store.idea(idea.id)
    assert read is not None
    assert read.size is None and read.shape is None and read.appraised_at is None


@pytest.mark.unit
async def test_a_sweep_takes_a_handful_at_a_time(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One model call each: a sweep that took sixty in a tick hurts on the day somebody pastes a
    meeting into the box."""
    for number in range(appraise.AT_A_TIME + 4):
        await store.create_idea(text_=f"thought {number}", summary="t", source_kind="typed")
    _answers("small ready", monkeypatch)

    assert await appraise.sweep(store) == appraise.AT_A_TIME


@pytest.mark.unit
async def test_a_discarded_idea_is_not_worth_a_model_call(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    idea = await store.create_idea(text_="never mind", summary="never mind", source_kind="typed")
    await store.set_idea_state(idea.id, "dropped")
    _answers("small ready", monkeypatch)

    assert await appraise.sweep(store) == 0
