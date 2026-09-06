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


@pytest.mark.unit
async def test_a_filed_idea_is_known_to_be_built_rather_than_suspected(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ "Сервис сам определяет, исполнена ли идея и зарегистрирована ли она как фича." The whole
    difference is where the answer comes from: a ticket that exists is a fact, and a reading of
    the idea's own words is a hunch."""
    idea = await store.create_idea(text_="add a grid", summary="a grid", source_kind="typed")
    await store.record_filing(
        idea_id=idea.id, tracker="jira", issue_key="DUCK-7", url="https://x/browse/DUCK-7"
    )

    def never(*a: object, **k: object) -> None:  # pragma: no cover — reaching it is the failure
        raise AssertionError("it asked a model about something it could check")

    monkeypatch.setattr(appraise, "stream_answer", never)

    assert await appraise.sweep(store) == 1

    read = await store.idea(idea.id)
    assert read is not None and read.shape == "built"
    said, _ = await store.card_said(f"idea:{idea.id}")
    assert "already built" in said and "DUCK-7" in said
    # And it is still the human's call: the state a person sets is untouched.
    assert read.state == "new"


@pytest.mark.unit
async def test_an_idea_an_agent_finished_counts_as_evidence_too(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    idea = await store.create_idea(text_="cache it", summary="cache it", source_kind="typed")
    task = await store.queue_task(
        repo_key="origin:acme/api",
        cwd="/tmp",
        title="cache the probes",
        instruction="cache it",
        source_kind="idea",
        source_ref=idea.id,
    )
    await store.take_next_task("origin:acme/api")
    await store.task_started(task.id, "agent1")
    await store.finish_task(task.id)

    assert await appraise.already_there(store, idea) != ""
    assert "finished" in await appraise.already_there(store, idea)


@pytest.mark.unit
async def test_with_no_evidence_it_is_still_only_a_reading(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing was filed and nothing was started, so the text is all there is — and a hunch stays
    a hunch."""
    idea = await store.create_idea(text_="something new", summary="new", source_kind="typed")
    _answers("small built", monkeypatch)

    assert await appraise.already_there(store, idea) == ""
    await appraise.sweep(store)

    said, _ = await store.card_said(f"idea:{idea.id}")
    assert said == "", "a reading must not be written down as evidence"
    assert (await store.idea(idea.id)).shape == "built"  # type: ignore[union-attr]


@pytest.mark.unit
def test_it_never_searches_the_repository_for_something_that_looks_similar() -> None:
    """ "There is a function with a similar name" is not evidence that somebody's idea was built,
    and a check that said so would be the guess this replaces, wearing a grep."""
    # Against the code rather than the prose: the docstring says it does not grep, which a naive
    # search for the word would trip over.
    import ast

    tree = ast.parse(pathlib.Path(appraise.__file__).read_text())
    reader = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "already_there"
    )
    used = {node.attr for node in ast.walk(reader) if isinstance(node, ast.Attribute)} | {
        node.func.id
        for node in ast.walk(reader)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    for searching in ("glob", "rglob", "walk", "read_text", "open", "run"):
        assert searching not in used, searching
    # What it does use: the two things this console actually did.
    assert {"filing_of", "tasks"} <= used
