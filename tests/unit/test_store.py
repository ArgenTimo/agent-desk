"""The store: four tables, forward-only migrations, and the crash rule.

Every test here runs against a real SQLite file under `tmp_path`. The only external dependency
this project has is a filesystem, and a fake filesystem is a directory
(design/01-module-layout.md, "Tests").
"""

from __future__ import annotations

import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk.store.repo import Store
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

REPO_SOURCE = pathlib.Path(Store.__module__.replace(".", "/") + ".py")


@pytest.fixture
async def store(tmp_path: pathlib.Path) -> AsyncIterator[Store]:
    store = Store(tmp_path / "data" / "agent-desk.db")
    await store.open()
    yield store
    await store.close()


async def _thread(store: Store) -> str:
    return (await store.create_thread("a subject")).id


# --- schema -------------------------------------------------------------------------------
@pytest.mark.unit
async def test_opening_creates_the_file_and_records_the_version(store: Store) -> None:
    assert store.path.exists()
    async with store.engine.connect() as conn:
        rows = await conn.execute(text("SELECT version FROM schema_version"))
        assert [row[0] for row in rows] == [1]


@pytest.mark.unit
async def test_opening_twice_applies_nothing_twice(tmp_path: pathlib.Path) -> None:
    """`schema.sql` creates tables without IF NOT EXISTS, so a second application would raise.

    That is the point of recording the version rather than trusting the statement to be harmless:
    forward-only means applied once, and the check is what makes it so.
    """
    path = tmp_path / "agent-desk.db"
    for _ in range(2):
        store = Store(path)
        await store.open()
        await store.close()

    store = Store(path)
    await store.open()
    async with store.engine.connect() as conn:
        rows = await conn.execute(text("SELECT version FROM schema_version"))
        assert [row[0] for row in rows] == [1]
    await store.close()


@pytest.mark.unit
async def test_a_block_cannot_point_at_a_thread_that_does_not_exist(store: Store) -> None:
    """SQLite ignores REFERENCES unless asked per connection, and the schema declares them."""
    with pytest.raises(IntegrityError):
        await store.create_block(
            thread_id="no-such-thread", kind="question", input="?", thread_set_by="human"
        )


# --- blocks -------------------------------------------------------------------------------
@pytest.mark.unit
async def test_a_block_starts_queued_and_is_answered_without_losing_its_input(
    store: Store,
) -> None:
    block = await store.create_block(
        thread_id=await _thread(store),
        kind="question",
        input="what did the docker client end up doing about timeouts",
        thread_set_by="classifier",
    )
    assert block.state == "queued"
    assert block.finished_at is None

    await store.set_block_running(block.id)
    assert (await store.block(block.id)).state == "running"  # type: ignore[union-attr]

    await store.finish_block(block.id, "it retries twice and gives up")
    answered = await store.block(block.id)
    assert answered is not None
    assert answered.state == "answered"
    assert answered.answer == "it retries twice and gives up"
    assert answered.finished_at is not None
    # docs/04: the input is verbatim and is never replaced.
    assert answered.input == "what did the docker client end up doing about timeouts"


@pytest.mark.unit
async def test_a_failed_block_says_why_and_stays(store: Store) -> None:
    """A question that vanished is a question you ask again (docs/04-threads-and-blocks.md)."""
    block = await store.create_block(
        thread_id=await _thread(store), kind="question", input="?", thread_set_by="human"
    )
    await store.fail_block(block.id, "claude exited 1")

    failed = await store.block(block.id)
    assert failed is not None
    assert failed.state == "failed"
    assert failed.error == "claude exited 1"
    assert [b.id for b in await store.blocks()] == [block.id]


@pytest.mark.unit
async def test_a_block_that_was_running_when_the_process_died_comes_back_failed(
    tmp_path: pathlib.Path,
) -> None:
    """Never `answered`: an empty answer that looks complete is the worst of both
    (design/02-data-model.md, "Crash behaviour")."""
    path = tmp_path / "agent-desk.db"
    store = Store(path)
    await store.open()
    thread = await _thread(store)
    running = await store.create_block(
        thread_id=thread, kind="question", input="?", thread_set_by="human"
    )
    queued = await store.create_block(
        thread_id=thread, kind="question", input="?", thread_set_by="human"
    )
    await store.set_block_running(running.id)
    await store.close()

    reopened = Store(path)
    await reopened.open()
    after = await reopened.block(running.id)
    assert after is not None
    assert after.state == "failed"
    assert after.error == "interrupted"
    assert after.answer is None
    # A queued block never started; nothing about it is lost by leaving it queued.
    assert (await reopened.block(queued.id)).state == "queued"  # type: ignore[union-attr]
    await reopened.close()


