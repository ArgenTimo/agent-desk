# Data model

One SQLite file at `~/.local/share/agent-desk/agent-desk.db`. Four tables, and a fifth that
arrived with the shared view. Timestamps are
Unix milliseconds, matching what the registry writes, so that a comparison never needs a
conversion nobody remembers to do.

```sql
CREATE TABLE thread (
    id          TEXT PRIMARY KEY,
    subject     TEXT NOT NULL,          -- generated, editable
    created_at  INTEGER NOT NULL,
    closed_at   INTEGER
);

CREATE TABLE block (
    id          TEXT PRIMARY KEY,
    thread_id   TEXT NOT NULL REFERENCES thread(id),
    kind        TEXT NOT NULL,          -- question | idea | instruction | observation
    state       TEXT NOT NULL,          -- queued | running | answered | failed | cancelled
    input       TEXT NOT NULL,          -- verbatim, never replaced by a summary
    answer      TEXT,
    error       TEXT,
    thread_set_by TEXT NOT NULL,        -- classifier | human — the override-rate metric
    created_at  INTEGER NOT NULL,
    finished_at INTEGER
);

CREATE TABLE idea (
    id          TEXT PRIMARY KEY,
    block_id    TEXT REFERENCES block(id),
    text        TEXT NOT NULL,          -- verbatim
    summary     TEXT NOT NULL,          -- generated, editable
    state       TEXT NOT NULL,          -- new | kept | promoted | dropped
    -- Where it came from, which is most of an idea's meaning a week later.
    -- Deliberately a source rather than a session: see below.
    source_kind TEXT NOT NULL,          -- session | typed | meeting
    source_ref  TEXT,                   -- sessionId, or a meeting id
    context     TEXT NOT NULL,          -- JSON: project, branch, title — or meeting, speaker, offset
    created_at  INTEGER NOT NULL
);

CREATE TABLE draft (
    id          TEXT PRIMARY KEY,
    idea_id     TEXT NOT NULL REFERENCES idea(id),
    kind        TEXT NOT NULL,          -- proposal | ticket | paste
    body        TEXT NOT NULL,
    created_at  INTEGER NOT NULL
);
```

```sql
-- A message somebody asked for, waiting for the click that sends it. "Tell Biba to test it again"
-- is not a question and not an idea: it is an instruction, and the honest thing to do with one is
-- to prepare it and stop (docs/adr/0002, docs/08-non-goals.md §2). `sent_at` records the click if
-- it ever comes, and only on an actual delivery — a refused message is still waiting.
CREATE TABLE directive (
    id           TEXT PRIMARY KEY,
    block_id     TEXT NOT NULL REFERENCES block(id),
    session_id   TEXT NOT NULL,          -- the registry's id, never a copy of the session
    session_name TEXT NOT NULL,          -- what it was called then, for reading a week later
    text         TEXT NOT NULL,          -- verbatim, ready for the panel
    created_at   INTEGER NOT NULL,
    sent_at      INTEGER
);
```

```sql
-- Where a project lives besides on this disk: a tracker, a repository page, a dashboard. Nothing
-- on disk derives these — an `origin` gives a repository, never a board — so a human types them
-- once and they are one click away afterwards.
--
-- What is deliberately not here is a credential. This is a plain SQLite file that a second
-- application already serves a redacted view out of (../docs/07-security.md), with no encryption
-- and no audit of who read it. `token_env` records the *name* of an environment variable and
-- never a value, so the secret stays where the operating system already keeps secrets and the
-- console can still say what it would use.
CREATE TABLE project_link (
    repo_key    TEXT NOT NULL,
    name        TEXT NOT NULL,          -- jira | github | anything a human types
    url         TEXT NOT NULL,
    token_env   TEXT,                   -- the variable, never the token
    added_at    INTEGER NOT NULL,
    PRIMARY KEY (repo_key, name)
);
```

