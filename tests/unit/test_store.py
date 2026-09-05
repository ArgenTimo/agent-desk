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
async def test_opening_applies_every_migration_exactly_once(store: Store) -> None:
    """The recorded versions are the ones on disk — no more, no fewer, no duplicates.

    Asserting against the files rather than against a number means a new migration does not have
    to edit this test, while a migration that was skipped or applied twice still fails it.
    """
    from agent_desk.store.repo import _migrations

    on_disk = [
        version
        for version, _ in _migrations(pathlib.Path(Store.__module__.replace(".", "/")).parent)
    ]
    assert store.path.exists()
    async with store.engine.connect() as conn:
        rows = await conn.execute(text("SELECT version FROM schema_version ORDER BY version"))
        assert [row[0] for row in rows] == on_disk
    # Version 2 is the viewer table, which arrived with the shared view rather than with the
    # first schema — the forward-only path working as designed (docs/adr/0003).
    assert on_disk[:2] == [1, 2]


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
        rows = await conn.execute(text("SELECT version FROM schema_version ORDER BY version"))
        versions = [row[0] for row in rows]
        assert versions == sorted(set(versions))
        assert versions[0] == 1
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
async def test_moving_a_block_records_who_decided(store: Store) -> None:
    """That column is the Phase 2 measurement, not decoration (design/02-data-model.md).

    Both values are written by this program: `classifier` when its classifier attached the block,
    `human` when a person corrected it. A correction that did not record itself is a measurement
    the project decided to take and then did not.
    """
    first, second, third = await _thread(store), await _thread(store), await _thread(store)
    block = await store.create_block(
        thread_id=first, kind="question", input="?", thread_set_by="human"
    )

    await store.move_block(block.id, second, set_by="classifier")
    attached = await store.block(block.id)
    assert attached is not None
    assert attached.thread_id == second
    assert attached.thread_set_by == "classifier"

    await store.move_block(block.id, third, set_by="human")
    corrected = await store.block(block.id)
    assert corrected is not None
    assert corrected.thread_id == third
    assert corrected.thread_set_by == "human"


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


