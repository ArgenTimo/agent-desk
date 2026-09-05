"""Every SQL statement in the program.

One place to look when the storage shape changes, for the same reason `observe/` is one module
(design/01-module-layout.md). `schema.sql` is the schema; this file is the queries.

**Redaction runs here, on the way out.** Not every column: the line is provenance. `block.input`
and `idea.text` are what a human typed, and docs/05-ideas.md is explicit that the original is the
thing that survives — scrubbing it would let a net aimed at transcripts eat the thought this tool
exists to keep. `block.answer`, `block.error`, `idea.context` and `draft.body` are built from what
an agent saw, which is the text docs/07-security.md is about, and they are scrubbed every time
they leave.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import bindparam, event, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from ulid import ULID

from agent_desk.store.redact import scrub, scrub_optional

# The fifth is a request about *this console* — "tidy up the ideas", "put a button here" — as
# opposed to one about a project it watches. It is an instruction with a different address, and
# the address is the difference that matters (docs/04-threads-and-blocks.md).
# The shape of an environment variable's name, and the reason it is checked: the token field asks
# for a name, and a field that accepts a secret is a field that will be given one
# (docs/07-security.md).
#
# Upper snake case, and that is not fussiness. The obvious rule — "letters, digits and
# underscores" — accepts `ghp_R7Sz…`, which is exactly the thing being kept out: a GitHub token is
# letters, digits and underscores. Every environment variable anybody writes is upper snake, every
# example in the console is upper snake, and no secret this program has seen is. Short, too:
# names are short and secrets are not.
_ENV_NAME = re.compile(r"\A[A-Z][A-Z0-9_]{0,47}\Z")

BlockKind = Literal["question", "idea", "observation", "instruction", "master"]
BlockState = Literal["queued", "running", "answered", "failed", "cancelled"]
# Five, and the fifth was added for the one thing the other four cannot say. "We decided not to"
# and "it is in the product" are different answers to "what happened to my idea"
# (docs/05-ideas.md, and 011-idea-done.sql for why the wrong word was tempting).
IdeaState = Literal["new", "kept", "promoted", "dropped", "done"]
SourceKind = Literal["session", "typed", "meeting"]
DraftKind = Literal["proposal", "ticket", "paste"]
# The same three, as values. Defined here so a route validating a path segment and the type that
# describes it cannot drift apart.
DRAFT_KINDS: tuple[DraftKind, ...] = ("proposal", "ticket", "paste")
ThreadSetBy = Literal["classifier", "human"]


# The store's own clock, in the units the registry writes (design/02-data-model.md). Deliberately
# not imported from `observe`: a store does not need to know that a session reader exists.
def _now_ms() -> int:
    return int(time.time() * 1000)


def _new_id() -> str:
    """ULIDs sort by time, so a list of blocks is chronological without an index."""
    return str(ULID())


class Thread(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    subject: str
    created_at: int
    closed_at: int | None = None


class Block(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    thread_id: str
    kind: BlockKind
    state: BlockState
    input: str
    answer: str | None = None
    error: str | None = None
    thread_set_by: ThreadSetBy
    created_at: int
    finished_at: int | None = None
    # What this one was built from, one line a thing, as the console described it at the time.
    context: str | None = None


class Directive(BaseModel):
    """A message to a session that a human asked for and has not yet sent."""

    model_config = ConfigDict(frozen=True)

    id: str
    block_id: str
    session_id: str
    session_name: str
    text: str
    created_at: int
    sent_at: int | None = None
    # The other ending: a background agent started on this instruction (docs/adr/0006).
    agent_id: str | None = None
    dispatched_at: int | None = None


class Task(BaseModel):
    """Work a person approved and put in a queue (docs/adr/0007).

    No priority, no assignee, no estimate. It is a list of things somebody said to do, in the
    order they said them, and the loop that starts them decides only when.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    repo_key: str
    cwd: str
    title: str
    instruction: str
    source_kind: str
    source_ref: str | None = None
    # The message that asked for it, where one did. Matched by title once, which was the same
    # thing until two messages started with the same sixty characters.
    block_id: str | None = None
    queued_at: int
    started_at: int | None = None
    agent_id: str | None = None
    failed_at: int | None = None
    finished_at: int | None = None
    detail: str | None = None

    @property
    def waiting(self) -> bool:
        return self.started_at is None and self.failed_at is None


class Autostart(BaseModel):
    """What one project is allowed to do on its own, and what it has spent doing it.

    Two switches, because they are two decisions (docs/adr/0008): `armed` starts work somebody
    queued, and `exploring` goes looking for something to fix when there is nothing queued.
    """

    model_config = ConfigDict(frozen=True)

    repo_key: str
    armed_at: int | None = None
    per_hour: int = 2
    failures: int = 0
    disarmed_why: str | None = None
    exploring_at: int | None = None
    per_day: int = 3
    # Where this project is on disk, recorded by the panel that pressed the switch: an exploration
    # is the first task in a project and has none to inherit a directory from.
    cwd: str | None = None

    @property
    def armed(self) -> bool:
        return self.armed_at is not None

    @property
    def exploring(self) -> bool:
        return self.exploring_at is not None


class Kicking(BaseModel):
    """One session that is not allowed to idle, and what it has spent not idling (docs/adr/0009).

    Keyed by the short id, because that is the name the CLI's own `stop` and `logs` take and the
    prefix of the id `--resume` takes. Per session rather than per project: this is a permission
    about one conversation.
    """

    model_config = ConfigDict(frozen=True)

    short_id: str
    session_id: str = ""
    cwd: str = ""
    armed_at: int | None = None
    kicks: int = 0
    kicked_at: int | None = None
    # When the account was out of budget, this is when to look again. A limit is a wait, not a
    # failure, and this field is the difference between the two.
    resume_at: int | None = None
    failures: int = 0
    disarmed_why: str | None = None
    per_hour: int = 4

    @property
    def armed(self) -> bool:
        return self.armed_at is not None

    def waiting(self, now_ms: int) -> bool:
        return self.resume_at is not None and self.resume_at > now_ms


class Term(BaseModel):
    """One word somebody uses, and what they mean by it (021-glossary.sql)."""

    model_config = ConfigDict(frozen=True)

    id: str
    repo_key: str
    term: str
    means: str
    created_at: int


class Filing(BaseModel):
    """Where an idea went, once a human sent it there (docs/adr/0005)."""

    model_config = ConfigDict(frozen=True)

    id: str
    idea_id: str
    tracker: str
    issue_key: str
    url: str
    created_at: int


class ProjectLink(BaseModel):
    """Somewhere a project also lives: a board, a repository page, a dashboard.

    `token_env` names an environment variable and never holds a token. See 006-project-links.sql
    for why, and docs/07-security.md for the rule it follows.
    """

    model_config = ConfigDict(frozen=True)

    repo_key: str
    name: str
    url: str
    token_env: str | None = None
    added_at: int

    @property
    def token_present(self) -> bool:
        """Whether there is a secret under this name — never what it is.

        Two places count: the shell that started the console, and this machine's own secret file
        (agent_desk/secrets.py). Neither is ever rendered.
        """
        from agent_desk import secrets as kept

        return kept.has(self.token_env or "")


class ProjectEnv(BaseModel):
    """A variable this project's agents need. The name, never the value."""

    model_config = ConfigDict(frozen=True)

    repo_key: str
    name: str
    note: str | None = None
    added_at: int

    @property
    def present(self) -> bool:
        """Whether there is a value for it here — not what it holds."""
        from agent_desk import secrets as kept

        return kept.has(self.name)