@pytest.mark.unit
async def test_moving_a_block_records_that_a_human_did_it(store: Store) -> None:
    """That column is the Phase 2 measurement, not decoration (design/02-data-model.md)."""
    first, second = await _thread(store), await _thread(store)
    block = await store.create_block(
        thread_id=first, kind="question", input="?", thread_set_by="classifier"
    )
    await store.move_block(block.id, second)

    moved = await store.block(block.id)
    assert moved is not None
    assert moved.thread_id == second
    assert moved.thread_set_by == "human"


@pytest.mark.unit
async def test_blocks_come_back_newest_first(store: Store) -> None:
    thread = await _thread(store)
    ids = [
        (
            await store.create_block(
                thread_id=thread, kind="question", input=str(n), thread_set_by="human"
            )
        ).id
        for n in range(3)
    ]
    assert [b.id for b in await store.blocks()] == list(reversed(ids))


# --- threads ------------------------------------------------------------------------------
@pytest.mark.unit
async def test_a_closed_thread_is_not_a_candidate_for_classification(store: Store) -> None:
    open_one = await store.create_thread("still open")
    closed = await store.create_thread("finished")
    await store.close_thread(closed.id)

    assert [t.id for t in await store.open_threads()] == [open_one.id]


# --- ideas --------------------------------------------------------------------------------
@pytest.mark.unit
async def test_an_idea_keeps_its_context_and_moves_through_its_four_states(store: Store) -> None:
    idea = await store.create_idea(
        text_="cache the probe results per project",
        summary="Cache tracker probes per project",
        source_kind="session",
        source_ref="00000000-0000-4000-8000-000000000001",
        context={"project": "llm-developer-2", "branch": "boba/duck-129", "title": "Docker client"},
    )
    assert idea.state == "new"

    for state in ("kept", "promoted", "dropped"):
        await store.set_idea_state(idea.id, state)  # type: ignore[arg-type]
    stored = await store.idea(idea.id)
    assert stored is not None
    assert stored.state == "dropped"
    # "What was I doing when I thought this" is most of an idea's meaning a week later.
    assert stored.context["branch"] == "boba/duck-129"
    assert stored.source_kind == "session"


@pytest.mark.unit
async def test_the_summary_is_editable_and_the_thought_is_not(store: Store) -> None:
    """docs/05-ideas.md: losing the thought to its summary would be the tool failing at its job.

    The guarantee is structural — there is no statement in the program that writes `idea.text`.
    """
    idea = await store.create_idea(
        text_="the original thought", summary="first", source_kind="typed"
    )
    await store.set_idea_summary(idea.id, "a better line")

    stored = await store.idea(idea.id)
    assert stored is not None
    assert stored.summary == "a better line"
    assert stored.text == "the original thought"
    source = (pathlib.Path(__file__).resolve().parents[2] / REPO_SOURCE).read_text()
    assert "UPDATE idea SET text" not in source


@pytest.mark.unit
async def test_ideas_can_be_listed_by_state(store: Store) -> None:
    kept = await store.create_idea(text_="one", summary="one", source_kind="typed")
    await store.create_idea(text_="two", summary="two", source_kind="typed")
    await store.set_idea_state(kept.id, "kept")

    assert [i.id for i in await store.ideas(state="kept")] == [kept.id]
    assert len(await store.ideas()) == 2


# --- drafts -------------------------------------------------------------------------------
@pytest.mark.unit
async def test_a_draft_is_text_in_this_tool(store: Store) -> None:
    """All three promotion actions produce text here and nothing anywhere else (docs/05)."""
    idea = await store.create_idea(text_="an idea", summary="an idea", source_kind="typed")
    for kind in ("proposal", "ticket", "paste"):
        await store.create_draft(idea_id=idea.id, kind=kind, body=f"# {kind}")  # type: ignore[arg-type]

    assert {d.kind for d in await store.drafts_for(idea.id)} == {"proposal", "ticket", "paste"}


# --- redaction ----------------------------------------------------------------------------
@pytest.mark.unit
async def test_a_secret_in_an_answer_does_not_leave_the_store(store: Store) -> None:
    secret = "ghp_" + "z" * 36
    block = await store.create_block(
        thread_id=await _thread(store), kind="question", input="?", thread_set_by="human"
    )
    await store.finish_block(block.id, f"the config had {secret} in it")

    answered = await store.block(block.id)
    assert answered is not None
    assert secret not in (answered.answer or "")


@pytest.mark.unit
async def test_what_the_human_typed_comes_back_exactly_as_typed(store: Store) -> None:
    """The line is provenance, not caution.

    docs/07-security.md is about text an agent saw. docs/05-ideas.md is about the thought the
    human had, and it says the original is what survives — a net aimed at transcripts must not eat
    it.
    """
    looks_like_one = "the fix is password = " + '"' + "correcthorse" + '"'
    idea = await store.create_idea(text_=looks_like_one, summary="s", source_kind="typed")
    stored = await store.idea(idea.id)
    assert stored is not None
    assert stored.text == looks_like_one