# --- what a reviewer found by mutating this file ------------------------------------------------
@pytest.mark.unit
async def test_a_crash_between_a_migration_and_its_version_row_leaves_nothing_behind(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A half-applied migration used to brick the store permanently.

    The driver commits DDL as it runs, so a crash after `CREATE TABLE` and before the
    `schema_version` row left the tables in place and the version unrecorded — and every start
    after that died with "table thread already exists". The only recovery was deleting the file.
    """
    from agent_desk.store import repo

    path = tmp_path / "agent-desk.db"
    real = repo._now_ms
    calls = {"n": 0}

    def explode() -> int:
        calls["n"] += 1
        if calls["n"] == 1:  # the timestamp of the first version row
            raise RuntimeError("killed between the tables and the version")
        return real()

    monkeypatch.setattr(repo, "_now_ms", explode)
    store = Store(path)
    with pytest.raises(RuntimeError):
        await store.open()
    await store.close()

    monkeypatch.setattr(repo, "_now_ms", real)
    reopened = Store(path)
    await reopened.open()  # this is the assertion: it opens at all
    async with reopened.engine.connect() as conn:
        rows = await conn.execute(text("SELECT version FROM schema_version ORDER BY version"))
        assert next(row[0] for row in rows) == 1
    await reopened.close()


@pytest.mark.unit
def test_a_semicolon_inside_a_comment_or_a_string_is_not_the_end_of_a_statement() -> None:
    """Both halves of this were bugs: the first shipped, the second was one migration away."""
    from agent_desk.store.repo import _statements

    script = """
    -- a note with a semicolon; like this one
    CREATE TABLE t (
        a TEXT NOT NULL,          -- sha256 of a token; not stored
        b TEXT NOT NULL DEFAULT 'a;b'
    );
    /* a block comment; with one too */
    INSERT INTO t (a, b) VALUES ('x;y', 'z');
    """
    parsed = _statements(script)

    assert len(parsed) == 2
    assert parsed[0].startswith("CREATE TABLE t")
    assert "'a;b'" in parsed[0]
    assert parsed[1].startswith("INSERT INTO t")
    assert "'x;y'" in parsed[1]


@pytest.mark.unit
def test_a_migration_numbered_one_is_refused_rather_than_silently_winning(
    tmp_path: pathlib.Path,
) -> None:
    """`001-anything.sql` sorts before `schema.sql`, and would take its version number with it."""
    from agent_desk.store.repo import _migrations

    (tmp_path / "schema.sql").write_text("CREATE TABLE a (id TEXT);")
    (tmp_path / "001-early.sql").write_text("CREATE TABLE b (id TEXT);")

    with pytest.raises(ValueError, match="number migrations from 002"):
        _migrations(tmp_path)


@pytest.mark.unit
async def test_a_retried_block_does_not_keep_the_failure_it_recovered_from(store: Store) -> None:
    block = await store.create_block(
        thread_id=await _thread(store), kind="question", input="?", thread_set_by="human"
    )
    await store.fail_block(block.id, "claude exited 1")
    await store.set_block_running(block.id)
    await store.finish_block(block.id, "the real answer")

    answered = await store.block(block.id)
    assert answered is not None
    assert answered.state == "answered"
    assert answered.answer == "the real answer"
    assert answered.error is None


@pytest.mark.unit
async def test_every_column_the_documents_call_redacted_is_redacted(store: Store) -> None:
    """Three of the four had no test at all, and each survived being un-scrubbed.

    docs/07-security.md names redaction at the store boundary as the mechanism; a mechanism that
    only one column is asserted to have is a comment on the other three.
    """
    secret = "ghp_" + "w" * 36
    thread = await _thread(store)

    failed = await store.create_block(
        thread_id=thread, kind="question", input="?", thread_set_by="human"
    )
    await store.fail_block(failed.id, f"the run printed {secret} before dying")
    stored_block = await store.block(failed.id)
    assert stored_block is not None
    assert secret not in (stored_block.error or "")

    idea = await store.create_idea(
        text_="a thought",
        summary="a thought",
        source_kind="session",
        context={"title": f"session working on {secret}"},
    )
    stored_idea = await store.idea(idea.id)
    assert stored_idea is not None
    assert secret not in str(stored_idea.context)

    await store.create_draft(idea_id=idea.id, kind="proposal", body=f"it quotes {secret}")
    (draft,) = await store.drafts_for(idea.id)
    assert secret not in draft.body


@pytest.mark.unit
def test_the_splitter_knows_every_way_sqlite_quotes_a_name() -> None:
    """A `;` inside any of the four quotings is not the end of a statement."""
    from agent_desk.store.repo import _statements

    parsed = _statements(
        """
        CREATE TABLE "odd;name" (a TEXT DEFAULT 'x;y', `b;c` TEXT, [d;e] TEXT);
        INSERT INTO "odd;name" (a) VALUES ('p;q');
        """
    )
    assert len(parsed) == 2
    assert parsed[0].startswith('CREATE TABLE "odd;name"')
    assert "[d;e]" in parsed[0]
    assert "`b;c`" in parsed[0]


@pytest.mark.unit
async def test_the_token_field_cannot_be_given_a_token(store: Store) -> None:
    """It asks for the name of an environment variable, and somebody pasted a token into it — of
    course they did. A field that accepts a secret is a field that will be given one, so this is
    the check that makes docs/07-security.md's promise true rather than merely written down.
    """
    await store.set_link(
        repo_key="k", name="jira", url="https://example.invalid/browse/A", token_env="JIRA_TOKEN"
    )
    (kept,) = await store.links("k")
    assert kept.token_env == "JIRA_TOKEN"

    for pasted in (
        "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        "ATATTyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy==",
        "me@example.com:secret",
        "not a name",
        "x" * 200,
    ):
        await store.set_link(
            repo_key="k", name="jira", url="https://example.invalid/browse/A", token_env=pasted
        )
        (after,) = await store.links("k")
        assert after.token_env is None, f"{pasted[:8]}… was stored"

    # The same field on the environment list, and the same answer.
    assert await store.set_env(repo_key="k", name="DATABASE_URL") is True
    assert await store.set_env(repo_key="k", name="postgres://user:pw@host/db") is False
    assert [one.name for one in await store.env("k")] == ["DATABASE_URL"]