class Idea(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    block_id: str | None
    text: str
    summary: str
    state: IdeaState
    source_kind: SourceKind
    source_ref: str | None
    context: dict[str, Any]
    created_at: int
    # The idea this one is part of, when a message held several thoughts or a human said two
    # ideas are one piece of work (docs/05-ideas.md).
    parent_id: str | None = None
    # Which project it is about, as a repository key. Editable, and defaulted rather than guessed:
    # a thought typed with nothing on the workbench is about the thing in front of you.
    project_key: str | None = None
    # What a background pass made of it, kept apart from what a person made of it: `state` is the
    # human's column and nothing here is ever written into it (022-idea-appraisal.sql). All three
    # are nullable because "nobody has looked at this yet" is a real state, and a default that
    # reads like a judgement is the guessed status CLAUDE.md's fifth rule is about.
    size: str | None = None
    shape: str | None = None
    appraised_at: int | None = None


LinkKind = Literal["needs", "touches"]


class IdeaLink(BaseModel):
    """One idea's relation to another, when it is not a sub-idea of it (024-idea-links.sql)."""

    model_config = ConfigDict(frozen=True)

    id: str
    from_id: str
    to_id: str
    kind: LinkKind
    created_at: int


class TrackerBlocker(BaseModel):
    """A ticket on somebody's board that says it is stuck (026-tracker-blockers.sql)."""

    model_config = ConfigDict(frozen=True)

    key: str
    repo_key: str
    summary: str
    said: str
    seen_at: int


class Subscription(BaseModel):
    """A plan a session's tokens are spent against (025-subscriptions.sql).

    `limit_tokens` is a number a person typed, not one this console read: there is no account
    balance on this machine to read. Null is the ordinary state and means the card shows what was
    observed and no percentage.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    service: str = ""
    limit_tokens: int | None = None
    created_at: int


class Viewer(BaseModel):
    """A person who may open the shared ideas list, and nothing else (docs/07-security.md)."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    created_at: int
    revoked_at: int | None = None

    @property
    def active(self) -> bool:
        return self.revoked_at is None


class Group(BaseModel):
    """A project somebody declared, over the top of what the repositories say."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    created_at: int
    repo_keys: list[str] = []


class Draft(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    idea_id: str
    kind: DraftKind
    body: str
    created_at: int


def new_token() -> str:
    """A link that is somebody's whole identity, so it is long enough to be one.

    256 bits from the system generator, so guessing one is not a plan and the shared route needs
    no rate limit *against guessing*. That argument covers who gets in and nothing else: what a
    link holder may do once they are in is bounded separately, by the size cap in `web/shared.py`.
    """
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    """What is stored. A high-entropy token needs no key stretching; it needs not being kept."""
    return hashlib.sha256(token.encode()).hexdigest()


def _statements(script: str) -> list[str]:
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


def _migrations(directory: Path) -> list[tuple[int, Path]]:
    """`schema.sql` is version 1; every later change is `NNN-<name>.sql` applied in order.

    Forward-only, and never edited in place: a file that has been applied on a machine is history
    (docs/adr/0003).
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
    return sorted(found)


def _prepare_connection(dbapi_connection: Any, _record: Any) -> None:
    """Two settings per connection, and the second one is why migrations are safe.

    SQLite ignores `REFERENCES` unless asked, so a schema declaring foreign keys without this is
    a schema documenting a guarantee it does not have.

    And the driver, left alone, commits DDL the moment it runs — which meant a crash between a
    migration's `CREATE TABLE`s and its `schema_version` row left the tables in place and the
    version unrecorded. Every subsequent start then tried to create them again and died with
    "table thread already exists": the store was bricked, permanently, and the only recovery was
    deleting the file. Handing transaction control back to us is what makes the two halves of a
    migration one thing (design/02-data-model.md, "Migrations").
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
    dbapi_connection.isolation_level = None


def _begin_explicitly(conn: Any) -> None:
    """With the driver's autocommit off, a transaction has to be asked for by name."""
    conn.exec_driver_sql("BEGIN")


class Store:
    """One SQLite file, opened once at startup (docs/adr/0003)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._engine: AsyncEngine | None = None

    @property
    def opened(self) -> bool:
        """Has the console opened this store yet?

        The shared bind starts beside the console rather than after it, so there is a window at
        every start — and another at every stop — in which this is false. A reader who asks in
        that window used to get a RuntimeError out of a route whose whole promise is that it
        answers identically to everything it cannot serve.
        """
        return self._engine is not None

    @property
    def engine(self) -> AsyncEngine:
        if self._engine is None:  # pragma: no cover - a programming error, not a state
            raise RuntimeError("the store is not open")
        return self._engine

    async def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._engine = create_async_engine("sqlite+aiosqlite:///" + str(self.path))
        event.listen(self._engine.sync_engine, "connect", _prepare_connection)
        event.listen(self._engine.sync_engine, "begin", _begin_explicitly)
        await self._migrate()
        await self._recover_interrupted()

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None

    # --- schema ---------------------------------------------------------------------------
    async def _migrate(self) -> None:
        """Apply what has not been applied, each file in one transaction with its own version row.

        The transaction is the point. A file that fails halfway, or a process killed between its
        statements and its `schema_version` row, must leave the database exactly as it found it —
        otherwise the next start finds tables it is about to create and never opens again.
        """
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS schema_version ("
                    "version INTEGER PRIMARY KEY, applied_at INTEGER NOT NULL)"
                )
            )
            rows = await conn.execute(text("SELECT version FROM schema_version"))
            applied = {row[0] for row in rows}

        for version, path in _migrations(Path(__file__).parent):
            if version in applied:
                continue
            async with self.engine.begin() as conn:
                for statement in _statements(path.read_text()):
                    await conn.execute(text(statement))
                await conn.execute(
                    text("INSERT INTO schema_version (version, applied_at) VALUES (:v, :t)"),
                    {"v": version, "t": _now_ms()},
                )

    async def _recover_interrupted(self) -> None:
        """A block that was running when the process died comes back `failed`, never `answered`.

        A restart that silently promoted an unfinished block would produce an empty answer that
        looks complete (design/02-data-model.md, "Crash behaviour"). A `queued` block is left
        queued: it never started, and nothing about it is lost by running it now.
        """
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE block SET state = 'failed', error = 'interrupted', finished_at = :t "
                    "WHERE state = 'running'"
                ),
                {"t": _now_ms()},
            )

    # --- threads --------------------------------------------------------------------------
    async def create_thread(self, subject: str) -> Thread:
        thread = Thread(id=_new_id(), subject=subject, created_at=_now_ms())
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO thread (id, subject, created_at, closed_at) "
                    "VALUES (:id, :subject, :created_at, NULL)"
                ),
                thread.model_dump(),
            )
        return thread

    async def open_threads(self, *, limit: int = 20) -> list[Thread]:
        """What a new block is classified against — closed subjects are not candidates.

        Bounded, and the bound is not tidiness. Every open subject becomes an option in the thread
        control of every block on the page: measured at 120 questions, that was 6050 options and
        659 KiB re-rendered and pushed over the event stream every two seconds. It is also the
        list the classifier is asked to choose from, and a choice between eighty subjects is not
        a choice anybody should trust.
        """
        async with self.engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT id, subject, created_at, closed_at FROM thread "
                    "WHERE closed_at IS NULL ORDER BY created_at DESC LIMIT :limit"
                ),
                {"limit": limit},
            )
            return [Thread(**row._mapping) for row in rows]

    async def threads_of(self, thread_ids: set[str]) -> list[Thread]:
        """The threads these blocks belong to, whether or not they are still open.

        `open_threads` is bounded, and a block older than that bound still has to be able to show
        the subject it is in — and to be moved back into it.
        """
        if not thread_ids:
            return []
        async with self.engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT id, subject, created_at, closed_at FROM thread "
                    "WHERE id IN :ids ORDER BY created_at DESC"
                ).bindparams(bindparam("ids", expanding=True)),
                {"ids": sorted(thread_ids)},
            )
            return [Thread(**row._mapping) for row in rows]

    async def rename_thread(self, thread_id: str, subject: str) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                text("UPDATE thread SET subject = :subject WHERE id = :id"),
                {"id": thread_id, "subject": subject},
            )

    async def close_thread(self, thread_id: str) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                text("UPDATE thread SET closed_at = :t WHERE id = :id"),
                {"id": thread_id, "t": _now_ms()},
            )

    # --- blocks ---------------------------------------------------------------------------
    async def create_block(
        self,
        *,
        thread_id: str,
        kind: BlockKind,
        input: str,
        thread_set_by: ThreadSetBy,
    ) -> Block:
        block = Block(
            id=_new_id(),
            thread_id=thread_id,
            kind=kind,
            state="queued",
            input=input,
            thread_set_by=thread_set_by,
            created_at=_now_ms(),
        )
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO block (id, thread_id, kind, state, input, answer, error, "
                    "thread_set_by, created_at, finished_at) VALUES (:id, :thread_id, :kind, "
                    ":state, :input, NULL, NULL, :thread_set_by, :created_at, NULL)"
                ),
                block.model_dump(exclude={"answer", "error", "finished_at"}),
            )
        return block

    async def set_block_context(self, block_id: str, context: str) -> None:
        """What this block's run was given, recorded once, at submission."""
        async with self.engine.begin() as conn:
            await conn.execute(
                text("UPDATE block SET context = :context WHERE id = :id"),
                {"context": context, "id": block_id},
            )

    async def delete_block(self, block_id: str) -> None:
        """Remove one block from the console, at a human's asking.

        A block never disappears on its own — a question that vanished is a question you ask again
        (docs/04-threads-and-blocks.md) — but a person may throw one away, and then it goes for
        real. What it leaves behind is what outlives it: an idea keeps its text and loses only the
        pointer to the message that captured it, and a prepared message goes with the instruction
        that asked for it, because nothing should offer to send a message nobody can see the
        reason for.
        """
        async with self.engine.begin() as conn:
            await conn.execute(
                text("UPDATE idea SET block_id = NULL WHERE block_id = :id"), {"id": block_id}
            )
            await conn.execute(text("DELETE FROM directive WHERE block_id = :id"), {"id": block_id})
            await conn.execute(
                text("DELETE FROM block_idea WHERE block_id = :id"), {"id": block_id}
            )
            # Work that never started goes with the message that asked for it: nothing should be
            # waiting to run for a reason nobody can read any more. Work that *did* start keeps its
            # row and loses only the pointer — an agent exists whatever happened to the message.
            await conn.execute(
                text("DELETE FROM task WHERE block_id = :id AND started_at IS NULL"),
                {"id": block_id},
            )
            await conn.execute(
                text("UPDATE task SET block_id = NULL WHERE block_id = :id"), {"id": block_id}
            )
            await conn.execute(text("DELETE FROM block WHERE id = :id"), {"id": block_id})

    async def set_block_kind(self, block_id: str, kind: BlockKind) -> None:
        """What one line of input turned out to be, once a run has read it (docs/04)."""
        async with self.engine.begin() as conn:
            await conn.execute(
                text("UPDATE block SET kind = :kind WHERE id = :id"),
                {"kind": kind, "id": block_id},
            )

    async def set_block_running(self, block_id: str) -> None:
        """Starting a run clears the last one's failure, which is no longer true of this block."""
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE block SET state = 'running', answer = NULL, error = NULL, "
                    "finished_at = NULL WHERE id = :id"
                ),
                {"id": block_id},
            )

    async def finish_block(self, block_id: str, answer: str) -> None:
        await self._set_block_state(block_id, "answered", answer=answer, finished=True)

    async def fail_block(self, block_id: str, error: str) -> None:
        """A failed block says why and stays: a question that vanished is one you ask again."""
        await self._set_block_state(block_id, "failed", error=error, finished=True)

    async def cancel_block(self, block_id: str) -> None:
        await self._set_block_state(block_id, "cancelled", finished=True)

    async def _set_block_state(
        self,
        block_id: str,
        state: BlockState,
        *,
        answer: str | None = None,
        error: str | None = None,
        finished: bool = False,
    ) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE block SET state = :state, "
                    "answer = COALESCE(:answer, answer), error = COALESCE(:error, error), "
                    "finished_at = CASE WHEN :finished THEN :t ELSE finished_at END "
                    "WHERE id = :id"
                ),
                {
                    "id": block_id,
                    "state": state,
                    "answer": answer,
                    "error": error,
                    "finished": finished,
                    "t": _now_ms(),
                },
            )

    async def move_block(self, block_id: str, thread_id: str, *, set_by: ThreadSetBy) -> None:
        """Attach a block to a thread, recording who decided.

        `classifier` is written when this program's classifier attached it; `human` when a person
        did, which is both the one-click override of docs/04-threads-and-blocks.md and the signal
        the correction rate is counted from. A block that is where it started says `human` too,
        because that is what a default is: nobody's decision but the person who typed it.
        """
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE block SET thread_id = :thread_id, thread_set_by = :set_by "
                    "WHERE id = :id"
                ),
                {"id": block_id, "thread_id": thread_id, "set_by": set_by},
            )

    async def blocks_in_thread(self, thread_id: str) -> list[Block]:
        """The thread so far, oldest first — what a continuation is answered against."""
        async with self.engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT id, thread_id, kind, state, input, answer, error, thread_set_by, "
                    "created_at, finished_at, context FROM block WHERE thread_id = :thread_id ORDER BY id"
                ),
                {"thread_id": thread_id},
            )
            return [self._block(row._mapping) for row in rows]

    async def blocks(self, *, limit: int = 50) -> list[Block]:
        """Newest first, which is how the column reads (docs/06-console.md)."""
        async with self.engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT id, thread_id, kind, state, input, answer, error, thread_set_by, "
                    "created_at, finished_at, context FROM block ORDER BY id DESC LIMIT :limit"
                ),
                {"limit": limit},
            )
            return [self._block(row._mapping) for row in rows]

    async def block(self, block_id: str) -> Block | None:
        async with self.engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT id, thread_id, kind, state, input, answer, error, thread_set_by, "
                    "created_at, finished_at, context FROM block WHERE id = :id"
                ),
                {"id": block_id},
            )
            row = rows.first()
            return None if row is None else self._block(row._mapping)

    @staticmethod
    def _block(row: Any) -> Block:
        fields = dict(row)
        fields["answer"] = scrub_optional(fields["answer"])
        fields["error"] = scrub_optional(fields["error"])
        # It quotes what was typed into earlier messages, and what somebody typed can be a token
        # they pasted. Redaction is at the store boundary, and this is the store boundary
        # (docs/07-security.md).
        fields["context"] = scrub_optional(fields["context"])
        return Block(**fields)

    # --- approved work, and the arming that starts it -----------------------------------------
    async def queue_task(
        self,
        *,
        repo_key: str,
        cwd: str,
        title: str,
        instruction: str,
        source_kind: str,
        source_ref: str | None = None,
        block_id: str | None = None,
    ) -> Task:
        """Put one piece of approved work in the queue. Only a route reaches this: nothing
        enqueues itself (docs/adr/0007)."""
        task = Task(
            id=_new_id(),
            repo_key=repo_key,
            cwd=cwd,
            title=title,
            instruction=instruction,
            source_kind=source_kind,
            source_ref=source_ref,
            block_id=block_id,
            queued_at=_now_ms(),
        )
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO task (id, repo_key, cwd, title, instruction, source_kind, "
                    "source_ref, block_id, queued_at, started_at, agent_id, failed_at, detail) "
                    "VALUES (:id, :repo_key, :cwd, :title, :instruction, :source_kind, "
                    ":source_ref, :block_id, :queued_at, NULL, NULL, NULL, NULL)"
                ),
                task.model_dump(
                    exclude={"started_at", "agent_id", "failed_at", "finished_at", "detail"}
                ),
            )
        return task

    async def tasks(self, *, repo_key: str | None = None, limit: int = 100) -> list[Task]:
        one = (
            "SELECT id, repo_key, cwd, title, instruction, source_kind, source_ref, block_id, "
            "queued_at, started_at, agent_id, failed_at, finished_at, detail FROM task "
            "WHERE repo_key = :repo_key ORDER BY queued_at LIMIT :limit"
        )
        every = (
            "SELECT id, repo_key, cwd, title, instruction, source_kind, source_ref, block_id, "
            "queued_at, started_at, agent_id, failed_at, finished_at, detail FROM task "
            "ORDER BY queued_at LIMIT :limit"
        )
        async with self.engine.connect() as conn:
            rows = await conn.execute(
                text(one if repo_key else every),
                {"repo_key": repo_key, "limit": limit} if repo_key else {"limit": limit},
            )
            return [Task(**row._mapping) for row in rows]

    async def take_next_task(self, repo_key: str) -> Task | None:
        """The oldest waiting task in this project, claimed so that two ticks cannot take it.

        The claim is the `started_at` write itself, guarded by `started_at IS NULL`: one statement,
        one winner, and the loser sees the row already taken.
        """
        waiting = [task for task in await self.tasks(repo_key=repo_key) if task.waiting]
        for task in waiting:
            async with self.engine.begin() as conn:
                claimed = await conn.execute(
                    text(
                        "UPDATE task SET started_at = :t WHERE id = :id AND started_at IS NULL "
                        "AND failed_at IS NULL"
                    ),
                    {"t": _now_ms(), "id": task.id},
                )
            if claimed.rowcount:
                return task
        return None

    async def finish_task(self, task_id: str) -> None:
        """Its agent is gone from the registry. What it achieved is not this program's to judge."""
        async with self.engine.begin() as conn:
            await conn.execute(
                text("UPDATE task SET finished_at = :t WHERE id = :id AND finished_at IS NULL"),
                {"t": _now_ms(), "id": task_id},
            )

    async def link_block_ideas(self, block_id: str, idea_ids: Sequence[str]) -> None:
        """Record which ideas a message turned out to be about. A guess, rendered as an offer."""
        async with self.engine.begin() as conn:
            for idea_id in idea_ids:
                await conn.execute(
                    text(
                        "INSERT OR IGNORE INTO block_idea (block_id, idea_id) "
                        "VALUES (:block_id, :idea_id)"
                    ),
                    {"block_id": block_id, "idea_id": idea_id},
                )

    async def ideas_in_flight(self) -> set[str]:
        """The ideas an agent is working on right now.

        Derived rather than stored: a task that started, has not finished and has not failed is an
        agent in a worktree, and the ideas it was dispatched for are the ones in its hands. A sixth
        idea state would be a second copy of that fact, and a second copy of a fact goes wrong
        quietly (design/02-data-model.md).
        """
        working: set[str] = set()
        async with self.engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT source_ref FROM task WHERE started_at IS NOT NULL "
                    "AND finished_at IS NULL AND failed_at IS NULL AND source_ref IS NOT NULL"
                )
            )
            for row in rows:
                working.update(one for one in str(row._mapping["source_ref"]).split(",") if one)
        return working

    async def ideas_of_blocks(self) -> dict[str, list[str]]:
        async with self.engine.connect() as conn:
            rows = await conn.execute(text("SELECT block_id, idea_id FROM block_idea"))
            found: dict[str, list[str]] = {}
            for row in rows:
                found.setdefault(row._mapping["block_id"], []).append(row._mapping["idea_id"])
            return found

    async def task_started(self, task_id: str, agent_id: str) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                text("UPDATE task SET agent_id = :agent_id WHERE id = :id"),
                {"agent_id": agent_id, "id": task_id},
            )

    async def task_landed(self, task_id: str, detail: str) -> None:
        """What happened when its branch was offered to the project (docs/adr/0008)."""
        async with self.engine.begin() as conn:
            await conn.execute(
                text("UPDATE task SET detail = :detail WHERE id = :id"),
                {"detail": detail[:500], "id": task_id},
            )

    async def task_failed(self, task_id: str, detail: str) -> None:
        """It stays failed and says why. Retry is a click (docs/adr/0007)."""
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE task SET failed_at = :t, started_at = NULL, detail = :detail "
                    "WHERE id = :id"
                ),
                {"t": _now_ms(), "detail": detail[:500], "id": task_id},
            )

    async def drop_task(self, task_id: str) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(text("DELETE FROM task WHERE id = :id"), {"id": task_id})

    async def started_since(self, repo_key: str, since_ms: int) -> int:
        """How much of the budget this project has spent in the window (docs/adr/0007)."""
        async with self.engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT COUNT(*) AS n FROM task WHERE repo_key = :repo_key "
                    "AND started_at IS NOT NULL AND started_at >= :since"
                ),
                {"repo_key": repo_key, "since": since_ms},
            )
            row = rows.first()
            return int(row._mapping["n"]) if row else 0

    async def autostart(self, repo_key: str) -> Autostart:
        """Absent is disarmed, which is what every project is until somebody says otherwise."""
        async with self.engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT repo_key, armed_at, per_hour, failures, disarmed_why, "
                    "exploring_at, per_day, cwd FROM autostart WHERE repo_key = :repo_key"
                ),
                {"repo_key": repo_key},
            )
            row = rows.first()
            return Autostart(repo_key=repo_key) if row is None else Autostart(**row._mapping)

    async def armed_projects(self) -> list[Autostart]:
        async with self.engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT repo_key, armed_at, per_hour, failures, disarmed_why, "
                    "exploring_at, per_day, cwd FROM autostart "
                    "WHERE armed_at IS NOT NULL OR exploring_at IS NOT NULL"
                )
            )
            return [Autostart(**row._mapping) for row in rows]

    # --- a session that is not allowed to idle (docs/adr/0009) --------------------------------
    async def kicking(self, short_id: str) -> Kicking:
        """Absent is off, which is what every session is until somebody presses the button."""
        async with self.engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT short_id, session_id, cwd, armed_at, kicks, kicked_at, resume_at, "
                    "failures, disarmed_why, per_hour FROM kicking WHERE short_id = :short_id"
                ),
                {"short_id": short_id},
            )
            row = rows.first()
            return Kicking(short_id=short_id) if row is None else Kicking(**row._mapping)

    async def kicked_sessions(self) -> list[Kicking]:
        async with self.engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT short_id, session_id, cwd, armed_at, kicks, kicked_at, resume_at, "
                    "failures, disarmed_why, per_hour FROM kicking WHERE armed_at IS NOT NULL"
                )
            )
            return [Kicking(**row._mapping) for row in rows]

    async def switched_off_sessions(self) -> list[Kicking]:
        """Sessions that stopped being kept going, and said why (docs/adr/0009).

        The same shape as `switched_off_projects`, and for the same reason: turning itself off is
        what takes a row out of `kicked_sessions`, and that is the moment it is worth showing.
        """
        async with self.engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT short_id, session_id, cwd, armed_at, kicks, kicked_at, resume_at, "
                    "failures, disarmed_why, per_hour FROM kicking WHERE disarmed_why IS NOT NULL"
                )
            )
            return [Kicking(**row._mapping) for row in rows]

    async def kick_session(
        self, short_id: str, *, on: bool, session_id: str = "", cwd: str = "", per_hour: int = 4
    ) -> None:
        """Switch kicking on or off for one session.

        The full id and the directory are recorded when the button is pressed, by the card that
        already knows them: the loop must be able to continue a session whose registry entry has
        gone, and a registry entry goes the moment the session is stopped — which is the first
        thing a kick does.
        """
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO kicking (short_id, session_id, cwd, armed_at, per_hour) "
                    "VALUES (:short_id, :session_id, :cwd, :armed_at, :per_hour) "
                    "ON CONFLICT (short_id) DO UPDATE SET armed_at = :armed_at, "
                    "session_id = CASE WHEN :session_id = '' THEN kicking.session_id "
                    "ELSE :session_id END, "
                    "cwd = CASE WHEN :cwd = '' THEN kicking.cwd ELSE :cwd END, "
                    "per_hour = :per_hour, failures = 0, disarmed_why = NULL, resume_at = NULL"
                ),
                {
                    "short_id": short_id,
                    "session_id": session_id,
                    "cwd": cwd,
                    "armed_at": _now_ms() if on else None,
                    "per_hour": per_hour,
                },
            )

    async def note_kick(self, short_id: str) -> None:
        """One more turn kept alive. The count is what says whether this was worth switching on."""
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE kicking SET kicks = kicks + 1, kicked_at = :t, failures = 0, "
                    "resume_at = NULL WHERE short_id = :short_id"
                ),
                {"t": _now_ms(), "short_id": short_id},
            )

    async def kick_waits_until(self, short_id: str, when_ms: int) -> None:
        """The account is out of budget. Not a failure: the switch stays on and this is when."""
        async with self.engine.begin() as conn:
            await conn.execute(
                text("UPDATE kicking SET resume_at = :t WHERE short_id = :short_id"),
                {"t": when_ms, "short_id": short_id},
            )

    async def note_kick_failure(self, short_id: str) -> int:
        async with self.engine.begin() as conn:
            await conn.execute(
                text("UPDATE kicking SET failures = failures + 1 WHERE short_id = :short_id"),
                {"short_id": short_id},
            )
        return (await self.kicking(short_id)).failures

    async def stop_kicking(self, short_id: str, *, why: str) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE kicking SET armed_at = NULL, disarmed_why = :why "
                    "WHERE short_id = :short_id"
                ),
                {"why": why[:300], "short_id": short_id},
            )

    async def switched_off_projects(self) -> list[Autostart]:
        """Projects that turned themselves off, and said why (docs/adr/0007).

        Separate from `armed_projects` on purpose: disarming clears `armed_at`, so the moment a
        project stops starting work it leaves that list — which is exactly when somebody needs to
        see it (agent_desk/web/blockers.py).
        """
        async with self.engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT repo_key, armed_at, per_hour, failures, disarmed_why, "
                    "exploring_at, per_day, cwd FROM autostart WHERE disarmed_why IS NOT NULL"
                )
            )
            return [Autostart(**row._mapping) for row in rows]

    async def explore(self, repo_key: str, *, per_day: int, on: bool, cwd: str = "") -> None:
        """Switch exploring on or off for one project (docs/adr/0008).

        Separate from arming on purpose: "start what I queued" and "find something to do" are
        different permissions, and a project can have the first without the second.
        """
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO autostart (repo_key, armed_at, per_hour, failures, "
                    "disarmed_why, exploring_at, per_day, cwd) VALUES (:repo_key, NULL, 2, 0, "
                    "NULL, :t, :per_day, :cwd) ON CONFLICT (repo_key) DO UPDATE SET "
                    "exploring_at = :t, per_day = :per_day, cwd = COALESCE(:cwd, autostart.cwd)"
                ),
                {
                    "repo_key": repo_key,
                    "t": _now_ms() if on else None,
                    "per_day": max(1, min(per_day, 12)),
                    "cwd": cwd or None,
                },
            )

    async def explored_since(self, repo_key: str, since_ms: int) -> int:
        """How much of the day's budget this project has spent looking for work of its own."""
        async with self.engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT COUNT(*) AS n FROM task WHERE repo_key = :repo_key "
                    "AND source_kind = 'found' AND started_at IS NOT NULL AND started_at >= :since"
                ),
                {"repo_key": repo_key, "since": since_ms},
            )
            row = rows.first()
            return int(row._mapping["n"]) if row else 0

    async def arm(self, repo_key: str, *, per_hour: int) -> None:
        """Switch it on for one project. Arming clears whatever disarmed it last time."""
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO autostart (repo_key, armed_at, per_hour, failures, disarmed_why) "
                    "VALUES (:repo_key, :t, :per_hour, 0, NULL) "
                    "ON CONFLICT (repo_key) DO UPDATE SET armed_at = :t, per_hour = :per_hour, "
                    "failures = 0, disarmed_why = NULL"
                ),
                {"repo_key": repo_key, "t": _now_ms(), "per_hour": max(1, min(per_hour, 20))},
            )

    async def disarm(self, repo_key: str, why: str | None = None) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO autostart (repo_key, armed_at, per_hour, failures, disarmed_why) "
                    "VALUES (:repo_key, NULL, 2, 0, :why) "
                    "ON CONFLICT (repo_key) DO UPDATE SET armed_at = NULL, disarmed_why = :why"
                ),
                {"repo_key": repo_key, "why": why},
            )

    async def note_failure(self, repo_key: str) -> int:
        """One more failed start, and the count back. Two in a row disarms it (docs/adr/0007)."""
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO autostart (repo_key, armed_at, per_hour, failures, disarmed_why) "
                    "VALUES (:repo_key, NULL, 2, 1, NULL) "
                    "ON CONFLICT (repo_key) DO UPDATE SET failures = autostart.failures + 1"
                ),
                {"repo_key": repo_key},
            )
        return (await self.autostart(repo_key)).failures

    async def clear_failures(self, repo_key: str) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                text("UPDATE autostart SET failures = 0 WHERE repo_key = :repo_key"),
                {"repo_key": repo_key},
            )

    # --- what left through the one door ------------------------------------------------------
    async def record_filing(
        self, *, idea_id: str, tracker: str, issue_key: str, url: str
    ) -> Filing:
        """Written after the issue exists, so a row here means an issue there."""
        filing = Filing(
            id=_new_id(),
            idea_id=idea_id,
            tracker=tracker,
            issue_key=issue_key,
            url=url,
            created_at=_now_ms(),
        )
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO filing (id, idea_id, tracker, issue_key, url, created_at) "
                    "VALUES (:id, :idea_id, :tracker, :issue_key, :url, :created_at)"
                ),
                filing.model_dump(),
            )
        return filing

    async def filings(self) -> list[Filing]:
        async with self.engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT id, idea_id, tracker, issue_key, url, created_at FROM filing "
                    "ORDER BY created_at DESC"
                )
            )
            return [Filing(**row._mapping) for row in rows]

    async def filing_of(self, idea_id: str) -> Filing | None:
        async with self.engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT id, idea_id, tracker, issue_key, url, created_at FROM filing "
                    "WHERE idea_id = :idea_id"
                ),
                {"idea_id": idea_id},
            )
            row = rows.first()
            return None if row is None else Filing(**row._mapping)

    # --- where a project also lives ----------------------------------------------------------
    async def set_link(
        self, *, repo_key: str, name: str, url: str, token_env: str | None = None
    ) -> None:
        """Add or replace one link. One name per project, because a second "jira" is a typo.

        `token_env` is refused unless it is shaped like the name of an environment variable. The
        field asks for a name and somebody pasted a token into it — of course they did; a field
        that accepts a secret is a field that will be given one. This is the check that makes the
        promise in 006-project-links.sql true rather than merely written down.
        """
        if token_env and not _ENV_NAME.match(token_env):
            token_env = None
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO project_link (repo_key, name, url, token_env, added_at) "
                    "VALUES (:repo_key, :name, :url, :token_env, :added_at) "
                    "ON CONFLICT (repo_key, name) DO UPDATE SET url = :url, token_env = :token_env"
                ),
                {
                    "repo_key": repo_key,
                    "name": name,
                    "url": url,
                    "token_env": token_env or None,
                    "added_at": _now_ms(),
                },
            )

    async def set_env(self, *, repo_key: str, name: str, note: str | None = None) -> bool:
        """Name a variable this project needs. Refused unless it is shaped like a name."""
        if not _ENV_NAME.match(name):
            return False
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO project_env (repo_key, name, note, added_at) "
                    "VALUES (:repo_key, :name, :note, :added_at) "
                    "ON CONFLICT (repo_key, name) DO UPDATE SET note = :note"
                ),
                {
                    "repo_key": repo_key,
                    "name": name,
                    "note": note or None,
                    "added_at": _now_ms(),
                },
            )
        return True

    async def env(self, repo_key: str) -> list[ProjectEnv]:
        async with self.engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT repo_key, name, note, added_at FROM project_env "
                    "WHERE repo_key = :repo_key ORDER BY name"
                ),
                {"repo_key": repo_key},
            )
            return [ProjectEnv(**row._mapping) for row in rows]

    async def remove_env(self, repo_key: str, name: str) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM project_env WHERE repo_key = :repo_key AND name = :name"),
                {"repo_key": repo_key, "name": name},
            )

    async def links(self, repo_key: str | None = None) -> list[ProjectLink]:
        """Every link, or one project's. Two statements rather than one with a hole in it: a
        query built by concatenation is a query somebody eventually concatenates a value into."""
        one = (
            "SELECT repo_key, name, url, token_env, added_at FROM project_link "
            "WHERE repo_key = :repo_key ORDER BY name"
        )
        every = "SELECT repo_key, name, url, token_env, added_at FROM project_link ORDER BY repo_key, name"
        async with self.engine.connect() as conn:
            rows = await conn.execute(
                text(one if repo_key else every),
                {"repo_key": repo_key} if repo_key else {},
            )
            return [ProjectLink(**row._mapping) for row in rows]

    async def remove_link(self, repo_key: str, name: str) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM project_link WHERE repo_key = :repo_key AND name = :name"),
                {"repo_key": repo_key, "name": name},
            )

    # --- directives -------------------------------------------------------------------------
    async def record_directive(
        self, *, block_id: str, session_id: str, session_name: str, text_: str
    ) -> Directive:
        """Write down what would be sent, and to whom. Sending is a separate, human act."""
        directive = Directive(
            id=_new_id(),
            block_id=block_id,
            session_id=session_id,
            session_name=session_name,
            text=text_,
            created_at=_now_ms(),
        )
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO directive (id, block_id, session_id, session_name, text, "
                    "created_at, sent_at) VALUES (:id, :block_id, :session_id, :session_name, "
                    ":text, :created_at, NULL)"
                ),
                directive.model_dump(exclude={"sent_at"}),
            )
        return directive

    async def directives(self, *, limit: int = 50) -> list[Directive]:
        async with self.engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT id, block_id, session_id, session_name, text, created_at, sent_at, "
                    "agent_id, dispatched_at FROM directive ORDER BY created_at DESC LIMIT :limit"
                ),
                {"limit": limit},
            )
            return [Directive(**row._mapping) for row in rows]

    async def directive(self, directive_id: str) -> Directive | None:
        async with self.engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT id, block_id, session_id, session_name, text, created_at, sent_at, "
                    "agent_id, dispatched_at FROM directive WHERE id = :id"
                ),
                {"id": directive_id},
            )
            row = rows.first()
            return None if row is None else Directive(**row._mapping)

    async def mark_directive_dispatched(self, directive_id: str, agent_id: str) -> None:
        """Written after the agent exists, so a row here means a session there (docs/adr/0006).

        Only once: a second click on an instruction that already started one does nothing, the way
        a second click on a filed idea does nothing. Starting the same work twice is two agents in
        two worktrees editing the same repository.
        """
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE directive SET agent_id = :agent_id, dispatched_at = :t "
                    "WHERE id = :id AND agent_id IS NULL"
                ),
                {"agent_id": agent_id, "t": _now_ms(), "id": directive_id},
            )

    async def mark_directive_sent(self, directive_id: str) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                text("UPDATE directive SET sent_at = :t WHERE id = :id AND sent_at IS NULL"),
                {"t": _now_ms(), "id": directive_id},
            )

    # --- ideas ----------------------------------------------------------------------------
    async def create_idea(
        self,
        *,
        text_: str,
        summary: str,
        source_kind: SourceKind,
        source_ref: str | None = None,
        context: dict[str, Any] | None = None,
        block_id: str | None = None,
        parent_id: str | None = None,
        project_key: str | None = None,
    ) -> Idea:
        idea = Idea(
            id=_new_id(),
            block_id=block_id,
            parent_id=parent_id,
            project_key=project_key,
            text=text_,
            summary=summary,
            state="new",
            source_kind=source_kind,
            source_ref=source_ref,
            context=context or {},
            created_at=_now_ms(),
        )
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO idea (id, block_id, text, summary, state, source_kind, "
                    "source_ref, context, created_at, parent_id, project_key) VALUES (:id, "
                    ":block_id, :text, :summary, :state, :source_kind, :source_ref, :context, "
                    ":created_at, :parent_id, :project_key)"
                ),
                {**idea.model_dump(exclude={"context"}), "context": json.dumps(idea.context)},
            )
        return idea

    async def delete_idea(self, idea_id: str) -> None:
        """Remove an idea that turned out to be several, and only that.

        The one caller is the splitter, undoing its own placeholder within seconds of writing it
        and only while nothing has happened to it. Anything a human has touched — a state, a
        summary, a draft — is not deleted by this program; `dropped` is the state for that
        (docs/05-ideas.md).
        """
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    "DELETE FROM idea WHERE id = :id AND state = 'new' "
                    "AND NOT EXISTS (SELECT 1 FROM draft WHERE draft.idea_id = idea.id)"
                ),
                {"id": idea_id},
            )

    async def set_idea_state(self, idea_id: str, state: IdeaState) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                text("UPDATE idea SET state = :state WHERE id = :id"),
                {"id": idea_id, "state": state},
            )

    async def set_idea_summary(
        self, idea_id: str, summary: str, *, only_if: str | None = None
    ) -> None:
        """The summary is editable; `text` is not, and no statement here writes it.

        `only_if` is a compare-and-set, and it exists because the two writers of this column race.
        A capture stores a fallback line and starts a run to improve it; a human can edit the line
        in the seconds that run takes. Without the guard the generated summary lands last and the
        human's words are gone — the tool overwriting the person it is for.
        """
        async with self.engine.begin() as conn:
            if only_if is None:
                await conn.execute(
                    text("UPDATE idea SET summary = :summary WHERE id = :id"),
                    {"id": idea_id, "summary": summary},
                )
            else:
                await conn.execute(
                    text(
                        "UPDATE idea SET summary = :summary WHERE id = :id AND summary = :only_if"
                    ),
                    {"id": idea_id, "summary": summary, "only_if": only_if},
                )

    async def ideas(self, *, state: IdeaState | None = None, limit: int = 200) -> list[Idea]:
        async with self.engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT id, block_id, text, summary, state, source_kind, source_ref, "
                    "context, created_at, parent_id, project_key, size, shape, appraised_at FROM idea "
                    "WHERE (:state IS NULL OR state = :state) ORDER BY id DESC LIMIT :limit"
                ),
                {"state": state, "limit": limit},
            )
            return [self._idea(row._mapping) for row in rows]

    async def unappraised_ideas(self, limit: int = 5) -> list[Idea]:
        """Ideas a background pass has not read yet (022-idea-appraisal.sql).

        A handful at a time: the pass costs one model call each, and a sweep that took sixty in
        one tick would be a sweep that hurts on the day somebody pastes a meeting into the box.
        """
        async with self.engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT id, block_id, text, summary, state, source_kind, source_ref, "
                    "context, created_at, parent_id, project_key, size, shape, appraised_at "
                    "FROM idea WHERE appraised_at IS NULL AND state IN ('new', 'kept') "
                    "ORDER BY id DESC LIMIT :limit"
                ),
                {"limit": limit},
            )
            return [self._idea(row._mapping) for row in rows]

    async def appraise_idea(self, idea_id: str, *, size: str, shape: str) -> None:
        """What the pass made of it. Never touches `state`, which is the human's column."""
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE idea SET size = :size, shape = :shape, appraised_at = :t WHERE id = :id"
                ),
                {"size": size, "shape": shape, "t": _now_ms(), "id": idea_id},
            )

    # --- tickets that say they are stuck (026-tracker-blockers.sql) ---------------------------
    async def replace_tracker_blockers(
        self, repo_key: str, found: Sequence[tuple[str, str, str]]
    ) -> None:
        """What this project's board says is blocked, as of now.

        Replaced rather than merged: a ticket somebody unblocked stops being a blocker without
        anybody having to tell this console, which is the only way this stays true.
        """
        async with self.engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM tracker_blocker WHERE repo_key = :repo_key"),
                {"repo_key": repo_key},
            )
            for key, summary, said in found:
                await conn.execute(
                    text(
                        "INSERT INTO tracker_blocker (key, repo_key, summary, said, seen_at) "
                        "VALUES (:key, :repo_key, :summary, :said, :t)"
                    ),
                    {
                        "key": key,
                        "repo_key": repo_key,
                        "summary": summary[:200],
                        "said": said[:300],
                        "t": _now_ms(),
                    },
                )

    async def tracker_blockers(self) -> list[TrackerBlocker]:
        async with self.engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT key, repo_key, summary, said, seen_at FROM tracker_blocker "
                    "ORDER BY seen_at DESC"
                )
            )
            return [TrackerBlocker(**row._mapping) for row in rows]

    # --- the plan a session's tokens are spent against (025-subscriptions.sql) ----------------
    async def add_subscription(
        self, *, name: str, service: str = "", limit_tokens: int | None = None
    ) -> Subscription | None:
        if not name.strip():
            return None
        row = Subscription(
            id=_new_id(),
            name=name.strip()[:60],
            service=service.strip()[:60],
            limit_tokens=limit_tokens if limit_tokens and limit_tokens > 0 else None,
            created_at=_now_ms(),
        )
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO subscription (id, name, service, limit_tokens, created_at) "
                    "VALUES (:id, :name, :service, :limit_tokens, :created_at)"
                ),
                row.model_dump(),
            )
        return row

    async def subscriptions(self) -> list[Subscription]:
        async with self.engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT id, name, service, limit_tokens, created_at FROM subscription "
                    "ORDER BY created_at"
                )
            )
            return [Subscription(**row._mapping) for row in rows]

    async def drop_subscription(self, subscription_id: str) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM session_subscription WHERE subscription_id = :id"),
                {"id": subscription_id},
            )
            await conn.execute(
                text("DELETE FROM subscription WHERE id = :id"), {"id": subscription_id}
            )

    async def move_session(
        self, short_id: str, subscription_id: str, *, until: int | None = None
    ) -> None:
        """Put one session on a subscription, or take it off with an empty id.

        `until` is what "temporarily" means: after it the row is ignored and the session goes back
        to wherever it was.
        """
        async with self.engine.begin() as conn:
            if not subscription_id:
                await conn.execute(
                    text("DELETE FROM session_subscription WHERE short_id = :short_id"),
                    {"short_id": short_id},
                )
                return
            await conn.execute(
                text(
                    "INSERT INTO session_subscription (short_id, subscription_id, until, moved_at) "
                    "VALUES (:short_id, :subscription_id, :until, :t) "
                    "ON CONFLICT (short_id) DO UPDATE SET subscription_id = :subscription_id, "
                    "until = :until, moved_at = :t"
                ),
                {
                    "short_id": short_id,
                    "subscription_id": subscription_id,
                    "until": until,
                    "t": _now_ms(),
                },
            )

    async def session_subscriptions(self) -> dict[str, str]:
        """Which subscription each session is on, by short id. A move that has expired is gone."""
        now = _now_ms()
        async with self.engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT short_id, subscription_id FROM session_subscription "
                    "WHERE until IS NULL OR until > :now"
                ),
                {"now": now},
            )
            return {str(row[0]): str(row[1]) for row in rows}

    # --- how ideas relate to each other (024-idea-links.sql) ----------------------------------
    async def link_ideas(self, *, from_id: str, to_id: str, kind: LinkKind) -> IdeaLink | None:
        """Record that one idea needs, or touches, another.

        Refuses a link from an idea to itself, and refuses one that is already there — both are a
        misclick rather than something to store twice.
        """
        if from_id == to_id or not from_id or not to_id:
            return None
        row = IdeaLink(id=_new_id(), from_id=from_id, to_id=to_id, kind=kind, created_at=_now_ms())
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT OR IGNORE INTO idea_link (id, from_id, to_id, kind, created_at) "
                    "VALUES (:id, :from_id, :to_id, :kind, :created_at)"
                ),
                row.model_dump(),
            )
        return row

    async def idea_links(self) -> list[IdeaLink]:
        async with self.engine.connect() as conn:
            rows = await conn.execute(
                text("SELECT id, from_id, to_id, kind, created_at FROM idea_link ORDER BY id")
            )
            return [IdeaLink(**row._mapping) for row in rows]

    async def unlink_ideas(self, link_id: str) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(text("DELETE FROM idea_link WHERE id = :id"), {"id": link_id})

    # --- the signature an instance was told to keep (023-canary.sql) --------------------------
    async def keep_canary(self, short_id: str, name: str) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO canary (short_id, name, started_at) "
                    "VALUES (:short_id, :name, :t) "
                    "ON CONFLICT (short_id) DO UPDATE SET name = :name, started_at = :t"
                ),
                {"short_id": short_id, "name": name, "t": _now_ms()},
            )

    async def canaries(self) -> dict[str, str]:
        """Every session this console told to sign its replies, by short id."""
        async with self.engine.connect() as conn:
            rows = await conn.execute(text("SELECT short_id, name FROM canary"))
            return {str(row[0]): str(row[1]) for row in rows}

    # --- the names somebody uses for things (021-glossary.sql) --------------------------------
    async def add_term(self, *, repo_key: str, term: str, means: str) -> Term | None:
        """A word and what it means. Nothing without both halves — a term with no meaning in a
        glossary is worse than no entry, because it reads as one."""
        if not term.strip() or not means.strip():
            return None
        row = Term(
            id=_new_id(),
            repo_key=repo_key,
            term=term.strip()[:80],
            means=means.strip()[:500],
            created_at=_now_ms(),
        )
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO glossary (id, repo_key, term, means, created_at) "
                    "VALUES (:id, :repo_key, :term, :means, :created_at)"
                ),
                row.model_dump(),
            )
        return row

    async def terms(self, repo_key: str = "", *, everywhere: bool = True) -> list[Term]:
        """This project's words, and the ones that mean the same thing everywhere.

        `everywhere` is what makes the empty key useful: a word defined once, for every project,
        without writing it into each of them.
        """
        async with self.engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT id, repo_key, term, means, created_at FROM glossary "
                    "WHERE repo_key = :repo_key OR (:everywhere AND repo_key = '') "
                    "ORDER BY term COLLATE NOCASE"
                ),
                {"repo_key": repo_key, "everywhere": everywhere},
            )
            return [Term(**row._mapping) for row in rows]

    async def drop_term(self, term_id: str) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(text("DELETE FROM glossary WHERE id = :id"), {"id": term_id})

    # --- what anybody working in a project should know (020-project-note.sql) -----------------
    async def project_note(self, repo_key: str) -> str:
        async with self.engine.connect() as conn:
            rows = await conn.execute(
                text("SELECT body FROM project_note WHERE repo_key = :repo_key"),
                {"repo_key": repo_key},
            )
            row = rows.first()
            return "" if row is None else str(row[0])

    async def set_project_note(self, repo_key: str, body: str) -> None:
        """One body of text per project. Empty clears it rather than leaving a heading with
        nothing under it in every briefing."""
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO project_note (repo_key, body, updated_at) "
                    "VALUES (:repo_key, :body, :t) "
                    "ON CONFLICT (repo_key) DO UPDATE SET body = :body, updated_at = :t"
                ),
                {"repo_key": repo_key, "body": body.strip(), "t": _now_ms()},
            )

    # --- the handful of choices a person makes about the console itself -----------------------
    async def setting(self, key: str, default: str = "") -> str:
        async with self.engine.connect() as conn:
            rows = await conn.execute(
                text("SELECT value FROM setting WHERE key = :key"), {"key": key}
            )
            row = rows.first()
            return default if row is None else str(row[0])

    async def set_setting(self, key: str, value: str) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO setting (key, value) VALUES (:key, :value) "
                    "ON CONFLICT (key) DO UPDATE SET value = :value"
                ),
                {"key": key, "value": value},
            )

    async def set_idea_project(self, idea_id: str, project_key: str | None) -> None:
        """Point an idea at a project, or at nothing in particular."""
        async with self.engine.begin() as conn:
            await conn.execute(
                text("UPDATE idea SET project_key = :project_key WHERE id = :id"),
                {"project_key": project_key or None, "id": idea_id},
            )

    async def set_idea_parent(self, idea_id: str, parent_id: str | None) -> bool:
        """Put one idea under another, or take it back out. `False` when it would make a loop.

        A parent that is its own descendant renders forever, so the walk happens here rather than
        in the template that would hang on it.
        """
        if parent_id == idea_id:
            return False
        if parent_id is not None:
            seen = {idea_id}
            walking: str | None = parent_id
            while walking is not None:
                if walking in seen:
                    return False
                seen.add(walking)
                above = await self.idea(walking)
                walking = above.parent_id if above else None

        async with self.engine.begin() as conn:
            await conn.execute(
                text("UPDATE idea SET parent_id = :parent_id WHERE id = :id"),
                {"parent_id": parent_id, "id": idea_id},
            )
        return True

    async def idea(self, idea_id: str) -> Idea | None:
        async with self.engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT id, block_id, text, summary, state, source_kind, source_ref, "
                    "context, created_at, parent_id, project_key, size, shape, appraised_at "
                    "FROM idea WHERE id = :id"
                ),
                {"id": idea_id},
            )
            row = rows.first()
            return None if row is None else self._idea(row._mapping)

    @staticmethod
    def _idea(row: Any) -> Idea:
        fields = dict(row)
        # The context carries a project, a branch and a session's generated title — all of it read
        # off a transcript, none of it typed by the human whose thought this is.
        fields["context"] = json.loads(scrub(fields["context"]))
        return Idea(**fields)

    # --- viewers ------------------------------------------------------------------------
    async def create_viewer(self, name: str) -> tuple[Viewer, str]:
        """Mint a link for one named person. The token is returned once and never again."""
        token = new_token()
        viewer = Viewer(id=_new_id(), name=name, created_at=_now_ms())
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO viewer (id, name, token_hash, created_at, revoked_at) "
                    "VALUES (:id, :name, :token_hash, :created_at, NULL)"
                ),
                {**viewer.model_dump(exclude={"revoked_at"}), "token_hash": token_hash(token)},
            )
        return viewer, token

    async def viewer_for(self, token: str) -> Viewer | None:
        """The viewer this token names, or `None` — revoked included, because revoked is `None`."""
        async with self.engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT id, name, created_at, revoked_at FROM viewer "
                    "WHERE token_hash = :token_hash AND revoked_at IS NULL"
                ),
                {"token_hash": token_hash(token)},
            )
            row = rows.first()
            return None if row is None else Viewer(**row._mapping)

    async def viewers(self) -> list[Viewer]:
        async with self.engine.connect() as conn:
            rows = await conn.execute(
                text("SELECT id, name, created_at, revoked_at FROM viewer ORDER BY id DESC")
            )
            return [Viewer(**row._mapping) for row in rows]

    async def revoke_viewer(self, viewer_id: str) -> None:
        """A timestamp rather than a delete: an audit asks "until when", not "was there one"."""
        async with self.engine.begin() as conn:
            await conn.execute(
                text("UPDATE viewer SET revoked_at = :t WHERE id = :id AND revoked_at IS NULL"),
                {"id": viewer_id, "t": _now_ms()},
            )

    # --- projects a human declared ---------------------------------------------------------
    async def create_group(self, name: str) -> Group:
        """Start a project that is more than one repository."""
        group = Group(id=_new_id(), name=name, created_at=_now_ms())
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO project_group (id, name, created_at) "
                    "VALUES (:id, :name, :created_at)"
                ),
                group.model_dump(exclude={"repo_keys"}),
            )
        return group

    async def add_to_group(self, group_id: str, repo_key: str) -> None:
        """A repository belongs to at most one declared project; the newest claim wins.

        Two groups claiming one repository would put the same sessions in two places on the board,
        and a board that shows a session twice is a board you count twice.
        """
        async with self.engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM project_member WHERE repo_key = :repo_key"),
                {"repo_key": repo_key},
            )
            await conn.execute(
                text(
                    "INSERT INTO project_member (group_id, repo_key, added_at) "
                    "VALUES (:group_id, :repo_key, :added_at)"
                ),
                {"group_id": group_id, "repo_key": repo_key, "added_at": _now_ms()},
            )

    async def remove_from_group(self, repo_key: str) -> None:
        """Ungrouping returns a repository to being its own project. Nothing is lost."""
        async with self.engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM project_member WHERE repo_key = :repo_key"),
                {"repo_key": repo_key},
            )

    async def delete_group(self, group_id: str) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM project_member WHERE group_id = :id"), {"id": group_id}
            )
            await conn.execute(text("DELETE FROM project_group WHERE id = :id"), {"id": group_id})

    async def groups(self) -> list[Group]:
        async with self.engine.connect() as conn:
            rows = await conn.execute(
                text("SELECT id, name, created_at FROM project_group ORDER BY created_at")
            )
            found = [Group(**row._mapping) for row in rows]
            members = await conn.execute(
                text("SELECT group_id, repo_key FROM project_member ORDER BY added_at")
            )
            by_group: dict[str, list[str]] = {}
            for group_id, repo_key in members:
                by_group.setdefault(group_id, []).append(repo_key)
        return [
            group.model_copy(update={"repo_keys": by_group.get(group.id, [])}) for group in found
        ]

    # --- drafts ---------------------------------------------------------------------------
    async def create_draft(self, *, idea_id: str, kind: DraftKind, body: str) -> Draft:
        draft = Draft(id=_new_id(), idea_id=idea_id, kind=kind, body=body, created_at=_now_ms())
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO draft (id, idea_id, kind, body, created_at) "
                    "VALUES (:id, :idea_id, :kind, :body, :created_at)"
                ),
                draft.model_dump(),
            )
        return draft

    async def drafted(self, kind: DraftKind) -> set[str]:
        """The ideas that have a draft of this kind, which is the same as "somebody read one".

        Filing needs it: what goes to a tracker is the ticket a human asked for and could read,
        never a body generated on the way out (docs/adr/0005).
        """
        async with self.engine.connect() as conn:
            rows = await conn.execute(
                text("SELECT DISTINCT idea_id FROM draft WHERE kind = :kind"), {"kind": kind}
            )
            return {str(row._mapping["idea_id"]) for row in rows}

    async def drafts_for(self, idea_id: str) -> list[Draft]:
        async with self.engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT id, idea_id, kind, body, created_at FROM draft "
                    "WHERE idea_id = :idea_id ORDER BY id DESC"
                ),
                {"idea_id": idea_id},
            )
            return [Draft(**{**row._mapping, "body": scrub(row._mapping["body"])}) for row in rows]