```sql
-- Phase 4. One row per person who may open the shared ideas list.
CREATE TABLE viewer (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,          -- who this link is for, in a human's words
    token_hash  TEXT NOT NULL UNIQUE,   -- sha256 of 256 random bits; the token itself is not here
    created_at  INTEGER NOT NULL,
    revoked_at  INTEGER                 -- a timestamp, not a delete: an audit asks "until when"
);
```

```sql
-- A project a human declared, over the top of what the repositories say. By default a project IS
-- a repository and nobody has to say anything; this is for the case that default cannot know —
-- an API and an app in two repositories that are one product.
CREATE TABLE project_group (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  INTEGER NOT NULL
);

CREATE TABLE project_member (
    group_id    TEXT NOT NULL REFERENCES project_group(id),
    repo_key    TEXT NOT NULL,          -- `origin:owner/repo`, or a path when there is no remote
    added_at    INTEGER NOT NULL,
    PRIMARY KEY (group_id, repo_key)
);
```

Note what these two tables do *not* hold: sessions, instances, or which session belongs where.
Those are read fresh from the registry every time, for the same reason there is no session table —
a second copy of a fact goes wrong quietly. A declared project stores only the part nobody can
derive: that a human said two repositories are one thing.

## What is deliberately not stored

**No transcript content.** Tails are read on demand and rendered. A copy would be large, stale, and
a second thing to redact ([`../docs/07-security.md`](../docs/07-security.md)).

**No session table.** Sessions are projected from the registry on every read. The registry is the
truth and it is already fast; a cached copy would be a second truth that goes wrong quietly, which
is the failure [`../docs/adr/0004`](../docs/adr/0004-the-transcript-format-is-not-a-contract.md) is
about.

**No priority, assignee or estimate on an idea.** That is a backlog
([`../docs/08-non-goals.md`](../docs/08-non-goals.md) §4).

**No token or cost accounting.** The `claude` CLI reports it and nothing here is decided by it.

**No credentials of any kind.** Not the CLI's, which this program never opens
([`../docs/07-security.md`](../docs/07-security.md)), and not a tracker's, which a human might
reasonably want it to hold. `project_link.token_env` names the environment variable instead. A
token in this file would be a token in a database with no encryption, no rotation and no record of
who read it, in a process that also serves a page to other people.

## Two fields that exist for a reason

`block.thread_set_by` records whether the thread was chosen by the classifier or corrected by a
human. That column *is* the Phase 2 measurement in
[`../docs/09-roadmap.md`](../docs/09-roadmap.md): a correction rate above roughly one in four means
the classifier should be replaced by a default and a click.

`block.input` and `idea.text` hold the original text and are never overwritten by a generated
summary. The summary is a convenience for scanning; losing the thought to it would be the tool
failing at the one job it has ([`../docs/05-ideas.md`](../docs/05-ideas.md)).

`idea.source_kind` / `source_ref` / `context` replace what would naturally have been three columns
— `project`, `branch`, `session_id` — shaped like a Claude Code session, which is one source of one
kind. A meeting-sourced idea sets `source_kind = "meeting"` and puts the meeting, the speaker and
the timestamp in `context`, and nothing else in the store, the inbox or the drafts changes
([`../docs/10-meeting-intake.md`](../docs/10-meeting-intake.md)).

This is the only concession made to a future version, it costs one JSON column today, and it is
made now because a schema is cheap to shape before it holds a year of rows and expensive
afterwards. No interface is generalised and no plugin system exists — that would be `CLAUDE.md`
rule 2 broken in the name of a roadmap.

## Migrations

Plain SQL files applied in order at startup, recorded in a `schema_version` table. Forward-only. No
Alembic ([`../docs/adr/0003`](../docs/adr/0003-sqlite-and-one-process.md)).

## Crash behaviour

A block that was `running` when the process died is reopened as `failed` with `error =
"interrupted"`, never as `answered`. A restart that silently promotes an unfinished block to
answered would produce an empty answer that looks complete
([`../docs/04-threads-and-blocks.md`](../docs/04-threads-and-blocks.md)).
