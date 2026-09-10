"""The store as a whole: what has to be true of it however many tables it grows.

Every other mechanic in this program rests on these four, and each one is the kind of guarantee that
breaks quietly — a migration added on a tired evening, a reader written against a table that always
had a row in it during development. So they are asserted over *whatever the store currently is*,
by introspection, rather than over a list somebody has to remember to extend.
"""

from __future__ import annotations

import inspect
import pathlib
import sqlite3
import tempfile
from collections.abc import AsyncIterator

import pytest
from agent_desk.store.repo import Store

pytestmark = pytest.mark.unit

# Readers that need something named before they can answer, and getters whose whole job is to be
# asked about a row that may not exist. Both are covered below by their own test; they are named
# here so the sweep can be "everything else, with no exceptions".
NEEDS_A_NAME = {
    "idea",
    "block",
    "button_card",
    "check_card",
    "step_card",
    "question",
    "script",
    "autostart",
    "links",
    "tasks",
    "shift_steps",
    "run_steps",
    "board_tickets",
    "env",
    "terms",
    "project_note",
    "may_be_read",
    "viewer_for",
    "combining",
    "template",
    "mcp_servers",
    "known",
    "scripts",
    "grades",
    "suggestions",
    "bench_cards",
    "bench_moments",
    "bench_as_it_was",
    "can_undo_bench",
    "cards_said",
    "spent_since",
    "ideas_of_blocks",
    "explored_since",
    "started_since",
    "kicked_since",
    "labels",
    "questions",
    "blocks",
    "ideas",
    "runs",
}


@pytest.fixture
async def desk(tmp_path: pathlib.Path) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    yield store
    await store.close()


def _schema(where: pathlib.Path) -> str:
    conn = sqlite3.connect(where)
    try:
        rows = conn.execute(
            "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
        ).fetchall()
    finally:
        conn.close()
    return "\n".join(
        f"{kind} {name} :: {' '.join((sql or '').split())}" for kind, name, sql in rows
    )


async def _built_fresh() -> tuple[pathlib.Path, str]:
    where = pathlib.Path(tempfile.mkdtemp()) / "agent-desk.db"
    store = Store(where)
    await store.open()
    await store.close()
    return where, _schema(where)


# --- the schema is a function of the migrations and nothing else --------------------------------
async def test_two_databases_built_from_nothing_come_out_identical() -> None:
    """Forward-only migrations mean the schema is a pure function of the files. A database that
    depended on when it was built would make "it works on mine" a sentence somebody has to say."""
    _, first = await _built_fresh()
    _, second = await _built_fresh()

    assert first == second
    assert first.count("\n") > 50, "the schema came out suspiciously small"


async def test_opening_the_same_database_again_changes_nothing() -> None:
    """Every start of the console runs the migrations. One that applied anything a second time
    would be a console that broke on its second run — which is the one nobody tests."""
    where, first = await _built_fresh()

    again = Store(where)
    await again.open()
    await again.close()

    assert _schema(where) == first


async def test_every_migration_is_recorded_once(desk: Store) -> None:
    """The version row is what makes the second start cheap, and a duplicate would mean a file
    applied twice."""
    async with desk.engine.connect() as conn:
        from sqlalchemy import text

        rows = await conn.execute(text("SELECT version FROM schema_version"))
        seen = [row[0] for row in rows]

    assert len(seen) == len(set(seen))
    assert min(seen) == 1, "schema.sql is version 1"


# --- and every reader survives a store with nothing in it ---------------------------------------
def _sweepable() -> list[str]:
    """Every reader that can be asked without naming anything.

    Found by looking rather than listed: a reader added next year is one nobody would think to add
    to a list here, and it is exactly as able to fall over on an empty store as the others.

    A *reader* is told from a writer by this module's own convention rather than by a name anybody
    has to remember: reading opens `engine.connect()`, writing opens `engine.begin()`. Written as
    a list of names first, the sweep called `close()` — which is async and takes nothing — and
    every reader after it failed with "the store is not open".
    """
    found = []
    for name, what in inspect.getmembers(Store, inspect.isfunction):
        if name.startswith("_") or name in NEEDS_A_NAME:
            continue
        if not inspect.iscoroutinefunction(what):
            continue
        said = inspect.getsource(what)
        if "engine.begin()" in said or "engine.connect()" not in said:
            continue
        needed = [
            one
            for one, kind in inspect.signature(what).parameters.items()
            if one != "self"
            and kind.default is inspect.Parameter.empty
            and kind.kind not in (kind.VAR_POSITIONAL, kind.VAR_KEYWORD)
        ]
        if not needed:
            found.append(name)
    return sorted(found)


async def test_every_reader_answers_on_a_store_with_nothing_in_it(desk: Store) -> None:
    """A console opened on a fresh machine renders every column before anybody has done anything,
    and a reader that raised there would be a first run that shows a stack trace."""
    swept = _sweepable()
    assert len(swept) > 15, f"the sweep found almost nothing to sweep: {swept}"

    broke = []
    for name in swept:
        try:
            await getattr(desk, name)()
        except Exception as exc:  # what is being asserted is that none of them do
            broke.append(f"{name}: {type(exc).__name__}: {exc}")

    assert broke == []


@pytest.mark.parametrize(
    "reader",
    ["idea", "block", "button_card", "check_card", "step_card", "question", "script"],
)
async def test_a_getter_for_a_row_that_is_not_there_says_so(desk: Store, reader: str) -> None:
    """`None`, not an exception. Every one of these is asked about an id off a page that may be
    looking at something somebody deleted a minute ago."""
    assert await getattr(desk, reader)("nothing-by-that-name") is None


async def test_the_one_getter_that_answers_with_a_row_either_way(desk: Store) -> None:
    """A project nobody has armed is a project with the switches off, which is a fact — and a
    `None` here would make every caller write the same three lines."""
    arming = await desk.autostart("a-project-nobody-has-touched")

    assert not arming.armed
    assert not arming.exploring
    assert not arming.tidying
