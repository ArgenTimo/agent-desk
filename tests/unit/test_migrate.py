"""The migration runner refuses a history it did not write, and copies before it changes anything.

_research/04_dogfooding_gaps.md R2: the live database was at "78" meaning a branch's migration while
`main` had a different 078, and the runner — which compared numbers only — would have skipped
`main`'s file in silence. Each test below is one way that happens.
"""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from agent_desk.store.migrate import MigrationRefused, backup_path, migrate, migrations
from agent_desk.store.repo import _begin_explicitly, _prepare_connection
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

pytestmark = pytest.mark.unit


@pytest.fixture
def files(tmp_path: Path) -> Path:
    here = tmp_path / "sql"
    here.mkdir()
    (here / "schema.sql").write_text("CREATE TABLE a (id TEXT);")
    (here / "002-first.sql").write_text("CREATE TABLE b (id TEXT);")
    return here


@pytest.fixture
async def engine(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    """Wired the way `Store.open` wires it: DDL is transactional only with these two listeners."""
    made = create_async_engine("sqlite+aiosqlite:///" + str(tmp_path / "agent-desk.db"))
    event.listen(made.sync_engine, "connect", _prepare_connection)
    event.listen(made.sync_engine, "begin", _begin_explicitly)
    yield made
    await made.dispose()


def _recorded(db: Path) -> list[tuple[int, str | None]]:
    with sqlite3.connect(db) as conn:
        return list(conn.execute("SELECT version, name FROM schema_version ORDER BY version"))


async def test_every_applied_file_is_recorded_by_name(
    engine: AsyncEngine, files: Path, tmp_path: Path
) -> None:
    db = tmp_path / "agent-desk.db"

    await migrate(engine, db, files)

    assert _recorded(db) == [(1, "schema.sql"), (2, "002-first.sql")]


async def test_a_number_applied_under_another_name_is_refused(
    engine: AsyncEngine, files: Path, tmp_path: Path
) -> None:
    """The exact shape of R2: a branch's 002 was applied, and this code's 002 is another file."""
    db = tmp_path / "agent-desk.db"
    await migrate(engine, db, files)
    (files / "002-first.sql").rename(files / "002-something-else.sql")

    with pytest.raises(MigrationRefused, match="applied as 002-first.sql"):
        await migrate(engine, db, files)


async def test_a_version_this_code_has_no_file_for_is_refused(
    engine: AsyncEngine, files: Path, tmp_path: Path
) -> None:
    """A database migrated by a newer checkout, opened by an older one."""
    db = tmp_path / "agent-desk.db"
    await migrate(engine, db, files)
    (files / "002-first.sql").unlink()

    with pytest.raises(MigrationRefused, match="version 2 .* has no such migration"):
        await migrate(engine, db, files)


async def test_a_refused_database_is_left_exactly_as_it_was(
    engine: AsyncEngine, files: Path, tmp_path: Path
) -> None:
    db = tmp_path / "agent-desk.db"
    await migrate(engine, db, files)
    (files / "002-first.sql").rename(files / "002-something-else.sql")
    (files / "003-more.sql").write_text("CREATE TABLE c (id TEXT);")

    with pytest.raises(MigrationRefused):
        await migrate(engine, db, files)

    assert _recorded(db) == [(1, "schema.sql"), (2, "002-first.sql")]
    assert not backup_path(db, 2).exists()


def test_two_files_with_one_number_are_refused_before_any_database(files: Path) -> None:
    """Git sees no conflict between `078-a.sql` and `078-b.sql`; this is where it is caught."""
    (files / "002-second.sql").write_text("CREATE TABLE c (id TEXT);")

    with pytest.raises(ValueError, match="both claim version 2"):
        migrations(files)


async def test_a_copy_at_the_old_version_is_taken_before_a_new_file_is_applied(
    engine: AsyncEngine, files: Path, tmp_path: Path
) -> None:
    db = tmp_path / "agent-desk.db"
    await migrate(engine, db, files)
    (files / "003-more.sql").write_text("CREATE TABLE c (id TEXT);")

    await migrate(engine, db, files)

    copy = backup_path(db, 2)
    assert copy.name == "agent-desk.db.bak-v2"
    assert _recorded(copy) == [(1, "schema.sql"), (2, "002-first.sql")]
    assert _recorded(db)[-1] == (3, "003-more.sql")


async def test_nothing_is_copied_when_nothing_is_applied_or_nothing_was_there(
    engine: AsyncEngine, files: Path, tmp_path: Path
) -> None:
    db = tmp_path / "agent-desk.db"

    await migrate(engine, db, files)  # a new database: there is nothing to keep
    await migrate(engine, db, files)  # nothing pending: nothing changes

    assert list(tmp_path.glob("agent-desk.db.bak-*")) == []


async def test_a_database_recorded_before_names_gets_them_from_the_files(
    engine: AsyncEngine, files: Path, tmp_path: Path
) -> None:
    """The one upgrade path: the old table had no name column, and every row's name is filled by
    number — the same trust the old runner gave it, once."""
    db = tmp_path / "agent-desk.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at INTEGER)"
        )
        conn.execute("CREATE TABLE a (id TEXT)")
        conn.execute("INSERT INTO schema_version VALUES (1, 0)")

    await migrate(engine, db, files)

    assert _recorded(db) == [(1, "schema.sql"), (2, "002-first.sql")]
    assert backup_path(db, 1).exists()


async def test_an_old_database_that_is_refused_keeps_its_old_version_table(
    engine: AsyncEngine, files: Path, tmp_path: Path
) -> None:
    """The live database's shape: no name column, and a version (66) no file here has. Refusing it
    must not leave a half-upgraded table behind."""
    db = tmp_path / "agent-desk.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at INTEGER)"
        )
        conn.execute("CREATE TABLE a (id TEXT)")
        conn.executemany("INSERT INTO schema_version VALUES (?, 0)", [(1,), (66,)])

    with pytest.raises(MigrationRefused, match="version 66 .no name recorded."):
        await migrate(engine, db, files)

    with sqlite3.connect(db) as conn:
        assert [row[1] for row in conn.execute("PRAGMA table_info(schema_version)")] == [
            "version",
            "applied_at",
        ]
