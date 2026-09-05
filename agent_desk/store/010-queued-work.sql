-- Work somebody approved, and the arming that lets it start on its own (docs/adr/0007).
--
-- The distinction this schema exists to hold: a human decides *what*, and the loop decides *when*.
-- Every row in `task` was written by a person and put here by a person; nothing enqueues itself,
-- and there is no column for who should do it or how big it is, because that is the backlog
-- ../docs/08-non-goals.md §4 refuses and this is a list of things somebody said to do.
--
-- `autostart` is per project and absent by default: a project with no row here behaves exactly as
-- it did before that ADR. `failures` is what disarms it — a rule that keeps firing into a broken
-- condition is the three-in-the-morning failure in its most ordinary form.

CREATE TABLE task (
    id          TEXT PRIMARY KEY,
    repo_key    TEXT NOT NULL,          -- which project's checkout it runs in
    cwd         TEXT NOT NULL,          -- where, resolved when it was queued
    title       TEXT NOT NULL,          -- what it is, in a human's words
    instruction TEXT NOT NULL,          -- what the agent is told, verbatim
    source_kind TEXT NOT NULL,          -- idea | instruction | typed
    source_ref  TEXT,                   -- the idea or directive it came from
    queued_at   INTEGER NOT NULL,
    started_at  INTEGER,
    agent_id    TEXT,                   -- the id `claude attach|logs|stop` take
    failed_at   INTEGER,
    detail      TEXT                    -- why it did not start, in the CLI's own words
);

CREATE INDEX task_waiting ON task (repo_key, started_at, failed_at);

CREATE TABLE autostart (
    repo_key    TEXT PRIMARY KEY,
    armed_at    INTEGER,                -- NULL is disarmed, which is the default everywhere
    per_hour    INTEGER NOT NULL,       -- the budget, checked before every start
    failures    INTEGER NOT NULL DEFAULT 0,
    disarmed_why TEXT
);
