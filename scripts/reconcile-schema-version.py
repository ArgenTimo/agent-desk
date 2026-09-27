"""One-off: make the live database's schema_version say what its schema actually is (A4).

_research/04_dogfooding_gaps.md R2. The live database at ~/.local/share/agent-desk was migrated by
branches as well as by `main`:

- its 66 has no file in any ref, and left nothing in the schema that `main` does not also build;
- its 78 is `changed_at` from the branch of #15/#16 — which `main` now has as 079;
- its 79 is `sketch_card`, the file `main` has as 078, applied under a renamed number.

`store/migrate.py` refuses such a database, correctly. This rewrites only `schema_version` — never a
table the program reads — and then proves the result by building a fresh database from this
checkout's files and comparing every table, column and index. If they differ, nothing is written.

    poetry run python scripts/reconcile-schema-version.py <path-to-a-COPY-of-agent-desk.db>

Run it on a copy first; the command that restores the original is in _work/DECISIONS.md.
"""

from __future__ import annotations

import asyncio
import sqlite3
import sys
import tempfile
from pathlib import Path

from agent_desk.store.migrate import migrations
from agent_desk.store.repo import Store

# What each odd row of the live history really was, in this checkout's names.
ACTUALLY = {78: "078-a-thing-drawn-from-the-project.sql", 79: "079-when-a-card-last-changed.sql"}
NOTHING_AT_ALL = 66


def shape(db: Path) -> dict[str, object]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        found: dict[str, object] = {}
        for kind, name, table in conn.execute(
            "SELECT type, name, tbl_name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
        ):
            if kind == "table":
                found[name] = [row[1:] for row in conn.execute(f"PRAGMA table_info('{name}')")]
            else:
                found[f"{kind}:{name}"] = table
        found.pop("schema_version")
        return found
    finally:
        conn.close()


async def fresh(where: Path) -> Path:
    db = where / "fresh.db"
    store = Store(db)
    await store.open()
    await store.close()
    return db


def main(db: Path) -> int:
    named = {version: path.name for version, path in migrations()}
    for version, name in ACTUALLY.items():
        if named.get(version) != name:
            print(
                f"this checkout's version {version} is {named.get(version)}, not {name}: "
                "merge #16 (as 079) first",
                file=sys.stderr,
            )
            return 2
    if NOTHING_AT_ALL in named:
        print(f"this checkout has a {NOTHING_AT_ALL}; the mapping no longer holds", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory() as where:
        expected = shape(asyncio.run(fresh(Path(where))))

    got = shape(db)  # only schema_version is written below, so this is the result's shape too
    if got != expected:
        differ = sorted(k for k in set(got) | set(expected) if got.get(k) != expected.get(k))
        print(f"schema differs from this checkout's in {differ}; nothing written", file=sys.stderr)
        return 1

    conn = sqlite3.connect(db)
    conn.isolation_level = None
    try:
        conn.execute("BEGIN IMMEDIATE")
        columns = {row[1] for row in conn.execute("PRAGMA table_info(schema_version)")}
        if "name" not in columns:
            conn.execute("ALTER TABLE schema_version ADD COLUMN name TEXT")
        conn.execute("DELETE FROM schema_version WHERE version = ?", (NOTHING_AT_ALL,))
        for version, name in named.items():
            conn.execute("UPDATE schema_version SET name = ? WHERE version = ?", (name, version))
        recorded = [row[0] for row in conn.execute("SELECT version FROM schema_version")]
        if sorted(recorded) != sorted(named):
            conn.execute("ROLLBACK")
            print(
                f"versions {sorted(set(recorded) ^ set(named))} differ; nothing kept",
                file=sys.stderr,
            )
            return 1
        conn.execute("COMMIT")
    finally:
        conn.close()

    print(f"{db}: schema_version reconciled to {len(named)} named versions; schema matches")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
