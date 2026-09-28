"""Applying the schema files to the one database, and refusing one whose history is not ours.

`schema.sql` is version 1; every later change is `NNN-<name>.sql`, applied in order, once, forward
only (docs/adr/0003). Three things here that the runner inside `repo.py` did not do, each because
it already went wrong on the owner's machine (_research/04_dogfooding_gaps.md, R2):

- **The version table records the file's name, not only its number.** A branch that numbered its
  migration 078 while `main` had a different 078 left the live database at "78" meaning something
  `main` never wrote — and `main` then skipped its own 078 in silence. A number claimed by two
  files is only caught by comparing names.
- **A database whose recorded history this code does not know is refused, loudly.** An applied
  version with no file here, or with a different file here, means the database was migrated by
  some other checkout; opening it anyway is how a route fails a week later with "no such column".
- **A copy is taken before anything is applied.** `agent-desk.db.bak-v<N>` next to the database,
  where N is the version it was at. Rolling code back is `git checkout <tag>`; rolling the
  database back is this file — there was no second half before.

A database recorded before names existed has its names filled in from the files by number, once.
That is trusting its history exactly as much as the old runner did, and no more; the one database
where that trust was misplaced is reconciled by `scripts/reconcile-schema-version.py` first.
"""

from __future__ import annotations

import asyncio
import sqlite3
import time
from itertools import pairwise
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

HERE = Path(__file__).parent


class MigrationRefused(RuntimeError):
    """The database says it was migrated by something this code is not."""


def _now_ms() -> int:
    return int(time.time() * 1000)


def statements(script: str) -> list[str]:
    """One SQL statement per element, split on the semicolons that actually end one.

    The sqlite driver takes one statement per call, so a schema file is split here — and the split
    has to know where it is. A `;` inside a comment already cut a `CREATE TABLE` in half once
    ("sha256 of a token; not stored", which failed as `incomplete input`), and a `;` inside a
    string literal would do the same to the first migration that seeds a row or writes a
    `CHECK (x IN ('a;b'))`. So this walks the script once, tracking quotes and both kinds of
    comment, rather than deleting comments and hoping.
    """
    statements: list[str] = []
    current: list[str] = []
    quote: str | None = None
    index = 0
    while index < len(script):
        character = script[index]
        pair = script[index : index + 2]

        if quote is not None:
            current.append(character)
            if character == quote:
                quote = None
            index += 1
        elif character in "'\"`[":
            # SQLite accepts four quotings, and a `;` inside any of them is not the end of a
            # statement: '…', "…", `…` and [ … ].
            quote = "]" if character == "[" else character
            current.append(character)
            index += 1
        elif pair == "--":
            end = script.find("\n", index)
            index = len(script) if end == -1 else end
        elif pair == "/*":
            end = script.find("*/", index + 2)
            index = len(script) if end == -1 else end + 2
        elif character == ";":
            statements.append("".join(current))
            current = []
            index += 1
        else:
            current.append(character)
            index += 1

    statements.append("".join(current))
    return [statement.strip() for statement in statements if statement.strip()]


def migrations(directory: Path = HERE) -> list[tuple[int, Path]]:
    """`schema.sql` is version 1; every later change is `NNN-<name>.sql` applied in order.

    Forward-only, and never edited in place: a file that has been applied on a machine is history
    (docs/adr/0003). Two files with one number are refused here, before either reaches a database:
    git cannot see that conflict, because the two names differ.
    """
    found = [(1, directory / "schema.sql")]
    for path in sorted(directory.glob("[0-9][0-9][0-9]-*.sql")):
        version = int(path.name[:3])
        if version <= 1:
            # `001-anything.sql` would sort before `schema.sql`, apply, record version 1, and the
            # baseline would then be skipped for ever. The glob invites exactly that filename, so
            # it is refused loudly rather than resolved quietly.
            raise ValueError(f"{path.name}: version 1 is schema.sql; number migrations from 002")
        found.append((version, path))
    found.sort()
    for (one, first), (other, second) in pairwise(found):
        if one == other:
            raise ValueError(f"{first.name} and {second.name} both claim version {one}")
    return found


def backup_path(db: Path, version: int) -> Path:
    return db.with_name(f"{db.name}.bak-v{version}")


def _copy(db: Path, to: Path) -> None:
    """SQLite's own backup, so a database in WAL mode is copied whole rather than half."""
    source = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    target = sqlite3.connect(to)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


async def migrate(engine: AsyncEngine, db: Path, directory: Path = HERE) -> None:
    """Apply what has not been applied, each file in one transaction with its own version row.

    The transaction is the point. A file that fails halfway, or a process killed between its
    statements and its `schema_version` row, must leave the database exactly as it found it —
    otherwise the next start finds tables it is about to create and never opens again.
    """
    files = migrations(directory)
    named = {version: path.name for version, path in files}

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS schema_version ("
                "version INTEGER PRIMARY KEY, applied_at INTEGER NOT NULL, name TEXT)"
            )
        )
        columns = {row[1] for row in await conn.execute(text("PRAGMA table_info(schema_version)"))}
        if "name" not in columns:
            await conn.execute(text("ALTER TABLE schema_version ADD COLUMN name TEXT"))
        for version, name in named.items():
            await conn.execute(
                text("UPDATE schema_version SET name = :n WHERE version = :v AND name IS NULL"),
                {"n": name, "v": version},
            )
        rows = await conn.execute(text("SELECT version, name FROM schema_version"))
        applied = {row[0]: row[1] for row in rows}
        # Inside the transaction, so a refused database keeps no name column and no filled names:
        # refusing is only honest if it leaves the file as it was.
        for version, name in sorted(applied.items()):
            if version not in named:
                raise MigrationRefused(
                    f"{db}: version {version} ({name or 'no name recorded'}) is recorded as "
                    "applied, but this code has no such migration — the database was migrated by "
                    f"another checkout. Restore a backup ({db.name}.bak-v<N>) or reconcile "
                    "schema_version."
                )
            if name != named[version]:
                raise MigrationRefused(
                    f"{db}: version {version} was applied as {name}, but this code's version "
                    f"{version} is {named[version]} — two files claimed one number. Reconcile "
                    "schema_version before opening it."
                )

    pending = [(version, path) for version, path in files if version not in applied]
    if pending and applied:
        await asyncio.to_thread(_copy, db, backup_path(db, max(applied)))

    for version, path in pending:
        async with engine.begin() as conn:
            for statement in statements(path.read_text()):
                await conn.execute(text(statement))
            await conn.execute(
                text("INSERT INTO schema_version (version, applied_at, name) VALUES (:v, :t, :n)"),
                {"v": version, "t": _now_ms(), "n": path.name},
            )
