-- The four tables of design/02-data-model.md, and the one that records which of these files has
-- been applied. Timestamps are Unix milliseconds throughout, matching what the registry writes,
-- so that a comparison between something this tool stored and something Claude Code wrote never
-- needs a conversion nobody remembers to do.
--
-- Forward-only. This file is version 1; the next change is `002-<name>.sql` beside it and is
-- applied after it, never instead of it (docs/adr/0003 — plain SQL at startup, no Alembic).

CREATE TABLE IF NOT EXISTS schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at INTEGER NOT NULL
);

CREATE TABLE thread (
    id          TEXT PRIMARY KEY,
    subject     TEXT NOT NULL,          -- generated, editable
    created_at  INTEGER NOT NULL,
    closed_at   INTEGER
);

CREATE TABLE block (
    id          TEXT PRIMARY KEY,
    thread_id   TEXT NOT NULL REFERENCES thread(id),
    kind        TEXT NOT NULL,          -- question | idea | observation
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
    -- Where it came from, which is most of an idea's meaning a week later. Deliberately a source
    -- rather than a session: a meeting is the third kind and costs one JSON column today.
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

-- A block list is read newest-first and an idea list is read by state; nothing else is queried by
-- anything but its primary key.
CREATE INDEX block_by_thread ON block (thread_id);
CREATE INDEX idea_by_state ON idea (state);
