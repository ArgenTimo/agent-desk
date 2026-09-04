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
import secrets
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import bindparam, event, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from ulid import ULID

from agent_desk.store.redact import scrub, scrub_optional

BlockKind = Literal["question", "idea", "observation"]
BlockState = Literal["queued", "running", "answered", "failed", "cancelled"]
IdeaState = Literal["new", "kept", "promoted", "dropped"]
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
                    "created_at, finished_at FROM block WHERE thread_id = :thread_id ORDER BY id"
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
                    "created_at, finished_at FROM block ORDER BY id DESC LIMIT :limit"
                ),
                {"limit": limit},
            )
            return [self._block(row._mapping) for row in rows]

    async def block(self, block_id: str) -> Block | None:
        async with self.engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT id, thread_id, kind, state, input, answer, error, thread_set_by, "
                    "created_at, finished_at FROM block WHERE id = :id"
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
        return Block(**fields)

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
    ) -> Idea:
        idea = Idea(
            id=_new_id(),
            block_id=block_id,
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
                    "source_ref, context, created_at) VALUES (:id, :block_id, :text, :summary, "
                    ":state, :source_kind, :source_ref, :context, :created_at)"
                ),
                {**idea.model_dump(exclude={"context"}), "context": json.dumps(idea.context)},
            )
        return idea

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
                    "context, created_at FROM idea "
                    "WHERE (:state IS NULL OR state = :state) ORDER BY id DESC LIMIT :limit"
                ),
                {"state": state, "limit": limit},
            )
            return [self._idea(row._mapping) for row in rows]

    async def idea(self, idea_id: str) -> Idea | None:
        async with self.engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT id, block_id, text, summary, state, source_kind, source_ref, "
                    "context, created_at FROM idea WHERE id = :id"
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
